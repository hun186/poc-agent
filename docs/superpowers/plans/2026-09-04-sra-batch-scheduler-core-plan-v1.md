# SRA Batch Scheduler Core — Phase 1 Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, resumable CSV/XLSX/JSON Batch Scheduler that consumes the existing scoped Report Job API, polls real job state, atomically downloads completed DOCX files, and persists execution records without duplicating Agent/Elasticsearch/report logic.

**Architecture:** Add a new `batch_scheduler/` client package with canonical input normalization, its own versioned SQLite state, a narrow HTTP client for `/v1/report/jobs`, a restart-safe scheduler service, and a CLI. The scheduler is a separate process and uses a dedicated least-privilege service key; it never imports SRA Agent, Elasticsearch, ReportJobWorker, or DOCX rendering internals.

**Tech Stack:** Python 3, stdlib `csv/json/sqlite3/pathlib/datetime/zipfile`, `requests`, `openpyxl`, existing pytest stack.

**Spec:** `docs/superpowers/specs/2026-09-04-sra-batch-scheduler-core-design-v1.md`

**Baseline:** `poc-agent_20260904-092533.zip` source snapshot. Repository URL, branch, and commit are not available from the ZIP and MUST be captured by Codex from the actual repository before editing.

**Supersedes:** none; first Phase 1 plan. It does not supersede Phase 0 Design v3 / Plan v6.1.

## Global Constraints

- Actual repository source always overrides stale paths in this plan; record any conflict and make only the minimum necessary adjustment.
- Do not redesign Phase 0 security, Report Job API, Router, Agent, Elasticsearch retrieval, or Word rendering unless a blocking incompatibility is proven.
- Scheduler must use the HTTP Report Job contract only; no direct Agent/ES/worker imports.
- Batch key scopes are exactly `report:job:create`, `report:job:read`, `report:job:download`.
- Do not persist or log raw service keys, Authorization headers, credential digests, or signed capability secrets.
- Preserve path confinement, validation, atomic file publication, transaction/error handling, and fail-closed security behavior.
- Phase 1 does not add Server Dashboard, Windows GUI, recurrence/cron, cancel/retry server APIs, webhooks, or distributed queue/storage.
- TDD for production behavior changes: write/observe failing regression first, implement minimum code, rerun affected tests, then full suite.

---

## Planned file structure

```text
batch_scheduler/
  __init__.py
  __main__.py
  cli.py
  config.py
  models.py
  input_loader.py
  store.py
  sra_client.py
  service.py
  output.py

tests/
  test_batch_scheduler_input.py
  test_batch_scheduler_store.py
  test_batch_scheduler_client.py
  test_batch_scheduler_service.py
  test_batch_scheduler_cli.py
  test_batch_scheduler_security.py

docs/operations/
  batch-scheduler.md
```

Existing files expected to be modified only where necessary:

```text
.env.example
.gitignore
.codex/memory.md
.codex/architecture.md
.codex/api_contract.md
.codex/known_issues.md
.codex/decisions.md
.codex/backlog.md
tests_code/test_phase0_api_routing_evidence.py
```

Do not create SRA server batch routes in Phase 1 unless the actual repository proves the published Report Job API is insufficient; if that occurs, stop and report the blocking contract gap before expanding scope.

---

### Task 0: Close Phase 0 source-secret hygiene and establish actual baseline

**Files:**
- Modify: `tests_code/test_phase0_api_routing_evidence.py`
- Modify: `.env.example`
- Modify: `.gitignore` only if the actual ignore rules do not already protect the chosen local env file
- Modify: `.codex/memory.md`
- Modify: `.codex/backlog.md`
- Modify: `.codex/known_issues.md` if stale Phase 0 acceptance statements remain

**Interfaces:**
- Consumes: existing Phase 0 operator E2E harness and Service Key CLI.
- Produces: no raw credentials in tracked source; runtime-only smoke credentials and an accurate Phase 0 closure record.

- [ ] **Step 1: Record repository baseline before editing**

Run:

```bash
pwd
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
```

Record repository, branch, baseline commit, and working-tree status in the final report. Do not invent a remote URL when none exists.

- [ ] **Step 2: Write a failing source-hygiene regression**

Create or extend `tests/test_batch_scheduler_security.py` so it scans tracked first-party source/config/docs intended for commit and fails if `tests_code/test_phase0_api_routing_evidence.py` contains a real-looking `sra_sk_...` literal.

The test must not print the matched secret. It should report only file path and a generic failure.

- [ ] **Step 3: Verify RED**

Run the exact new test and confirm it fails because the current harness contains raw-looking acceptance credentials.

- [ ] **Step 4: Convert the operator harness to environment-backed credentials**

Use explicit names:

```python
OPENWEBUI_KEY = os.environ["SRA_SMOKE_OPENWEBUI_KEY"]
READ_ONLY_KEY = os.environ["SRA_SMOKE_READONLY_KEY"]
REPORT_KEY = os.environ["SRA_SMOKE_REPORT_KEY"]
```

Do not provide fallback literals.

Document placeholder variable names in `.env.example` without real values. Do not claim operator-side revoke/rotation occurred unless Codex actually executed and verified it against the live deployment.

- [ ] **Step 5: Verify GREEN and scan repository**

Run the source-hygiene test plus a focused raw-key scan. The scan output must not echo raw matched credentials.

- [ ] **Step 6: Update Phase 0 memory/backlog truthfully**

Record that real Router → Elasticsearch → long Agent → Word E2E passed based on operator evidence, source harness secrets were removed from tracked code in this task, and live key rotation/revocation remains an operator action unless independently verified.

- [ ] **Step 7: Commit**

Suggested commit:

```bash
git add tests_code/test_phase0_api_routing_evidence.py tests/test_batch_scheduler_security.py .env.example .gitignore .codex

git commit -m "chore: close phase0 credential source hygiene"
```

---

### Task 1: Add Phase 1 configuration and canonical models

**Files:**
- Create: `batch_scheduler/__init__.py`
- Create: `batch_scheduler/config.py`
- Create: `batch_scheduler/models.py`
- Test: `tests/test_batch_scheduler_input.py`
- Test: `tests/test_batch_scheduler_security.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `BatchSchedulerConfig`, `BatchTaskSpec`, canonical validation helpers.
- Consumes: no SRA internal runtime objects.

- [ ] **Step 1: Write failing config/model tests**

Tests must prove:

```text
SRA_API_BASE is required or has an explicitly documented default
SRA_BATCH_SERVICE_KEY is required for execution but never represented in repr/log output
poll/connect/read/retry numeric settings reject invalid values
task_id and prompt reject blank values
scheduled_at rejects naive timestamps and accepts offset-aware ISO-8601
unknown task fields are rejected by format normalization
```

- [ ] **Step 2: Verify RED**

Run `pytest -q tests/test_batch_scheduler_input.py tests/test_batch_scheduler_security.py --tb=short` and confirm failure due to missing package/models.

- [ ] **Step 3: Implement minimal config/model layer**

Use immutable dataclasses where practical. Example public shapes:

```python
@dataclass(frozen=True)
class BatchSchedulerConfig:
    api_base: str
    service_key: str
    db_path: Path
    output_root: Path
    poll_seconds: float = 2.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    max_retries: int = 3

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

Normalize API base by stripping the trailing slash. Never expose the service key via custom `repr`, status output, or exception text.

- [ ] **Step 4: Verify GREEN**

Run the affected tests.

- [ ] **Step 5: Commit**

Suggested commit:

```bash
git add batch_scheduler .env.example tests/test_batch_scheduler_input.py tests/test_batch_scheduler_security.py
git commit -m "feat: add batch scheduler config and task model"
```

---

### Task 2: Implement CSV/XLSX/JSON input normalization

**Files:**
- Create: `batch_scheduler/input_loader.py`
- Test: `tests/test_batch_scheduler_input.py`

**Interfaces:**
- Consumes: `BatchTaskSpec`.
- Produces: `LoadedBatch(batch_id_hint, source_sha256, tasks)` or equivalent immutable result.

- [ ] **Step 1: Add failing equivalence and validation tests**

Create temporary CSV, XLSX, and JSON inputs containing the same two tasks. Assert all formats normalize to equivalent canonical tasks.

Also test:

```text
duplicate task_id -> reject whole import
missing task_id -> reject
blank prompt -> reject
metadata_json non-object -> reject
unknown CSV/XLSX headers -> reject
unknown JSON task fields -> reject
naive scheduled_at -> reject
invalid JSON -> clear validation error
.xls -> unsupported
```

- [ ] **Step 2: Verify RED**

Run the input test module and confirm failures are caused by missing loader behavior.

- [ ] **Step 3: Implement loaders**

Rules:

```python
CSV: encoding="utf-8-sig", csv.DictReader
XLSX: openpyxl.load_workbook(..., read_only=True, data_only=True)
JSON: list or {"batch_id": ..., "tasks": [...]}
```

Compute SHA-256 from original source bytes before parsing.

- [ ] **Step 4: Verify GREEN**

Run the complete input test module.

- [ ] **Step 5: Commit**

```bash
git add batch_scheduler/input_loader.py tests/test_batch_scheduler_input.py
git commit -m "feat: normalize batch scheduler input formats"
```

---

### Task 3: Add versioned local SQLite persistence

**Files:**
- Create: `batch_scheduler/store.py`
- Test: `tests/test_batch_scheduler_store.py`

**Interfaces:**
- Produces: `BatchSchedulerStore` with initialize/import/get/list/update methods.
- Consumes: canonical loaded batch/tasks.

- [ ] **Step 1: Write failing schema/import tests**

Test fresh DB creation with `PRAGMA user_version=1` and the Design v1 `batch_runs` / `batch_tasks` constraints.

Test:

```text
same batch_id + same source hash -> idempotent existing batch
same batch_id + different hash -> conflict
duplicate task_id -> no partial rows
stable session id generated once when absent
stable idempotency key generated once and persisted
restart/reopen preserves all state
```

- [ ] **Step 2: Verify RED**

Run the store tests.

- [ ] **Step 3: Implement store transactionally**

Use parameterized SQL only. Use one connection per operation and a busy timeout. Import the complete batch in one transaction so validation/persistence is all-or-nothing.

Expose narrow methods such as:

```python
initialize()
import_batch(...)
get_batch(batch_id)
list_tasks(batch_id)
list_due_tasks(batch_id, now)
mark_submitting(...)
record_submission(...)
record_remote_status(...)
mark_downloading(...)
mark_downloaded(...)
mark_error(...)
```

Avoid a generic arbitrary SQL interface.

- [ ] **Step 4: Verify GREEN and reopen behavior**

Run store tests twice against fresh temp databases.

- [ ] **Step 5: Commit**

```bash
git add batch_scheduler/store.py tests/test_batch_scheduler_store.py
git commit -m "feat: persist resumable batch scheduler state"
```

---

### Task 4: Implement the narrow Report Job HTTP client

**Files:**
- Create: `batch_scheduler/sra_client.py`
- Test: `tests/test_batch_scheduler_client.py`
- Test: `tests/test_batch_scheduler_security.py`

**Interfaces:**
- Produces: `SRAReportJobClient.submit()`, `.status()`, `.download()`.
- Consumes: `BatchSchedulerConfig` and canonical task request data.

- [ ] **Step 1: Write failing HTTP-contract tests**

Use an injectable `requests.Session`/transport seam to test exact request method/path/header/body without a live server.

Assert:

```text
submit sends Authorization bearer and deterministic Idempotency-Key
submit payload uses options={} and metadata batch_id/task_id
status uses GET known job id
download only accepts DOCX MIME + 200
401/403 raise a credential-boundary exception
409 submit conflict is non-retryable
429/502/503/504 and transport timeouts are retryable within max_retries
400 and 404 are non-retryable
exception/log text does not contain service key
```

- [ ] **Step 2: Verify RED**

Run client/security tests.

- [ ] **Step 3: Implement minimal client**

Use `requests.Session`. Timeouts must be `(connect_timeout, read_timeout)` and remain short because the remote job is asynchronous.

Provide typed domain errors such as:

```python
class BatchCredentialError(RuntimeError): ...
class BatchRemoteConflict(RuntimeError): ...
class BatchRemoteUnavailable(RuntimeError): ...
```

Error messages include safe HTTP status and endpoint class, not raw response bodies/headers containing credentials.

- [ ] **Step 4: Verify GREEN**

Run affected tests.

- [ ] **Step 5: Commit**

```bash
git add batch_scheduler/sra_client.py tests/test_batch_scheduler_client.py tests/test_batch_scheduler_security.py
git commit -m "feat: add scoped report job api client"
```

---

### Task 5: Add atomic validated DOCX publication

**Files:**
- Create: `batch_scheduler/output.py`
- Test: `tests/test_batch_scheduler_service.py`
- Test: `tests/test_batch_scheduler_security.py`

**Interfaces:**
- Produces: safe output path derivation and atomic publication helper.
- Consumes: task id, requested filename, output root, downloaded bytes/stream.

- [ ] **Step 1: Write failing path/file tests**

Cover:

```text
../ and absolute-path filename attempts cannot escape output root
Windows separators are sanitized
same task filename cannot silently overwrite another task
invalid/non-ZIP DOCX is rejected and temp file removed
valid DOCX is fsync'd and atomically renamed
recorded final path remains under output root
```

- [ ] **Step 2: Verify RED**

Run the focused tests.

- [ ] **Step 3: Implement helper**

Never use remote `Content-Disposition` as the filesystem path. Use scheduler-controlled basenames and `Path.resolve()/relative_to()` confinement.

- [ ] **Step 4: Verify GREEN**

Run tests.

- [ ] **Step 5: Commit**

```bash
git add batch_scheduler/output.py tests/test_batch_scheduler_service.py tests/test_batch_scheduler_security.py
git commit -m "feat: publish batch report artifacts atomically"
```

---

### Task 6: Implement scheduler state machine and restart reconciliation

**Files:**
- Create: `batch_scheduler/service.py`
- Test: `tests/test_batch_scheduler_service.py`

**Interfaces:**
- Consumes: store, SRA client, output helper, clock/sleep seams.
- Produces: import/run/resume/status orchestration with deterministic state transitions.

- [ ] **Step 1: Write failing state-machine tests**

Test at minimum:

```text
future scheduled task stays pending
immediately due task submits
pending -> submitting is persisted before HTTP submit
successful submit persists remote_job_id
submitted/running poll until completed
completed triggers atomic download then downloaded
remote failed/interrupted become terminal without automatic new submit
credential failure aborts process-level run without marking every task report_failed
```

- [ ] **Step 2: Add crash-window regression before implementation**

Simulate:

```text
persist submitting
server accepts create
client crashes before record_submission
restart/resume
repeat same POST with same Idempotency-Key
server/client seam returns same remote job id
only one logical remote job is recorded
```

This is a blocking Phase 1 correctness test.

- [ ] **Step 3: Verify RED**

Run service tests.

- [ ] **Step 4: Implement minimal service**

Keep orchestration transport-neutral enough for Phase 2/3 consumers. CLI printing must not be embedded in service methods.

Use an injectable clock for due-time tests; production defaults to timezone-aware UTC now.

- [ ] **Step 5: Verify GREEN**

Run service tests including restart/crash window.

- [ ] **Step 6: Commit**

```bash
git add batch_scheduler/service.py tests/test_batch_scheduler_service.py
git commit -m "feat: orchestrate resumable batch report execution"
```

---

### Task 7: Add CLI surface

**Files:**
- Create: `batch_scheduler/cli.py`
- Create: `batch_scheduler/__main__.py`
- Test: `tests/test_batch_scheduler_cli.py`

**Interfaces:**
- Consumes: config, loader, store, service.
- Produces: validate/import/run/resume/status/execute commands and documented exit codes.

- [ ] **Step 1: Write failing CLI tests**

Test command parsing and exit codes without running real Agent work.

Required commands:

```text
validate INPUT
import INPUT --batch-id ID --output-dir DIR
run BATCH_ID
resume BATCH_ID
status BATCH_ID [--json]
execute INPUT --batch-id ID --output-dir DIR
```

Assert JSON status contains no service key and is stable enough for future GUI/dashboard adapters.

- [ ] **Step 2: Verify RED**

Run CLI tests.

- [ ] **Step 3: Implement CLI**

CLI must delegate to service/store; no duplicate scheduler logic in argument handlers.

- [ ] **Step 4: Verify GREEN**

Run CLI tests and at least one temp-file `validate` command with CSV/XLSX/JSON fixtures.

- [ ] **Step 5: Commit**

```bash
git add batch_scheduler/cli.py batch_scheduler/__main__.py tests/test_batch_scheduler_cli.py
git commit -m "feat: add batch scheduler cli"
```

---

### Task 8: Documentation and project memory

**Files:**
- Create: `docs/operations/batch-scheduler.md`
- Modify: `README.md` if it has an automation/API section suitable for one concise link
- Modify: `.env.example`
- Modify: `.codex/memory.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/api_contract.md`
- Modify: `.codex/known_issues.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/backlog.md`

**Interfaces:**
- Produces: operator setup/usage contract and durable project context.

- [ ] **Step 1: Document dedicated key creation**

Use the existing CLI contract, e.g.:

```bash
python -m api.security.cli create-service-key \
  --name batch-scheduler-production \
  --scope report:job:create \
  --scope report:job:read \
  --scope report:job:download
```

Document that the raw returned key is copied to runtime secret configuration only and must not be committed.

- [ ] **Step 2: Document input examples and CLI workflow**

Include one CSV, one JSON, and one XLSX-header example plus `validate`, `execute`, `status`, and `resume` usage.

- [ ] **Step 3: Document operational limits**

State explicitly:

```text
SRA Report Job backend is currently single-machine / single API process
remote failed/interrupted jobs are not auto-resubmitted in Phase 1
no cron/recurrence
no cancel/retry endpoint
no web dashboard/Windows GUI yet
scheduler DB and output directory require backup/retention policy
```

- [ ] **Step 4: Update `.codex` memory without stale claims**

Record actual baseline/result commit and exact fresh test counts. Archive/compact only if AGENTS.md thresholds are triggered.

- [ ] **Step 5: Commit**

```bash
git add docs/operations/batch-scheduler.md README.md .env.example .codex
git commit -m "docs: document phase1 batch scheduler operations"
```

---

### Task 9: Repository verification gate

**Files:**
- No production changes unless verification reveals a defect.

- [ ] **Step 1: Install/confirm dependencies per AGENTS.md**

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Package-index proxy warnings may be recorded, but already-installed requirements are acceptable only if the install command succeeds or the limitation is explicitly documented.

- [ ] **Step 2: Run Phase 1 targeted tests**

```bash
PYTHONPATH=. pytest -q \
  tests/test_batch_scheduler_input.py \
  tests/test_batch_scheduler_store.py \
  tests/test_batch_scheduler_client.py \
  tests/test_batch_scheduler_service.py \
  tests/test_batch_scheduler_cli.py \
  tests/test_batch_scheduler_security.py \
  --tb=short
```

- [ ] **Step 3: Run affected existing Report Job/security tests**

At minimum:

```bash
PYTHONPATH=. pytest -q \
  tests/test_report_jobs_api.py \
  tests/test_report_job_store.py \
  tests/test_report_job_worker.py \
  tests/test_job_authorization.py \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_phase0_security_acceptance.py \
  --tb=short
```

- [ ] **Step 4: Run full repository gate**

```bash
PYTHONPATH=. pytest tests -q --tb=short
python -m compileall -q batch_scheduler sra_api api tests
git diff --check
```

- [ ] **Step 5: Run security/static scans**

Verify no newly tracked runtime credential/cache files and no real-looking raw Service Key literals were introduced. Do not print secret contents in logs.

- [ ] **Step 6: Record exact evidence**

Final report must include exact passed/failed/error/warning counts and every command that could not be executed.

---

### Task 10: Real Phase 1 deployment acceptance

**Files:**
- May create operator-only ignored fixtures/scripts; do not commit secrets.

**Interfaces:**
- Consumes: real SRA API, real Elasticsearch, real Batch Scheduler key.
- Produces: deployment acceptance evidence; does not replace repository tests.

- [ ] **Step 1: Preflight live SRA**

From the operator network, verify `/healthz` and a dedicated Batch Scheduler key with exactly create/read/download scopes.

- [ ] **Step 2: Prepare real two-task fixtures**

Use at least:

```text
one CSV or XLSX batch with a real report prompt
one JSON batch with a second real report prompt
```

Do not use fake/mocked Agent or Elasticsearch responses.

- [ ] **Step 3: Execute and capture remote evidence**

Run scheduler execution and capture:

```text
batch_id/task_id
remote job_id
remote state transitions
final downloaded path
```

Confirm the resulting report content/citations demonstrate real SRA Report/analysis routing and Elasticsearch retrieval.

- [ ] **Step 4: Restart/resume test**

Stop the scheduler after a task has reached at least `submitting`/`submitted`/`running`, restart with `resume`, and prove the persisted idempotency key maps back to the same remote `job_id` rather than creating a second job.

- [ ] **Step 5: Validate DOCX files**

Verify both downloaded artifacts are non-empty ZIP/DOCX containers and open successfully in a DOCX reader if available.

- [ ] **Step 6: Credential lifecycle smoke**

After the real batch E2E passes, create a replacement batch key, verify it, revoke the old batch key, and confirm the old key receives `401` on a protected request. Never print raw keys into execution reports.

- [ ] **Step 7: Deployment acceptance declaration**

Only if every mandatory live step succeeds may the final report state:

```text
Phase 1 Batch Scheduler repository gate passed and real SRA/Elasticsearch deployment acceptance passed.
```

Otherwise report repository PASS separately from deployment acceptance PENDING/NOT EXECUTED.
