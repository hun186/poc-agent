# Dual-Mode Word Report API Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with TDD and verification evidence. Preserve the existing synchronous Word endpoint as a supported first-class API; add the asynchronous Job API alongside it rather than replacing it.

**Goal:** Keep the existing one-call synchronous `POST /v1/report/word` workflow for convenient manual/single-report use, while adding a durable asynchronous Job API for 10–30+ minute reports, bulk scheduling, client disconnect tolerance, and later automation expansion.

**Architecture:** Both API modes must call the same `execute_agent_turn()` / `ExportWordService` execution core. The synchronous endpoint holds the HTTP connection until the report completes and returns DOCX bytes directly. The asynchronous endpoint persists a job record in local SQLite, returns `202 Accepted` immediately, and a background worker later executes the same Agent turn, writes the DOCX artifact atomically, and exposes status/download endpoints. Do not route async work through the synchronous HTTP endpoint, and do not use `state.json` as the async job database.

**Tech Stack:** FastAPI, Pydantic 2, Python stdlib `sqlite3`, Python threads/background worker loop, existing Agent pipeline, existing `ExportWordService`, pytest, python-docx.

**Spec:** This document is the design and implementation source of truth for this change. Existing project source and `.codex` memory remain authoritative when they reveal facts not covered here.

## Global Constraints

- Runtime source is `sra_api/`; top-level `api/` remains a compatibility shim.
- Do not change Agent routing, Elasticsearch retrieval, query refiner, report prompts, citation generation, or Word rendering semantics except where required to share the existing execution boundary.
- Preserve `POST /v1/report/word` exactly as a supported synchronous API. Job API is additive.
- Preserve existing `GET /v1/export/word` and OpenWebUI `/v1/chat/completions` behavior.
- Async jobs must not depend on a long-lived client HTTP connection after `POST /v1/report/jobs` has returned.
- Async job execution must not read its just-produced structured result back from `state.json`; it must render the current in-memory `AgentTurnResult.output` directly, exactly like the current synchronous Word endpoint.
- Initial async implementation targets the repository's current single-process Uvicorn deployment. Do not claim multi-process/multi-host queue safety.
- Do not add Redis, Celery, RQ, PostgreSQL, Airflow, Kafka, Docker services, or other external queue infrastructure in this change.
- Use SQLite only for job metadata/payload persistence; store DOCX files under a dedicated output directory.
- Default async worker concurrency must be `1` unless the existing Agent/session state is explicitly proven thread-safe for higher concurrency. Expose a configuration seam, but document concurrency >1 as not yet validated.
- Do not expose cancellation for a currently running Agent turn because the existing `answer_with_routing()` path has no cooperative cancellation boundary.
- Do not add automatic retry of failed/interrupted reports in this change; retry remains explicit client behavior to avoid accidental duplicate 30-minute executions.
- Preserve the existing OpenWebUI/editor integration trust boundary. Do not reuse Editor bearer auth for the new Job API unless a separate integration-auth feature is designed later.
- All timestamps stored by the Job API must be timezone-aware UTC ISO-8601 strings.
- User-supplied filename controls only the download filename, never the filesystem path.
- Write DOCX artifacts atomically (`.tmp` + `os.replace`) so a downloader can never receive a partially written file.
- Run dependency preflight before pytest as required by `AGENTS.md`.
- Update `.codex` project memory after implementation and record real test evidence.

---

# 1. Current Code Baseline Confirmed From `poc-agent(6)`

The implementation must build on these existing facts rather than recreating them:

- `sra_api/services/turn_execution.py` already provides `execute_agent_turn()` returning `AgentTurnResult` with `session_id`, `turn_id`, `request_id`, `output`, and `trace`.
- `sra_api/routers/export.py` already implements synchronous `POST /v1/report/word`.
- The synchronous endpoint already renders the current `turn.output` directly through `ExportWordService`; it intentionally does **not** read `state.json` before creating the DOCX.
- `sra_api/routers/chat.py` already uses the same turn execution service and exposes `context.word_export` metadata.
- `tests/test_report_word_api.py`, `tests/test_turn_execution_service.py`, and `tests/test_chat_word_export_metadata.py` already lock important compatibility behavior.
- Current `sra_api/run_api.py` starts one Uvicorn process and does not configure multiple workers, which makes a local SQLite + in-process job worker a reasonable first durable async implementation.
- `.codex/backlog.md` already records asynchronous long-running jobs as a future design area; this change promotes the bounded core of that idea while intentionally leaving distributed queues/cancellation/automatic retry for later.

## Local inspection verification note

In the planning sandbox, the repository source was inspected successfully. The local sandbox could not re-run the current pytest subset because this runtime lacks installed `smolagents` and `elasticsearch`; this is an environment dependency issue, not evidence that the current code is failing. Codex must follow `AGENTS.md`, install/verify `requirements.txt`, establish the baseline in its actual development environment, and record the real results.

---

# 2. Product Contract: Two Supported Modes

## 2.1 Synchronous mode — keep exactly because it is convenient

Use when:

- a developer is testing one prompt from Chrome DevTools / curl / Python;
- the expected report duration is short enough for configured reverse-proxy/client timeouts;
- the caller explicitly wants one request to block and immediately return a DOCX;
- interactive simplicity matters more than reconnect/recovery behavior.

Contract stays:

```http
POST /v1/report/word
Content-Type: application/json
X-Session-Id: optional-session

{
  "model": "SRA-Structured Retrieval Agent",
  "messages": [
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "filename": "report.docx"
}
```

Success:

```http
HTTP/1.1 200 OK
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; ...
X-Session-Id: ...
X-Turn-Id: ...
X-Request-Id: ...

<DOCX bytes>
```

This path may legitimately hold the HTTP connection for 10–30+ minutes. Documentation must explicitly warn that the HTTP client, Nginx/reverse proxy, load balancer, and any upstream gateway all need timeouts longer than the maximum report duration.

Recommended Nginx documentation example for this endpoint/location:

```nginx
proxy_connect_timeout 30s;
proxy_send_timeout 3600s;
proxy_read_timeout 3600s;
send_timeout 3600s;
```

If reports may exceed one hour, the deployment operator should raise those values deliberately; do not hard-code Nginx configuration into Python.

## 2.2 Asynchronous Job mode — new default for long/bulk automation

Use when:

- one report may take 10–30+ minutes;
- callers schedule tens/hundreds of reports;
- client/reverse-proxy disconnects must not lose knowledge of the job result;
- the caller needs to resume polling after restart/network loss;
- resource consumption must be bounded by a worker queue rather than client concurrency.

Create:

```http
POST /v1/report/jobs
Content-Type: application/json
X-Session-Id: recommended
Idempotency-Key: optional-but-recommended

{
  "model": "SRA-Structured Retrieval Agent",
  "messages": [
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "filename": "report.docx"
}
```

Success must return quickly after persistence, without executing the Agent inline:

```http
HTTP/1.1 202 Accepted
Location: http://host/v1/report/jobs/<job_id>
Content-Type: application/json

{
  "job_id": "rpt_...",
  "status": "queued",
  "session_id": "...",
  "request_id": "...",
  "created_at": "2026-09-01T09:30:00+00:00",
  "status_url": "http://host/v1/report/jobs/rpt_...",
  "word_url": "http://host/v1/report/jobs/rpt_.../word"
}
```

Status:

```http
GET /v1/report/jobs/{job_id}
```

Status response shape:

```json
{
  "job_id": "rpt_...",
  "status": "queued|running|completed|failed|interrupted",
  "session_id": "...",
  "request_id": "...",
  "turn_id": null,
  "created_at": "...",
  "started_at": null,
  "finished_at": null,
  "filename": "report.docx",
  "content_length": null,
  "error_code": null,
  "error_message": null,
  "status_url": "http://host/v1/report/jobs/rpt_...",
  "word_url": "http://host/v1/report/jobs/rpt_.../word"
}
```

When completed, `turn_id`, `finished_at`, and `content_length` are populated.

Download:

```http
GET /v1/report/jobs/{job_id}/word
```

- `200` + DOCX only when status is `completed` and the artifact exists.
- `409` when job exists but is `queued` or `running`.
- `409` when job is `failed` or `interrupted`; JSON detail explains there is no completed artifact.
- `404` when `job_id` does not exist.
- If DB says completed but artifact is missing, return `410 Gone` and record/return a clear artifact-missing error; do not generate a fake DOCX.

## 2.3 Idempotency contract

Support optional request header:

```http
Idempotency-Key: client-generated-stable-key
```

Rules:

1. Store the key with a SHA-256 hash of the normalized request payload and resolved session id.
2. First submission creates a job and returns `202`.
3. Repeating the same key with the same payload/session returns the existing job response and must not enqueue a duplicate Agent run.
4. Repeating the same key with a different payload/session returns `409 Conflict`.
5. Empty idempotency key is treated as absent.
6. Do not use the key as a filesystem path or job id.

This protects automation clients from duplicate 30-minute work if the create-job HTTP response is lost and the client safely retries the short POST.

---

# 3. Job State Model

Allowed states:

```text
queued -> running -> completed
                 -> failed
running --server restart--> interrupted
```

No automatic transitions out of `failed` or `interrupted` in this change.

State semantics:

- `queued`: request is durably persisted and waiting for a worker.
- `running`: a worker successfully claimed it and entered Agent execution.
- `completed`: DOCX was atomically persisted and metadata committed.
- `failed`: Agent execution, DOCX rendering, or artifact persistence failed during this run.
- `interrupted`: service startup discovered a job that had been `running` when the previous process stopped. Do not silently rerun it because doing so could duplicate an expensive report.

Queued jobs should remain queued across process restart and become eligible for a new worker after startup.

---

# 4. Storage Design

## 4.1 Environment variables

Add to `.env.example` and document:

```text
REPORT_JOB_ENABLED=1
REPORT_JOB_DB_PATH=.api_jobs/report_jobs.sqlite3
REPORT_JOB_OUTPUT_DIR=.api_jobs/reports
REPORT_JOB_WORKERS=1
REPORT_JOB_POLL_INTERVAL_SEC=1.0
REPORT_JOB_MAX_QUEUED=500
```

Behavior:

- `REPORT_JOB_ENABLED=0`: Job endpoints return `503 Service Unavailable`; synchronous `/v1/report/word` remains fully available.
- `REPORT_JOB_WORKERS`: parse as integer >= 1, but document only `1` as validated in this version.
- `REPORT_JOB_MAX_QUEUED`: before create, count `queued` + `running`; if limit reached, return `429` or `503`. Prefer `429 Too Many Requests` with a clear `detail` because the caller may retry later.

## 4.2 SQLite schema

Create `report_jobs` with at least:

```sql
CREATE TABLE IF NOT EXISTS report_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    session_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    turn_id TEXT,
    request_payload_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key TEXT,
    requested_filename TEXT,
    download_filename TEXT,
    output_path TEXT,
    content_length INTEGER,
    error_code TEXT,
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_report_jobs_status_created
ON report_jobs(status, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_report_jobs_idempotency
ON report_jobs(idempotency_key)
WHERE idempotency_key IS NOT NULL;
```

Initialize the DB with `PRAGMA journal_mode=WAL` and a sensible `busy_timeout`.

Do not store DOCX binary in SQLite.

## 4.3 Artifact path

Filesystem path must be generated from server-controlled `job_id` only:

```text
<REPORT_JOB_OUTPUT_DIR>/<job_id>.docx
```

Never join user-provided `filename` into the filesystem path.

Worker writes:

```text
<job_id>.docx.tmp
```

then calls `os.replace(tmp_path, final_path)`.

Store the safe human-facing filename returned by `ExportWordService.build_docx_bytes()` separately as `download_filename`.

---

# 5. File Structure

## Create

- `sra_api/services/report_job_store.py`
  - SQLite schema, CRUD, idempotency lookup, atomic claim, state transitions, startup recovery.
- `sra_api/services/report_job_manager.py`
  - worker lifecycle, polling loop, Agent execution, DOCX persistence.
- `sra_api/routers/report_jobs.py`
  - POST create, GET status, GET DOCX.
- `tests/test_report_job_store.py`
- `tests/test_report_job_manager.py`
- `tests/test_report_jobs_api.py`
- `docs/report_word_automation.md`
  - operator/developer guide covering both sync and async modes.

## Modify

- `sra_api/services/turn_execution.py`
  - allow background execution with an explicit `session_id` without fabricating a FastAPI `Request`.
- `sra_api/routers/export.py`
  - keep synchronous endpoint behavior; optionally reuse a small shared payload model/helper if needed, but do not redirect through Job API.
- `sra_api/main.py`
  - include `report_jobs.router`; start/stop job manager using application lifecycle.
- `.env.example`
  - add Job API configuration.
- `.gitignore`
  - ignore `.api_jobs/` unless project policy already ignores it through a broader pattern.
- `.codex/api_contract.md`
- `.codex/architecture.md`
- `.codex/decisions.md`
- `.codex/backlog.md`
- `.codex/memory.md`
- `.codex/known_issues.md` only if implementation/verification exposes a new limitation; the single-process limitation should be documented either here or in architecture/decisions even if not treated as an operational incident.

## Do not modify unless tests prove necessary

- `agent/agent.py`
- `agent/data_agent/*`
- query refiner/prompts
- Elasticsearch query code
- Word presenter/rendering internals
- Editor auth
- OpenWebUI chat contract beyond regression fixes

---

# 6. Required Interfaces

## 6.1 Refine `execute_agent_turn()` for non-HTTP workers

Current function requires a FastAPI `Request` to resolve headers even though the core Agent execution does not otherwise need an HTTP request.

Change the public interface to support both callers:

```python
def execute_agent_turn(
    *,
    payload: Any,
    request: Request | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    trace: dict | None = None,
) -> AgentTurnResult:
    ...
```

Resolution precedence must be:

1. explicit `session_id` argument if non-empty;
2. request headers if `request` exists;
3. existing `infer_session_key_from_payload(payload.messages)` fallback.

Keep all existing Chat and synchronous POST callers working by continuing to pass `request=request`.

The background worker must pass the session id stored when the Job was created:

```python
turn = execute_agent_turn(
    payload=payload,
    session_id=job.session_id,
    request_id=job.request_id,
)
```

This avoids creating a fake Starlette/FastAPI request object inside a worker thread.

## 6.2 `ReportJobStore`

Expected public methods:

```python
class ReportJobStore:
    def initialize(self) -> None: ...
    def create_job(...) -> ReportJobRecord: ...
    def get_job(self, job_id: str) -> ReportJobRecord | None: ...
    def get_by_idempotency_key(self, key: str) -> ReportJobRecord | None: ...
    def count_active(self) -> int: ...
    def claim_next_queued(self) -> ReportJobRecord | None: ...
    def mark_completed(...) -> ReportJobRecord: ...
    def mark_failed(...) -> ReportJobRecord: ...
    def mark_running_jobs_interrupted(self) -> int: ...
```

Define a focused immutable `ReportJobRecord` dataclass or equivalent typed model in the same file unless a separate model file is clearly justified.

`claim_next_queued()` must be atomic. Use a transaction such as `BEGIN IMMEDIATE`, select the oldest queued job, update only if still queued, then commit.

## 6.3 `ReportJobManager`

Expected interface:

```python
class ReportJobManager:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def wake(self) -> None: ...
    def run_job(self, job: ReportJobRecord) -> None: ...
```

The worker loop:

```text
wait for queued work / poll interval
-> claim_next_queued()
-> execute_agent_turn(... explicit session/request ids ...)
-> ExportWordService().build_docx_bytes(turn.output, filename=requested filename)
-> atomic artifact write
-> mark_completed(... turn_id, output path, final filename, content length ...)
-> on exception: remove temp artifact if present; mark_failed(...)
```

Store only a safe, truncated exception message in the DB/API. Do not persist full prompts, model raw responses, secrets, or traceback text in `error_message`.

The full traceback may still be logged through the existing server logging/telemetry path if that path is already safe.

## 6.4 Job request reconstruction

Persist the normalized JSON payload using Pydantic `model_dump(mode="json")` and reconstruct with the same payload model used by the synchronous endpoint.

Do not pickle Python objects.

Before persistence force/validate:

```text
stream = false
```

If caller sends `stream=true`, both sync and job Word endpoints return 422.

## 6.5 FastAPI lifecycle

Use a single application-scoped manager instance.

On startup:

1. initialize DB/directories;
2. mark stale `running` jobs as `interrupted`;
3. start configured worker loop(s) if enabled.

On shutdown:

1. signal workers to stop accepting new jobs;
2. do not wait forever for a 30-minute Agent call;
3. document that forced process shutdown may leave a DB row as `running`, which next startup converts to `interrupted`.

Do not spawn a new worker thread per HTTP request.

---

# 7. API Behavior Details

## 7.1 `POST /v1/report/jobs`

Algorithm:

```text
validate ReportWordPayload
-> reject stream=true
-> resolve session id using same precedence as Agent turn
-> create stable request_id now
-> normalize payload and compute request hash
-> if Idempotency-Key exists:
     find existing
     same hash/session -> return existing job without enqueue
     different hash/session -> 409
-> enforce max active queue limit
-> insert queued row
-> manager.wake()
-> return 202 + Location + URLs
```

The endpoint must never call `execute_agent_turn()` itself.

## 7.2 `GET /v1/report/jobs/{job_id}`

Return job status only; do not return the original full prompt/messages by default.

This prevents status endpoints from becoming a second prompt-data exfiltration surface.

## 7.3 `GET /v1/report/jobs/{job_id}/word`

Use `FileResponse` or equivalent file streaming from the final artifact path.

Headers should align with synchronous Word download:

```text
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: existing safe download filename helper
Content-Length: actual file size
Cache-Control: no-store
X-Session-Id
X-Turn-Id
X-Request-Id
X-Job-Id
X-Content-Type-Options: nosniff
```

Do not read `state.json` to reconstruct the report.

---

# 8. Task-by-Task TDD Implementation

## Task 1: Lock the existing synchronous behavior before adding async jobs

**Files:**
- Existing tests: `tests/test_report_word_api.py`
- Existing tests: `tests/test_turn_execution_service.py`
- Existing tests: `tests/test_chat_word_export_metadata.py`
- Existing tests: `tests/test_export_word_service.py`

**Interfaces:**
- Consumes existing `POST /v1/report/word` and `execute_agent_turn()` behavior.
- Produces a verified regression baseline.

- [ ] **Step 1: Dependency preflight**

Run from repo root:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If pip upgrade hits the known proxy 403 but requirements are already installed, record that exact condition and continue with verification; do not claim a clean install if it was not clean.

- [ ] **Step 2: Run the existing targeted baseline**

```bash
PYTHONPATH=. pytest -q \
  tests/test_turn_execution_service.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_export_word_service.py
```

Expected: tests covering the current Word behavior pass in the actual Codex environment. If an unrelated known failure appears, compare it with `.codex/known_issues.md`; do not silently normalize a new failure as pre-existing.

- [ ] **Step 3: Add/confirm a regression test that synchronous POST never calls the async manager**

After the manager module exists later, add a test that monkeypatches Job manager enqueue to raise if called, then proves `POST /v1/report/word` still succeeds through direct execution. This test may be committed with Task 6 when the manager exists.

- [ ] **Step 4: Commit only if baseline test additions were necessary**

Suggested commit:

```bash
git commit -m "test: lock synchronous Word report contract"
```

## Task 2: Decouple turn execution from mandatory HTTP Request

**Files:**
- Modify: `sra_api/services/turn_execution.py`
- Test: `tests/test_turn_execution_service.py`

**Interfaces:**
- Produces `execute_agent_turn(..., request=None, session_id="...")` for background jobs.
- Existing HTTP callers continue to pass `request` unchanged.

- [ ] **Step 1: Write failing explicit-session test**

Add a test equivalent to:

```python
def test_execute_agent_turn_can_run_without_http_request_when_session_id_is_explicit(monkeypatch):
    # mock answer_with_routing/sessions/memory/snapshot as current tests do
    payload = SimpleNamespace(
        messages=[ChatMessage(role="user", content="背景工作")],
        model="model",
    )
    result = turn_execution.execute_agent_turn(
        payload=payload,
        request=None,
        session_id="job-session",
        request_id="job-request",
    )
    assert result.session_id == "job-session"
    assert result.request_id == "job-request"
```

Also add a precedence test: explicit `session_id` wins over a conflicting request header.

- [ ] **Step 2: Run only these tests and confirm failure before implementation**

```bash
PYTHONPATH=. pytest -q tests/test_turn_execution_service.py
```

- [ ] **Step 3: Implement minimal signature/session-resolution change**

Keep existing header precedence when no explicit session is supplied.

- [ ] **Step 4: Re-run targeted tests**

```bash
PYTHONPATH=. pytest -q tests/test_turn_execution_service.py tests/test_report_word_api.py tests/test_chat_word_export_metadata.py
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add sra_api/services/turn_execution.py tests/test_turn_execution_service.py
git commit -m "refactor: allow Agent turns outside HTTP requests"
```

## Task 3: Add durable SQLite Job store

**Files:**
- Create: `sra_api/services/report_job_store.py`
- Create: `tests/test_report_job_store.py`

**Interfaces:**
- Produces `ReportJobStore` and `ReportJobRecord` used by manager/router.

- [ ] **Step 1: Write schema/create/get failing test using pytest `tmp_path`**

The test must initialize a temporary SQLite file, create one queued record, then reopen a new `ReportJobStore` instance against the same file and retrieve the same record. This proves persistence is not process-memory-only.

- [ ] **Step 2: Write idempotency tests**

Cover:

```text
same key + same hash/session -> existing record can be found
duplicate key cannot create a second record
different keys create different records
```

- [ ] **Step 3: Write atomic claim ordering test**

Create two queued jobs with ordered timestamps. First `claim_next_queued()` returns oldest and marks it `running`; second call returns the next one.

- [ ] **Step 4: Write startup recovery test**

Create a job, claim it to `running`, construct a fresh store, call `mark_running_jobs_interrupted()`, assert status becomes `interrupted` while queued jobs remain queued.

- [ ] **Step 5: Implement store with WAL and transaction-safe claim**

Use server-generated IDs, for example:

```python
job_id = f"rpt_{uuid.uuid4().hex}"
```

Use UTC helper:

```python
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 6: Run store tests**

```bash
PYTHONPATH=. pytest -q tests/test_report_job_store.py
```

- [ ] **Step 7: Commit**

```bash
git add sra_api/services/report_job_store.py tests/test_report_job_store.py
git commit -m "feat: persist report jobs in SQLite"
```

## Task 4: Add Job manager and bounded worker execution

**Files:**
- Create: `sra_api/services/report_job_manager.py`
- Create: `tests/test_report_job_manager.py`

**Interfaces:**
- Consumes `ReportJobStore`, `execute_agent_turn`, `ExportWordService`.
- Produces a background execution service that is independent of request lifetime.

- [ ] **Step 1: Write successful state-transition test**

Inject/mocking boundaries so no real LLM runs:

```text
queued
-> manager claims job
-> fake execute_agent_turn returns AgentTurnResult
-> fake/real ExportWordService returns valid DOCX bytes
-> final file exists
-> DB status completed
-> turn_id/content_length/download filename saved
```

Where practical, use a real minimal `python-docx` payload and reopen it with `Document()` to prove artifact validity.

- [ ] **Step 2: Write failure test**

Make fake `execute_agent_turn` raise. Assert:

```text
status == failed
output_path is null/no final artifact
error_code is populated
error_message is safe/truncated
```

- [ ] **Step 3: Write atomic artifact test**

Ensure a `.tmp` artifact is not exposed as completed. The DB may only enter `completed` after final `os.replace` succeeds.

- [ ] **Step 4: Write single-worker queue behavior test**

Use synchronization primitives in tests:

1. first fake Agent blocks on an Event;
2. enqueue two jobs;
3. assert first becomes running;
4. assert second remains queued while first is blocked;
5. release first;
6. assert both eventually complete in order.

This proves the Job API bounds concurrent expensive Agent runs rather than converting every incoming POST into a thread.

- [ ] **Step 5: Implement manager**

The implementation must reuse the exact Agent/Word core:

```python
turn = execute_agent_turn(
    payload=payload,
    session_id=job.session_id,
    request_id=job.request_id,
)

data, download_filename = ExportWordService().build_docx_bytes(
    turn.output,
    filename=job.requested_filename or "agent_output.docx",
)
```

Do not call HTTP `/v1/report/word` from the worker.

- [ ] **Step 6: Run manager tests**

```bash
PYTHONPATH=. pytest -q tests/test_report_job_manager.py tests/test_turn_execution_service.py
```

- [ ] **Step 7: Commit**

```bash
git add sra_api/services/report_job_manager.py tests/test_report_job_manager.py
git commit -m "feat: run durable report jobs in background worker"
```

## Task 5: Add async Job API router

**Files:**
- Create: `sra_api/routers/report_jobs.py`
- Create: `tests/test_report_jobs_api.py`
- Modify only if useful for a shared payload contract: `sra_api/routers/export.py`

**Interfaces:**
- Produces `POST /v1/report/jobs`, `GET /v1/report/jobs/{job_id}`, `GET /v1/report/jobs/{job_id}/word`.

- [ ] **Step 1: Write create-job API test that proves the POST does not execute Agent inline**

Use a fake manager/store. Assert:

```text
HTTP 202
body status == queued
Location header points to status URL
job_id/status_url/word_url returned
```

Monkeypatch `execute_agent_turn` at any visible router boundary to raise if the create endpoint invokes it. The test must still pass.

- [ ] **Step 2: Write `stream=true` validation test**

Expect 422, matching synchronous Word semantics.

- [ ] **Step 3: Write status tests for all states**

At minimum: queued, running, completed, failed, interrupted, unknown 404.

- [ ] **Step 4: Write download tests**

Cover:

```text
unknown -> 404
queued/running -> 409
failed/interrupted -> 409
completed with artifact -> 200 valid DOCX + expected headers
completed but file missing -> 410
```

- [ ] **Step 5: Write idempotency API tests**

Cover:

```text
same key + same request -> same job id, no second enqueue
same key + changed prompt -> 409
same key + changed session -> 409
```

- [ ] **Step 6: Write active-queue-limit test**

When `queued + running >= REPORT_JOB_MAX_QUEUED`, create endpoint returns 429 and does not insert another job.

- [ ] **Step 7: Implement router with safe response models**

Status endpoint must not include `request_payload_json`.

- [ ] **Step 8: Run router tests**

```bash
PYTHONPATH=. pytest -q tests/test_report_jobs_api.py tests/test_report_word_api.py
```

- [ ] **Step 9: Commit**

```bash
git add sra_api/routers/report_jobs.py tests/test_report_jobs_api.py sra_api/routers/export.py
git commit -m "feat: add asynchronous Word report Job API"
```

## Task 6: Wire lifecycle and preserve synchronous API as a first-class path

**Files:**
- Modify: `sra_api/main.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Tests: `tests/test_report_jobs_api.py`, `tests/test_report_word_api.py`

**Interfaces:**
- Application startup/shutdown manages one shared Job manager.

- [ ] **Step 1: Add lifecycle test**

Use `TestClient(app)` context and a temporary Job DB/output dir configured before app startup or inject a test manager. Assert manager initializes and job routes are registered.

Tests must not create persistent `.api_jobs` files in the repository.

- [ ] **Step 2: Add synchronous independence regression test**

Prove `/v1/report/word` still calls direct `execute_agent_turn()` and produces the DOCX even if the async Job manager is disabled or unavailable.

This is a hard acceptance requirement: disabling Job API must not break the convenient synchronous POST workflow.

- [ ] **Step 3: Add restart recovery integration test**

Against a temporary SQLite DB:

1. create queued job A;
2. create job B and mark it running;
3. simulate service restart/new manager;
4. startup recovery marks B interrupted;
5. A remains queued and can be claimed/completed.

- [ ] **Step 4: Wire lifecycle**

Prefer a FastAPI lifespan context or the project's current lifecycle pattern. Do not start threads at module import time.

- [ ] **Step 5: Add environment documentation**

Add the variables from Section 4.1.

- [ ] **Step 6: Ignore runtime artifacts**

Ensure `.api_jobs/` is ignored from git.

- [ ] **Step 7: Run combined targeted suite**

```bash
PYTHONPATH=. pytest -q \
  tests/test_turn_execution_service.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_export_word_service.py \
  tests/test_report_job_store.py \
  tests/test_report_job_manager.py \
  tests/test_report_jobs_api.py
```

- [ ] **Step 8: Commit**

```bash
git add sra_api/main.py .env.example .gitignore tests
git commit -m "feat: wire report Job API lifecycle"
```

## Task 7: Write operator/developer documentation for both modes

**Files:**
- Create: `docs/report_word_automation.md`

**Interfaces:**
- Produces the human-maintainable reference for developers/operators.

- [ ] **Step 1: Document decision table**

Include at least:

| Scenario | Recommended API |
| --- | --- |
| Chrome F12 / one manual test | `POST /v1/report/word` |
| One short script and timeout is acceptable | synchronous Word POST |
| 10–30+ minute report | Job API |
| dozens/hundreds of scheduled reports | Job API |
| caller may disconnect/restart | Job API |
| immediate one-call DOCX convenience | synchronous Word POST |

- [ ] **Step 2: Document synchronous Chrome DevTools example**

Keep a working `fetch()` example that downloads the Blob automatically. Explicitly mention that this path holds the HTTP connection until Agent completion.

- [ ] **Step 3: Document Python synchronous example with explicit timeouts**

For example:

```python
response = requests.post(
    f"{base_url}/v1/report/word",
    json=payload,
    headers={"X-Session-Id": session_id},
    timeout=(10, 3600),
)
response.raise_for_status()
Path("report.docx").write_bytes(response.content)
```

Explain that Nginx/gateway timeouts must also be >= the report runtime.

- [ ] **Step 4: Document async Python polling example**

The example must:

1. create with `Idempotency-Key`;
2. save `job_id` locally;
3. poll every 15–30 seconds;
4. handle `failed` and `interrupted` explicitly;
5. download only after `completed`;
6. use short ordinary HTTP timeouts because the Agent runtime no longer happens inside create/status/download calls.

- [ ] **Step 5: Document batch scheduler pattern**

Recommend a persistent client-side table/CSV/DB containing at least:

```text
task_id
schedule_run_id
idempotency_key
job_id
status
output_filename
last_checked_at
```

This lets an external scheduler resume after its own restart without resubmitting every prompt.

- [ ] **Step 6: Document session guidance**

For independent daily reports, recommend an explicit unique session id per task/run, e.g.:

```text
gaza-daily-20260901
china-korea-fta-weekly-20260907
```

If the caller intentionally wants conversational continuation/reuse, it may reuse a session id. Warn that concurrently queueing multiple jobs against the same session is not guaranteed to preserve a deterministic conversational order in this initial version.

- [ ] **Step 7: Document limitations**

Must state:

- single SRA API process is the validated deployment model for this local SQLite worker version;
- server/process restart turns previously `running` jobs into `interrupted` rather than auto-retrying;
- queued jobs are durable and may resume;
- no cancellation of an already-running Agent turn;
- no automatic retry;
- no cross-host distributed queue;
- async worker concurrency defaults to 1;
- synchronous endpoint still needs long reverse-proxy/client timeouts.

- [ ] **Step 8: Commit**

```bash
git add docs/report_word_automation.md
git commit -m "docs: explain synchronous and async Word report automation"
```

## Task 8: Update `.codex` persistent project memory

**Files:**
- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/backlog.md`
- Modify: `.codex/memory.md`
- Modify `.codex/known_issues.md` if warranted

- [ ] **Step 1: API contract**

Record both modes explicitly and state that neither supersedes the other.

- [ ] **Step 2: Architecture**

Add data flow:

```text
Synchronous:
HTTP POST /v1/report/word
 -> execute_agent_turn
 -> ExportWordService
 -> HTTP DOCX

Asynchronous:
HTTP POST /v1/report/jobs
 -> SQLite queued record
 -> 202 job_id
 -> background worker
 -> execute_agent_turn
 -> ExportWordService
 -> atomic DOCX file
 -> SQLite completed metadata
 -> GET status / GET word
```

- [ ] **Step 3: Decisions**

Record:

- sync POST remains a first-class convenience path;
- Job API is the reliability/batch path;
- both share the Agent turn service;
- local SQLite + single-process worker is an intentional intermediate architecture;
- running jobs become interrupted after restart rather than auto-retry;
- optional idempotency is used to protect create-job retries.

- [ ] **Step 4: Backlog**

Keep future items separate:

```text
external Redis/Postgres queue
multi-process/multi-host workers
worker heartbeat/lease
cooperative cancellation
explicit retry endpoint/policy
priority scheduling
per-client rate limits
retention/cleanup policy if not implemented now
webhooks/callbacks
job listing/admin dashboard
```

Do not implement these merely because they are written in backlog.

- [ ] **Step 5: Memory**

Record actual files changed, exact test commands, actual pass/fail counts, and any environmental limitations.

- [ ] **Step 6: Commit**

```bash
git add .codex
git commit -m "docs: record dual-mode report Job API architecture"
```

## Task 9: Final verification

- [ ] **Step 1: Compile modified Python**

```bash
python -m compileall sra_api
```

- [ ] **Step 2: Run the full targeted Word/Job suite**

```bash
PYTHONPATH=. pytest -q \
  tests/test_turn_execution_service.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_export_word_service.py \
  tests/test_report_job_store.py \
  tests/test_report_job_manager.py \
  tests/test_report_jobs_api.py
```

- [ ] **Step 3: Run full test suite**

```bash
PYTHONPATH=. pytest tests -q --tb=short
```

Compare failures against `.codex/known_issues.md`. A new failure caused by this change blocks completion.

- [ ] **Step 4: Validate source diff**

```bash
git diff --check
```

- [ ] **Step 5: Manual synchronous API smoke test on the real API host**

Use the same Chrome DevTools or curl workflow already proven useful. Confirm a real DOCX downloads and opens.

- [ ] **Step 6: Manual asynchronous API smoke test on the real API host**

Submit one real long-running job:

```text
POST returns 202 quickly
-> observe queued/running
-> disconnect/close client console if desired
-> later GET status from a new client session
-> status becomes completed
-> GET /word downloads a valid DOCX
```

- [ ] **Step 7: Idempotency smoke test**

Submit the same create request twice with the same `Idempotency-Key`. Confirm it returns the same `job_id` and only one Agent execution occurs.

- [ ] **Step 8: Record exact real-world evidence in `.codex/memory.md`**

Do not claim the network-disconnect or 30-minute path is validated unless it was actually exercised on the deployed environment.

---

# 9. Acceptance Criteria

The feature is complete only if all of the following are true:

- [ ] Existing `POST /v1/report/word` still works and directly returns DOCX after Agent completion.
- [ ] Sync POST does not depend on Job API being enabled.
- [ ] Existing `GET /v1/export/word` still works.
- [ ] Existing `/v1/chat/completions` Word metadata still works.
- [ ] `POST /v1/report/jobs` returns `202` without waiting for the Agent execution.
- [ ] Job request is persisted before `202` is returned.
- [ ] Job can move `queued -> running -> completed` and produce a valid DOCX.
- [ ] A client can close/reconnect after create and retrieve status/result by `job_id` while the same server process remains alive.
- [ ] Queued jobs survive API process restart.
- [ ] Jobs that were running during restart are marked `interrupted`, not silently rerun.
- [ ] Failed jobs expose a safe failure status and do not return fake Word content.
- [ ] Word download before completion does not block for 30 minutes; it returns a clear 409.
- [ ] Completed Word download does not read `state.json`.
- [ ] Output path is server-controlled and cannot be changed by user filename.
- [ ] Artifact write is atomic.
- [ ] Optional `Idempotency-Key` prevents duplicate Agent execution for retried create requests.
- [ ] Same idempotency key with a different request returns 409.
- [ ] Worker concurrency is bounded; default is one expensive async Agent turn at a time.
- [ ] Queue capacity is bounded.
- [ ] Docs clearly tell users when to choose sync vs Job mode.
- [ ] Docs include Chrome/curl/Python examples and Nginx timeout guidance.
- [ ] `.codex` memory reflects the final contract and real test evidence.
- [ ] Full targeted suite passes.
- [ ] Full repo suite has no new failures attributable to this change.

---

# 10. Explicit Non-Goals for This PR

Do **not** implement these in this change:

- Redis/Celery/RQ/PostgreSQL queue backend.
- Multi-host worker farm.
- Uvicorn multi-process queue correctness.
- Job cancellation of a running Agent turn.
- Automatic retry of failed/interrupted jobs.
- Priority queue scheduling.
- User-facing Job management UI.
- Webhook/callback delivery.
- Email/SharePoint/NAS delivery.
- Distributed locks.
- Per-tenant authentication/rate limiting beyond existing integration boundary.
- Automatic report retention cleanup unless disk usage proves this is immediately required; otherwise place retention in backlog and document manual lifecycle expectations.

These belong to a later Phase 3 after the async contract is exercised with real 10–30+ minute reports.

---

# 11. Suggested Commit Sequence

Recommended reviewable commits:

```text
1. refactor: allow Agent turns outside HTTP requests
2. feat: persist report jobs in SQLite
3. feat: run durable report jobs in background worker
4. feat: add asynchronous Word report Job API
5. feat: wire report Job API lifecycle
6. docs: explain synchronous and async Word report automation
7. docs: record dual-mode report Job API architecture
```

Do not squash until tests are green and review is complete; the separation makes regressions easier to bisect.

---

# 12. How to Ask Codex

## Recommended prompt: implement the whole plan

```text
請依 `docs/superpowers/plans/2026-09-01-dual-mode-word-report-job-api-plan.md` 完整實作「同步 Word POST + 非同步 Job API 雙模式」功能。

開始前依 `AGENTS.md` 順序讀取 `.codex` 專案記憶，並先檢查目前程式碼是否與計劃的 baseline 一致；若文件與程式碼衝突，以目前程式碼為準，但不要自行擴大需求範圍。

這次最重要的架構原則：
1. 現有 `POST /v1/report/word` 必須完整保留，它是人工、Chrome F12、curl、單筆測試很好用的同步模式，不是要淘汰的舊 API。
2. 新增 `POST /v1/report/jobs`、`GET /v1/report/jobs/{job_id}`、`GET /v1/report/jobs/{job_id}/word`，給 10～30 分鐘以上與大量排程使用。
3. 同步與 Job 兩條路徑必須共用 `execute_agent_turn()` 與 `ExportWordService`，不得維護兩套 Agent 流程。
4. Job create POST 必須在任務持久化後快速回 202，不得在該 HTTP request 裡跑完整 Agent。
5. Job worker 必須直接用本輪 `AgentTurnResult.output` 產 Word，不得透過 `state.json` read-after-write，也不得從 worker 再 HTTP 呼叫 `/v1/report/word`。
6. 本版用 SQLite + 單一 API process 的 background worker 即可；不要引入 Redis、Celery、PostgreSQL、Airflow 等外部基礎設施。
7. 預設 Job worker concurrency 為 1；不要假設現有 session/memory state 已可安全多執行緒並行。
8. Running job 遇到 API process restart 後要標成 interrupted，不要自動重跑；queued job 可恢復排隊。
9. 支援可選 `Idempotency-Key`，避免 create response 遺失後 retry 造成同一份 30 分鐘報告重跑。
10. 採 TDD：先寫 failing tests，再做最小實作；每個 Task 做完跑該 Task 的 targeted tests。

實作範圍只限計劃內容。不要順便修改 Agent routing、ES、Query Refiner、Report Prompt、Word 格式或 Editor auth。

完成後請：
- 跑計劃指定的 targeted tests；
- 跑完整 `PYTHONPATH=. pytest tests -q --tb=short`；
- 跑 `python -m compileall sra_api` 與 `git diff --check`；
- 更新 `.codex/memory.md`、`.codex/api_contract.md`、`.codex/architecture.md`、`.codex/decisions.md`、`.codex/backlog.md`，有新限制時同步更新 `.codex/known_issues.md`；
- 提供實際測試結果與失敗數，不得把未執行的測試寫成通過；
- 最後整理：修改檔案、同步 API 使用方式、Job API 使用方式、環境變數、測試證據、已知限制、下一階段建議。
```

## Recommended prompt: ask Codex to review before implementation

Use this first if you want Codex to inspect the plan/code and point out conflicts before editing:

```text
請先不要修改程式碼。請依 `AGENTS.md` 讀取專案記憶，然後審查 `docs/superpowers/plans/2026-09-01-dual-mode-word-report-job-api-plan.md` 與目前 branch。

請確認：
- 現有 `POST /v1/report/word`、`execute_agent_turn()`、`ExportWordService` 與計劃 baseline 是否一致；
- SQLite Job store + 單 process worker 是否能在目前 `api.run_api` / Uvicorn 啟動方式安全落地；
- 新 Job API 是否會與現有 session/memory/state persistence 發生明顯競態；
- 計劃中的檔案、函式介面與測試位置是否符合目前 repo；
- 是否有任何會造成同步 Word POST 退化的修改風險。

只列出「必須在開工前修正的問題」和「可直接照計劃做的部分」，不要提出 Redis/Celery/PostgreSQL 等超出本次 scope 的重構。

如果沒有阻斷問題，最後明確回答「可依此計劃實作」，並列出你預計依序修改的檔案；此階段不要動 code。
```

## Recommended prompt: resume later

```text
請讀取 `AGENTS.md`、`.codex` 專案記憶，以及 `docs/superpowers/plans/2026-09-01-dual-mode-word-report-job-api-plan.md`，確認目前完成到哪個 Task，從第一個尚未完成且尚未驗證的 Task 繼續。不要重做已經有測試證據的 Task，也不要擴大到 Phase 3 分散式 Queue。
```

---

# 13. Operational Recommendation After This PR

Keep both APIs permanently:

```text
Developer / manual / single report
        |
        +--> POST /v1/report/word
             (simple, blocking, direct DOCX)

Scheduler / bulk / long-running report
        |
        +--> POST /v1/report/jobs
             -> 202 + job_id
             -> poll GET /v1/report/jobs/{id}
             -> GET /v1/report/jobs/{id}/word
```

The choice is not “old vs new”; it is “simple synchronous transport vs resilient asynchronous transport” over the same Agent/report core.
