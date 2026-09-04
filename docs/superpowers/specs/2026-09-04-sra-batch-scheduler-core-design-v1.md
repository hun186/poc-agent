# SRA Batch Scheduler Core — Design Specification v1

**Date:** 2026-09-04  
**Repository:** `poc-agent` (repository URL not available from ZIP snapshot)  
**Branch:** not available from ZIP snapshot  
**Commit / baseline:** `poc-agent_20260904-092533.zip` source snapshot; do not invent a Git commit  
**Depends on:** SRA Unified API Security Boundary Design v3 and Phase 0 repository/deployment acceptance  
**Supersedes:** none; this is the first Phase 1 design  
**Scope:** Phase 1 — Batch Scheduler Core

## 1. Purpose

Phase 0 established the security boundary and proved the real Service Key → Router → Elasticsearch → long-running Agent → signed Word chain. The repository also already contains two report execution surfaces:

- synchronous `POST /v1/report/word`;
- persisted/pollable `POST /v1/report/jobs`, `GET /v1/report/jobs/{job_id}`, and `GET /v1/report/jobs/{job_id}/word`.

Phase 1 builds the first automation client on top of those existing contracts. It MUST NOT reimplement Agent routing, Elasticsearch retrieval, report synthesis, DOCX rendering, or Report Job execution. It MUST consume the Report Job API as an external client using a dedicated Batch Scheduler service key.

The Phase 1 outcome is a resumable batch execution core that can ingest CSV, XLSX, or JSON task definitions, validate them into one canonical task model, submit due tasks to `/v1/report/jobs`, poll persisted remote state, download completed Word reports atomically, and persist local execution records across scheduler restarts.

## 2. Roadmap position

The accepted project roadmap is:

1. **Phase 0 — Security Foundation**: completed repository gate and real deployment E2E; only post-E2E credential hygiene/document cleanup may remain operationally.
2. **Phase 1 — Batch Scheduler Core**: this design.
3. **Phase 2 — Server Management Web UI**: dashboard/progress/retry/cancel/audit experience built on the scheduler core and existing authentication/RBAC.
4. **Phase 3 — Windows GUI**: login/import/submit/progress/download/resumable local client built on the same contracts.
5. **Phase 4 — Hardening / Operations**: concurrency/load, broader security matrix, rate limits, retention, backup/deployment, and scale-out decisions.

Existing historical references to “Phase 2 synchronous Word API” and “Phase 3 Report Job foundation” describe earlier API implementation increments; those APIs are already present and are dependencies, not work to repeat in this Phase 1 roadmap.

## 3. Architectural decision

### 3.1 Scheduler is a separate process/client

Create a new top-level package:

```text
batch_scheduler/
```

The Batch Scheduler runs separately from the FastAPI SRA server and talks to it only through the published HTTP API.

```text
CSV / XLSX / JSON
       |
       v
Batch Scheduler Core
  - input normalization
  - local SQLite state
  - due-task dispatcher
  - Report Job HTTP client
  - status reconciler
  - atomic DOCX downloader
       |
       | Bearer sra_sk_... with batch-only scopes
       v
SRA API :9002
  POST /v1/report/jobs
  GET  /v1/report/jobs/{id}
  GET  /v1/report/jobs/{id}/word
       |
       v
Existing Report Job Worker
       |
       v
Router -> Elasticsearch -> long Agent -> DOCX
```

Do not import or invoke `execute_agent_turn`, `ReportJobWorker`, Elasticsearch tools, or `ExportWordService` from the scheduler. The HTTP boundary is intentional and is part of the Phase 0 security architecture.

### 3.2 Dedicated Batch Scheduler credential

The scheduler MUST use a separate service key with exactly:

```text
report:job:create
report:job:read
report:job:download
```

It MUST NOT reuse the OpenWebUI key and does not need `model:*`, `report:sync`, `document:read`, `report:legacy-download`, or `report:job:admin`.

The raw key is supplied at runtime via environment variable and is never persisted in the scheduler database, input files, logs, execution records, or generated documentation.

Recommended environment variables:

```text
SRA_API_BASE=http://192.168.0.133:9002
SRA_BATCH_SERVICE_KEY=<runtime secret>
SRA_BATCH_DB_PATH=.batch_scheduler/scheduler.sqlite3
SRA_BATCH_OUTPUT_ROOT=.batch_scheduler/output
SRA_BATCH_POLL_SECONDS=2
SRA_BATCH_HTTP_CONNECT_TIMEOUT=10
SRA_BATCH_HTTP_READ_TIMEOUT=30
SRA_BATCH_MAX_RETRIES=3
```

Long Agent execution is asynchronous on the SRA server, so scheduler HTTP reads remain short. The scheduler MUST NOT use a 30–60 minute HTTP timeout for normal Report Job polling.

## 4. Phase 0 closure precondition

The current snapshot still contains an operator E2E harness with raw-looking acceptance credentials. Since the real Phase 0 E2E has now passed, Phase 1 implementation begins by removing raw credentials from tracked source and reading them from environment/ignored local configuration.

This source cleanup is not permission to fabricate or silently rotate deployed credentials. Actual key replacement/revocation is an operator action:

1. create replacement keys;
2. smoke-test replacements;
3. revoke old acceptance keys;
4. verify an old key receives `401` on the next protected request.

Project memory/backlog MUST distinguish source hygiene from operator-side credential rotation.

## 5. Canonical batch input model

### 5.1 Canonical task

Every input format normalizes to:

```python
@dataclass(frozen=True)
class BatchTaskSpec:
    task_id: str
    prompt: str
    filename: str | None
    session_id: str | None
    model: str
    scheduled_at: datetime | None
    metadata: dict[str, object]
```

Rules:

- `task_id` is required, non-empty, and unique within a batch.
- `prompt` is required and non-blank.
- `filename` is optional and is display/output metadata only.
- `session_id` is optional. When absent, the scheduler creates a stable task-specific value derived from `batch_id` + `task_id` so a restart does not create a new conversation identity.
- `model` defaults to `SRA-Structured Retrieval Agent`.
- `scheduled_at` is optional. When absent, the task is immediately due. When present, it MUST be an offset-aware ISO-8601 timestamp; naive timestamps are rejected.
- `metadata` is persisted bookkeeping only and MUST NOT become an unvalidated execution-options channel.
- Phase 1 does not expose Report Job `options`; the existing API currently accepts no option keys.

### 5.2 CSV

UTF-8 / UTF-8-SIG CSV with header names:

```text
task_id,prompt,filename,session_id,model,scheduled_at,metadata_json
```

Only `task_id` and `prompt` are required. `metadata_json`, when present, must decode to a JSON object.

### 5.3 XLSX

`.xlsx` only. Read the first worksheet with `openpyxl` using `data_only=True`. The first row is the same canonical header as CSV. Do not evaluate formulas and do not support legacy `.xls` in Phase 1.

### 5.4 JSON

Accept either a bare array of task objects or:

```json
{
  "batch_id": "daily-gaza-20260904",
  "tasks": [
    {
      "task_id": "gaza-001",
      "prompt": "...",
      "filename": "gaza-001.docx",
      "scheduled_at": "2026-09-04T18:00:00+08:00",
      "metadata": {"department": "analysis"}
    }
  ]
}
```

Unknown task fields are rejected rather than ignored.

## 6. Batch identity and import behavior

A batch has a stable `batch_id` supplied by the JSON envelope/CLI or generated once at import time.

The scheduler calculates and stores a SHA-256 fingerprint of the source bytes. Import rules:

- new `batch_id` -> insert batch and tasks;
- same `batch_id` + same source fingerprint -> idempotent no-op / return existing batch;
- same `batch_id` + different source fingerprint -> fail with an explicit conflict;
- duplicate `task_id` inside one batch -> validation failure before any remote submission.

Input validation is all-or-nothing. Invalid rows do not produce a partially imported runnable batch.

## 7. Local persistence

Use a separate SQLite database owned by the scheduler. Do not share the Report Job SQLite file.

### 7.1 `batch_runs`

Minimum fields:

```text
batch_id TEXT PRIMARY KEY
source_path TEXT
source_sha256 TEXT NOT NULL
output_root TEXT NOT NULL
status TEXT NOT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

### 7.2 `batch_tasks`

Minimum fields:

```text
batch_id TEXT NOT NULL
task_id TEXT NOT NULL
source_order INTEGER NOT NULL
prompt TEXT NOT NULL
filename TEXT
session_id TEXT NOT NULL
model TEXT NOT NULL
scheduled_at TEXT
metadata_json TEXT NOT NULL
idempotency_key TEXT NOT NULL
local_status TEXT NOT NULL
remote_job_id TEXT
remote_status TEXT
output_path TEXT
submit_attempts INTEGER NOT NULL
poll_attempts INTEGER NOT NULL
download_attempts INTEGER NOT NULL
last_http_status INTEGER
error_type TEXT
error_message TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
PRIMARY KEY(batch_id, task_id)
UNIQUE(idempotency_key)
```

Use `PRAGMA user_version` from the first scheduler schema so future Phase 2/3 code has an explicit migration boundary.

## 8. Task state machine

Canonical local states:

```text
pending
submitting
submitted
running
remote_failed
remote_interrupted
downloading
downloaded
download_failed
```

Flow:

```text
pending (not due yet or due)
  -> submitting
  -> submitted
  -> running
  -> downloading
  -> downloaded
```

Remote `failed` and `interrupted` are terminal in Phase 1. The scheduler does not automatically create a new report job for them.

### Crash safety at submission

Before `POST /v1/report/jobs`, persist `submitting` and the deterministic `idempotency_key`. If the scheduler crashes after the server accepted the request but before the response was persisted, restart/resume posts the exact same request with the same idempotency key. The existing owner-scoped Report Job idempotency contract resolves it to the original job rather than creating a duplicate.

## 9. Deterministic idempotency key

For every task derive:

```text
batch:<batch_id>:task:<task_id>:v1
```

If the resulting string exceeds the server header limit, use a stable SHA-256-derived representation while retaining `batch_id` / `task_id` in local records.

The key is generated by the scheduler, not read from arbitrary input columns.

## 10. HTTP client behavior

Create one focused SRA Report Job client.

### Submit

```http
POST /v1/report/jobs
Authorization: Bearer <batch service key>
Idempotency-Key: <stable task key>
Content-Type: application/json
```

Payload:

```json
{
  "prompt": "...",
  "filename": "...",
  "session_id": "...",
  "model": "SRA-Structured Retrieval Agent",
  "options": {},
  "metadata": {"batch_id": "...", "task_id": "..."}
}
```

### Poll

```http
GET /v1/report/jobs/{job_id}
```

Map remote states without inventing success.

### Download

Only after remote `completed`:

```http
GET /v1/report/jobs/{job_id}/word
```

Require:

```text
HTTP 200
Content-Type = application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

Write to a scheduler-owned temporary file, flush/fsync, validate `zipfile.is_zipfile`, then atomically rename inside the configured output root.

Never trust a remote `Content-Disposition` filename as a filesystem path.

## 11. Retry and failure policy

Phase 1 retries only failures that are safe under the existing idempotent API contract:

- connect timeout / connection error;
- read timeout;
- HTTP `429` when a future gateway emits it;
- HTTP `502`, `503`, `504`.

Use bounded retries with deterministic capped backoff. The default maximum is 3 per operation.

Do not blindly retry:

- `400` validation failures;
- `401` / `403` authentication or authorization failures;
- `409` idempotency conflict;
- `404` for a previously persisted remote job id;
- remote report status `failed` or `interrupted`.

Credential failures are process-level blockers. The scheduler exits non-zero and leaves local state resumable; it MUST NOT mark all tasks as report failures.

## 12. Resume/reconciliation

On startup or explicit `resume`:

- `pending`: dispatch only when due;
- `submitting`: safely repeat submit using the stable idempotency key;
- `submitted` / `running`: poll the known remote job;
- `downloading`: re-check remote status and restart atomic download;
- terminal states remain terminal.

A local process restart MUST NOT create a second remote report for the same task.

## 13. CLI contract

Phase 1 provides a CLI over the transport-neutral scheduler service:

```text
python -m batch_scheduler validate INPUT
python -m batch_scheduler import INPUT --batch-id ID --output-dir DIR
python -m batch_scheduler run BATCH_ID
python -m batch_scheduler resume BATCH_ID
python -m batch_scheduler status BATCH_ID
python -m batch_scheduler execute INPUT --batch-id ID --output-dir DIR
```

`execute` is a convenience command equivalent to import + run.

`status` has human-readable output and `--json` machine-readable output. Raw credentials are never displayed.

Exit codes:

```text
0 = requested operation completed successfully
2 = input/configuration validation error
3 = credential/auth boundary failure
4 = batch contains one or more terminal task failures
5 = local persistence/output failure
```

## 14. Output naming

The scheduler output directory is always explicitly configured or derived under `SRA_BATCH_OUTPUT_ROOT`.

For each task, the local basename is scheduler-controlled, e.g.:

```text
<safe-task-id>__<sanitized-requested-filename>
```

If no filename exists:

```text
<safe-task-id>.docx
```

All resolved output paths MUST remain under the batch output root. Existing files are not silently overwritten; a previously recorded matching completed artifact may be reused only after validation.

## 15. Execution records

The local database is the authoritative Phase 1 execution record. Persist:

- batch/task IDs;
- source fingerprint/order;
- local/remote status;
- remote job id;
- attempt counters;
- timestamps;
- output path;
- safe error type/message;
- last HTTP status.

Do not persist:

- service key;
- Authorization headers;
- service-key digest;
- signed URL credentials;
- arbitrary response bodies containing secrets.

## 16. Observability

Use Python logging with task context (`batch_id`, `task_id`, `remote_job_id`) and sanitized events. Phase 1 does not introduce metrics infrastructure or a web dashboard.

The CLI status view reads persisted records; it does not scrape logs to infer state.

## 17. Phase 1 non-goals

Do not implement in this phase:

- Server Management Web UI;
- Windows GUI;
- cron expressions or recurring schedules;
- Report Job cancel/retry server endpoints;
- automatic retry of a remote failed/interrupted report;
- webhook delivery;
- Redis/Celery/RQ/Kafka/Airflow;
- shared/distributed scheduler state;
- multiple SRA API workers / HA guarantees;
- per-user OpenWebUI identity propagation;
- arbitrary Report Job `options` passthrough;
- direct Agent/Elasticsearch imports from scheduler code.

## 18. Testing strategy

### Unit / repository tests

Cover:

- CSV/XLSX/JSON normalization equivalence;
- invalid/duplicate task rejection;
- timezone-aware scheduling validation;
- import idempotency and source conflict;
- SQLite schema/version and restart recovery;
- deterministic idempotency keys;
- submit/poll/download HTTP contract;
- auth failure fail-fast behavior;
- retryable vs non-retryable status handling;
- crash-after-submit recovery using the same idempotency key;
- atomic DOCX validation/publication;
- path traversal/collision prevention;
- no credential persistence/logging;
- CLI exit codes and JSON status.

Mocks/fakes are allowed for repository regression of the remote API seam, but may not be used as deployment acceptance evidence.

### Real Phase 1 deployment acceptance

From the operator network with real SRA and Elasticsearch:

1. create a dedicated Batch Scheduler key with exactly create/read/download scopes;
2. run a two-task batch from at least one tabular format and one JSON format;
3. confirm both tasks are submitted through `/v1/report/jobs`;
4. confirm remote jobs transition through real states;
5. confirm Router/Elasticsearch/long Agent execution through resulting report evidence;
6. confirm both Word files are downloaded and valid DOCX containers;
7. stop/restart the scheduler during one run and prove resume does not create a duplicate remote job;
8. revoke the batch key after creating a replacement and confirm the old key gets `401`.

Repository tests alone cannot declare Phase 1 deployment acceptance PASS.

## 19. Acceptance criteria

Phase 1 is complete only when:

- all three input formats work against one canonical model;
- local state survives scheduler restart;
- duplicate remote reports are prevented by stable owner-scoped idempotency;
- long tasks are handled through the asynchronous Report Job API, not long client HTTP waits;
- completed DOCX downloads are validated and atomically published;
- errors are explicit and resumable rather than fake-success;
- scheduler credentials are least-privilege and never persisted;
- repository tests pass;
- real SRA + Elasticsearch + long Agent batch E2E passes.
