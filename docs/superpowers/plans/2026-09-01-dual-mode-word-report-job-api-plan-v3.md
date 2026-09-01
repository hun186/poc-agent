# Dual-Mode Word Report API Implementation Plan (Final After Review)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the working synchronous Word-report API while adding a single-machine asynchronous Job API for long-running reports, with durable job metadata, polling/download endpoints, idempotency, explicit restart semantics, documentation, and SVG architecture diagrams.

**Architecture:** Both synchronous and asynchronous report generation must reuse the same Python execution core and Word renderer. The sync endpoint continues to block until DOCX is ready; the async API persists a job in SQLite, returns `202 + job_id`, and a single lifespan-managed worker claims queued jobs atomically and writes final DOCX files under a configured reports root.

**Tech Stack:** FastAPI, Python standard library `sqlite3`, existing SRA turn execution service, existing `ExportWordService`, pytest, plain-text Markdown/SVG documentation.

**Spec:** This plan incorporates the Codex review of the previous dual-mode Job API plan and supersedes the earlier draft.

## Global Constraints

- Runtime source of truth is `sra_api/`; do not implement feature logic in compatibility shims.
- Existing `POST /v1/report/word`, `/v1/chat/completions`, and `/v1/export/word` contracts must remain compatible.
- Do not add Redis, Celery, RQ, PostgreSQL, Airflow, RabbitMQ, Kafka, or a distributed queue in this phase.
- Async worker concurrency defaults to `1`.
- Async worker must call shared Python services directly; it must not call the sync endpoint over HTTP.
- Async Word generation must use the current `AgentTurnResult.output`; it must not depend on `state.json` read-after-write.
- Job state is single-machine persisted metadata, not high availability, exactly-once execution, or crash-resumable execution.
- `running` jobs discovered at API startup are marked `interrupted` and are not auto-retried.
- Job SQLite path and reports root must be configurable by environment variables.
- The formal maintained architecture SVG lives under `docs/architecture/`; plan-directory SVG assets must not become a second maintained source.

---

## 1. Final API Contract

### 1.1 Existing synchronous API — keep unchanged

#### `POST /v1/report/word`

- Input remains the existing `ChatPayload` contract (`model`, `messages`, `stream`, etc.).
- Existing behavior remains synchronous.
- Streaming remains rejected if it is currently unsupported.
- Success returns DOCX bytes plus the existing tracking headers.
- No conversion to Job API is allowed internally.

Use cases:
- Chrome F12 manual run
- curl smoke test
- one-off automation
- short/medium reports when waiting on one HTTP connection is acceptable

### 1.2 New async create API

#### `POST /v1/report/jobs`

Use a dedicated Job request model instead of reusing `ChatPayload`.

Canonical request body:

```json
{
  "prompt": "請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊。",
  "filename": "gaza_report_2026-09-01.docx",
  "session_id": "batch-gaza-20260901",
  "model": "SRA-Structured Retrieval Agent",
  "options": {},
  "metadata": {
    "task_id": "gaza-daily-001",
    "department": "political-diplomatic"
  }
}
```

Contract rules:
- `prompt`: required non-empty string.
- `filename`: optional display/download filename; must be sanitized and never used as an arbitrary filesystem path.
- `session_id`: optional; if omitted, service generates one using existing session rules.
- `model`: optional; default must be explicitly defined in code/docs and mapped to the same model normally used by the synchronous report endpoint.
- `options`: optional object for execution options that materially affect report generation; only supported keys should be accepted.
- `metadata`: optional JSON object persisted for caller bookkeeping; it must not silently alter execution unless documented.
- `Idempotency-Key`: optional HTTP header.

Service-boundary conversion:
- Convert `prompt` to a single user message before invoking shared turn execution.
- Pass `session_id` directly as a service parameter.
- Do not fabricate a FastAPI `Request` for the worker.

Success:
- `202 Accepted`

```json
{
  "job_id": "rpt_20260901_000123",
  "status": "queued",
  "status_url": "/v1/report/jobs/rpt_20260901_000123",
  "download_url": "/v1/report/jobs/rpt_20260901_000123/word"
}
```

### 1.3 Get Job Status

#### `GET /v1/report/jobs/{job_id}`

Supported states:
- `queued`
- `running`
- `completed`
- `failed`
- `interrupted`

Completed response must include the download URL.
Failed/interrupted responses may include sanitized operational error metadata.

### 1.4 Download Job Word

#### `GET /v1/report/jobs/{job_id}/word`

Fixed HTTP semantics:
- Job not found: `404`
- Job exists but status is not `completed`: `409`
- Job says `completed` but the expected final DOCX is missing, invalid, or unreadable: `500` with structured operational error
- Success: `200` DOCX bytes

Security rule:
- Resolve the physical file only from `REPORT_JOBS_REPORTS_ROOT` + system-generated `job_id`/trusted stored basename.
- Never join request-supplied filename or arbitrary SQLite path directly to the filesystem.

---

## 2. Transport-Neutral Turn Execution

### Task 1: Remove mandatory FastAPI transport coupling

**Files:**
- Modify: `sra_api/services/turn_execution.py`
- Test: `tests/test_turn_execution_service.py`

**Interfaces:**
- Produce a service call that can be used by both HTTP handlers and background worker without constructing a fake `Request`.

Preferred shape:

```python
def execute_agent_turn(
    *,
    payload,
    request: Request | None = None,
    session_id: str | None = None,
    ...,
) -> AgentTurnResult:
    ...
```

Rules:
- Explicit `session_id` wins when provided.
- HTTP wrapper may continue deriving session ID from request headers when explicit session ID is absent.
- Worker supplies `session_id` directly.
- Do not duplicate `answer_with_routing()`, history, memory, reuse, or snapshot logic.

Tests:
- existing HTTP-path behavior remains unchanged
- explicit `session_id` works when `request=None`
- worker-style invocation does not require FastAPI request construction

---

## 3. SQLite Job Store

### Task 2: Add persistent Job Store with atomic transaction semantics

**Files:**
- Create: `sra_api/services/report_job_store.py`
- Test: `tests/test_report_job_store.py`

Environment variables:
- `REPORT_JOBS_DB_PATH` (default: `.api_jobs/jobs.sqlite3`)
- `REPORT_JOBS_REPORTS_ROOT` (default: `.api_jobs/reports`)
- `REPORT_JOBS_SQLITE_BUSY_TIMEOUT_MS` (document a safe default, e.g. 5000)

SQLite rules:
- use a separate connection per thread/operation; do not share one request connection across threads
- configure busy timeout
- use transactions for create/idempotency and claim operations
- initialize schema safely on startup

Suggested columns:
- `job_id TEXT PRIMARY KEY`
- `status TEXT NOT NULL`
- `prompt TEXT NOT NULL`
- `filename TEXT`
- `session_id TEXT`
- `model TEXT`
- `options_json TEXT`
- `metadata_json TEXT`
- `idempotency_key TEXT UNIQUE`
- `request_hash TEXT`
- `turn_id TEXT`
- `docx_basename TEXT`
- `error_type TEXT`
- `error_message TEXT`
- timestamps (`created_at`, `started_at`, `finished_at`, `updated_at`)

Do not trust a stored arbitrary absolute path for download routing.

### Atomic job claim

Implement one transaction that changes exactly one `queued` job to `running`.

Acceptance test:
- two competing claim attempts against the same queued job result in only one successful claim.

### Startup recovery

Within a transaction at application startup:
- `running -> interrupted`
- `queued` stays `queued`

No automatic retry of `interrupted` jobs.

---

## 4. Idempotency

### Task 3: Make Job creation retry-safe at database level

**Files:**
- Modify/Create: `sra_api/services/report_job_store.py`
- Create/Modify: `sra_api/services/report_job_service.py`
- Test: `tests/test_report_job_store.py`, `tests/test_report_jobs_api.py`

Normalize and hash all execution-relevant create fields:
- `prompt`
- sanitized/logical `filename`
- `session_id`
- `model`
- supported `options`
- `metadata` (because it is part of the requested persisted resource and review explicitly requires it)

Rules:
- same `Idempotency-Key` + same normalized hash => return the existing job
- same key + different hash => `409 Conflict`
- failed/interrupted/completed existing job is still the existing job; do not silently create a second job for the same key
- protect with SQLite `UNIQUE(idempotency_key)` and transaction logic, not only an application-level pre-check

---

## 5. Background Worker + FastAPI Lifespan

### Task 4: Add lifespan-managed single worker

**Files:**
- Create: `sra_api/services/report_job_worker.py`
- Modify: `sra_api/main.py`
- Test: `tests/test_report_job_worker.py`, `tests/test_report_jobs_lifecycle.py`

Requirements:
- use FastAPI lifespan, not request-scoped `BackgroundTasks`, for durable Job execution
- startup order:
  1. initialize DB/schema
  2. atomically mark stale `running` jobs as `interrupted`
  3. start one worker
- shutdown:
  1. set stop signal
  2. stop taking new jobs
  3. bounded join / cleanup according to implementation

Worker loop:
1. atomically claim a queued job
2. convert Job `prompt` to one user message and construct the internal payload expected by shared service
3. call `execute_agent_turn(..., request=None, session_id=job.session_id)`
4. call existing `ExportWordService.build_docx_bytes(turn.output, ...)`
5. write DOCX to temp file under configured reports root
6. flush/close and atomically rename temp to final job-owned filename
7. update Job to `completed`
8. on exception, remove temp artifact and set `failed` with sanitized error

No internal HTTP client is allowed.

Tests:
- lifespan starts exactly one worker
- shutdown signals worker
- competing claims execute a job only once
- worker directly invokes mocked shared service; test should fail if internal HTTP client path appears
- exception leaves no downloadable final or partial DOCX

---

## 6. Job Router

### Task 5: Add Job HTTP resources

**Files:**
- Create: `sra_api/routers/report_jobs.py`
- Modify: `sra_api/main.py`
- Test: `tests/test_report_jobs_api.py`

Implement:
- `POST /v1/report/jobs`
- `GET /v1/report/jobs/{job_id}`
- `GET /v1/report/jobs/{job_id}/word`

OpenAPI:
- explicitly describe `202`, `404`, `409`, `500`
- document DOCX MIME type on download
- document `Idempotency-Key`

CORS:
- add `Idempotency-Key` to `allow_headers`
- add browser preflight test verifying the header is permitted

Error sanitization:
- do not return traceback, local filesystem paths, API keys, full internal exception repr, or upstream secrets
- retain a short type/category and safe message

---

## 7. Atomic Word Storage and Filename Safety

### Task 6: Add/centralize safe Job file persistence

**Files:**
- Prefer Create: focused helper under `sra_api/services/` if needed
- Modify `export_word_service.py` only if a small reusable helper naturally belongs there
- Test: `tests/test_report_job_worker.py`, `tests/test_export_word_service.py`

Rules:
- request filename is presentation metadata only
- physical final basename is generated by the server, e.g. `<job_id>.docx`
- Content-Disposition may use a sanitized logical filename
- temp file and final file must both be under configured reports root
- final publication uses atomic rename/replace on same filesystem
- a half-written DOCX must never be downloadable

Tests:
- `../../etc/passwd` or path separators in requested filename never escape reports root
- completed DB row with missing final file returns `500`
- failed write leaves no final file

---

## 8. Existing API Regression Boundary

### Task 7: Protect existing sync/chat/legacy export behavior

**Files:**
- Modify tests only unless shared helper extraction is required:
  - `tests/test_report_word_api.py`
  - `tests/test_turn_execution_service.py`
  - `tests/test_chat_word_export_metadata.py`
  - `tests/test_export_word_service.py`
  - `tests/test_api_security_boundaries.py`

Hard requirements:
- `POST /v1/report/word` remains synchronous and working
- `/v1/chat/completions` remains OpenAI-compatible
- `/v1/export/word` remains snapshot-based compatibility download
- legacy export must not read Job SQLite or Job output files
- Job API must not alter chat/session response formatting

Baseline already reviewed:
- targeted suite reported `41 passed, 3 warnings` before implementation

Final implementation must rerun the same regressions plus new Job tests.

---

## 9. Documentation and SVG Single Source of Truth

### Task 8: Add maintained architecture/API/operations documentation

**Files:**
- Create: `docs/architecture/dual-mode-report-api.md`
- Create: `docs/architecture/dual-mode-report-api.svg`
- Create: `docs/architecture/report-job-lifecycle.svg`
- Create: `docs/api/report-api.md`
- Create: `docs/operations/report-jobs.md`
- Modify: `README.md`
- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/memory.md`
- Modify: `.codex/backlog.md`
- Modify: `.codex/known_issues.md`

Formal terminology:
- say **single-machine persisted job state** / **pollable result resource**
- do not claim exactly-once, high availability, or crash-resumable execution
- explain that process crash during `running` becomes `interrupted`

Architecture doc must explain:
- why sync and async modes both remain supported
- shared execution core
- worker lifecycle
- SQLite transaction/claim model
- file persistence model
- restart semantics
- idempotency
- current single-process limitation

API doc must include:
- sync vs async selection guide
- complete request/response examples
- Python polling example
- curl examples
- 404/409/500 behavior
- Idempotency-Key behavior

Operations doc must include:
- Nginx timeout guidance for sync endpoint
- environment variables
- SQLite location
- reports root
- handling `interrupted` jobs
- local disk retention caveat
- troubleshooting completed-but-file-missing error

### SVG ownership rule

There must be only one maintained architecture SVG:
- canonical: `docs/architecture/dual-mode-report-api.svg`

If `docs/superpowers/plans/dual-mode-report-api.svg` exists:
- move it to canonical path if appropriate, or
- replace it with a short plan-level note/link/reference if project conventions permit
- do not maintain duplicate diagram content in two files

---

## 10. Job Lifecycle SVG Contract

The maintained lifecycle diagram must show:

```text
queued ──claim──> running ──success──> completed
                    │
                    ├──runtime error──> failed
                    │
                    └──service restart/crash recovery──> interrupted
```

No `interrupted -> queued` automatic edge in this phase.
No automatic failed retry edge in this phase.

---

## 11. .gitignore / Runtime Data

### Task 9: Exclude runtime artifacts

**Files:**
- Modify: `.gitignore`

Ignore at least:
- `.api_jobs/`
- `*.sqlite3-wal` / `*.sqlite3-shm` if not covered by directory ignore
- temporary Job DOCX names if created outside ignored directory

Do not ignore committed SVG/Markdown docs.

---

## 12. Test Matrix

### Job Store
- schema initialization
- create queued job
- idempotent same-key same-hash returns same job
- same-key different-hash => conflict
- concurrent claim => one winner
- restart recovery keeps queued
- restart recovery changes running to interrupted

### Worker
- worker starts once in lifespan
- worker stops via shutdown signal
- direct shared service invocation, no HTTP
- output generated from current turn result
- success atomic temp->final rename
- failed generation leaves no final/partial downloadable file

### API
- create => `202`
- status queued/running/completed/failed/interrupted
- not found => `404`
- download before complete => `409`
- completed missing file => `500`
- successful DOCX download
- sanitized errors
- path traversal filename harmless
- OpenAPI response documentation
- CORS preflight accepts `Idempotency-Key`

### Regressions
- sync Word API
- chat completions
- chat Word export metadata
- ExportWordService
- API security boundaries
- legacy snapshot `/v1/export/word`

### Documentation
- expected Markdown files exist
- canonical SVG files exist
- no duplicated maintained architecture SVG content in plan path
- SVG parses as XML/text if lightweight validation is practical

---

## 13. Final Verification Commands

Run and report actual outcomes:

```bash
PYTHONPATH=. pytest -q \
  tests/test_report_job_store.py \
  tests/test_report_job_worker.py \
  tests/test_report_jobs_api.py \
  tests/test_report_jobs_lifecycle.py \
  tests/test_report_jobs_docs.py
```

Then regression suite:

```bash
PYTHONPATH=. pytest -q \
  tests/test_turn_execution_service.py \
  tests/test_report_word_api.py \
  tests/test_chat_word_export_metadata.py \
  tests/test_export_word_service.py \
  tests/test_api_security_boundaries.py
```

Then full suite:

```bash
PYTHONPATH=. pytest tests -q --tb=short
python -m compileall sra_api
git diff --check
```

Do not report tests as passing unless they were actually executed and passed.

---

## 14. Acceptance Criteria

- [ ] Existing synchronous `POST /v1/report/word` still works.
- [ ] New `POST /v1/report/jobs` returns quickly with `202 + job_id`.
- [ ] Job request contract is fixed and documented (`prompt`, default model, `session_id`, supported options, metadata).
- [ ] Worker calls transport-neutral shared service directly.
- [ ] Worker is managed by FastAPI lifespan, not request BackgroundTasks.
- [ ] SQLite uses transaction-safe create/idempotency and atomic queued->running claim.
- [ ] Startup marks stale running jobs interrupted before starting worker.
- [ ] Idempotency key is protected by DB UNIQUE semantics.
- [ ] `Idempotency-Key` is accepted by CORS preflight.
- [ ] Download status codes are fixed to 404/409/500 semantics.
- [ ] Job download cannot path-traverse outside reports root.
- [ ] Word publication is atomic; partial files are not downloadable.
- [ ] `/v1/export/word` remains snapshot-based and independent from Job storage.
- [ ] Formal docs avoid overstating durability/HA guarantees.
- [ ] Canonical architecture SVG exists only under `docs/architecture/` as the maintained source.
- [ ] Job lifecycle SVG documents interrupted semantics with no auto-retry.
- [ ] Targeted and full regression tests pass or failures are reported accurately.
- [ ] `.codex` project memory/docs are updated.

---

## 15. Codex Implementation Prompt

```text
請依下列最終計劃完整實作：

docs/superpowers/plans/2026-09-01-dual-mode-word-report-job-api-plan-v3.md

這份 v3 已整合前一輪 review 結果，請以它取代舊 v2 計劃。

開始前：
1. 依 AGENTS.md 順序載入 .codex 專案記憶。
2. 再次確認目前 branch 與 review baseline 一致。
3. 保留 review 已驗證通過的同步功能與既有 API contract。

實作時請嚴格遵守：
- POST /v1/report/word 保留原 ChatPayload contract 與同步 DOCX 行為。
- Job API 使用獨立 request model；service boundary 將 prompt 轉成單一 user message。
- model 預設值必須明確定義並寫入文件。
- session_id 直接傳入 shared service，不得為 worker 偽造 FastAPI Request。
- execute_agent_turn 或更底層 core 必須 transport-neutral，worker 不得 internal HTTP。
- 使用 FastAPI lifespan 啟動唯一 worker；不要用 request BackgroundTasks 執行 durable job。
- startup 先 running -> interrupted，再啟動 worker。
- SQLite 每執行緒/操作使用獨立 connection、busy timeout、transaction-safe atomic claim。
- Job create 的 Idempotency-Key 必須以 UNIQUE constraint + normalized request hash 實作。
- 同 key 同 hash 回原 job；同 key 不同 hash 回 409；失敗 job 也不得同 key 偷建新 job。
- CORS allow_headers 加入 Idempotency-Key 並測 preflight。
- Job download contract 固定：不存在 404；未完成/failed/interrupted 409；completed 但檔案遺失/不合法 500。
- 實體 Word 路徑只能由設定的 reports root + 系統生成 job identity 決定；request filename 只能作為安全化後的下載顯示名稱。
- Word 必須 temp write + atomic rename；失敗不得留下可下載半成品。
- /v1/export/word 維持既有 snapshot compatibility contract，不得改讀 Job DB/Job DOCX。
- 本版只宣稱單機持久化 job metadata 與可輪詢結果，不宣稱 HA、exactly-once、crash-resumable。
- 正式 SVG 唯一維護來源為 docs/architecture/dual-mode-report-api.svg；不要保留兩份會分岔的架構圖。

請採 TDD，按 plan task-by-task 實作。

完成後必須執行：
1. 新 Job targeted tests。
2. review baseline regression tests（原先為 41 passed, 3 warnings 的那組）。
3. 完整 PYTHONPATH=. pytest tests -q --tb=short。
4. python -m compileall sra_api。
5. git diff --check。

並更新：
- README.md
- docs/architecture/dual-mode-report-api.md
- docs/architecture/dual-mode-report-api.svg
- docs/architecture/report-job-lifecycle.svg
- docs/api/report-api.md
- docs/operations/report-jobs.md
- .codex/api_contract.md
- .codex/architecture.md
- .codex/decisions.md
- .codex/memory.md
- .codex/backlog.md
- .codex/known_issues.md

最後請回報：
- 修改/新增檔案
- 最終 Job API contract
- worker/lifespan 行為
- SQLite/idempotency 交易設計
- sync vs async 使用方式
- 文件與 SVG 路徑
- 每組實際測試結果
- 仍存在的 single-process / local-disk / interrupted 限制

不得將未執行的測試宣稱成功，也不要擴充到 Redis/Celery/PostgreSQL/Airflow。
```
