# Dual-Mode Word Report API + Architecture Docs/SVG Implementation Plan

> For Codex / agentic workers: use this document as the implementation brief. Preserve the existing synchronous `POST /v1/report/word` flow and add an asynchronous Job API for long-running reports. In the same change set, add maintainable architecture documentation in Markdown and an SVG diagram.

## 1. Goal

Build and document a **dual-mode report generation API** for the SRA agent backend:

1. **Synchronous mode** (keep existing behavior):
   - `POST /v1/report/word`
   - Best for manual testing, Chrome F12, curl, one-off runs, and short-to-medium report generation.

2. **Asynchronous job mode** (new):
   - `POST /v1/report/jobs`
   - `GET /v1/report/jobs/{job_id}`
   - `GET /v1/report/jobs/{job_id}/word`
   - Best for long-running reports (10–30+ minutes), batch scheduling, retry-safe integrations, and unstable networks.

3. **Documentation deliverables** (new requirement):
   - Add clear Markdown documentation for the architecture, API usage, and operational guidance.
   - Add at least one **SVG architecture/flow diagram** stored in the repository.

---

## 2. Scope

### In scope
- Keep synchronous Word export API working.
- Add async Job API using the same core execution service.
- Persist job states with SQLite for the current single-process deployment model.
- Add idempotency support for job creation.
- Add developer/operator documentation in Markdown.
- Add SVG architecture diagram(s).
- Add/extend tests.
- Update `.codex` project memory/docs.

### Out of scope for this phase
- Redis / Celery / RQ / RabbitMQ / Kafka
- PostgreSQL migration
- Multi-node distributed workers
- UI pages for job monitoring
- Rewriting agent prompts, report logic, Elasticsearch retrieval, or routing behavior
- Replacing synchronous mode with async mode

---

## 3. Design principles

1. **Two modes, one execution core**
   - Both sync and async modes must reuse the same internal turn execution service.
   - Do not maintain two separate report-generation pipelines.

2. **Synchronous mode remains supported**
   - It is not a legacy fallback.
   - It remains an intentionally supported workflow for manual and convenient single-run usage.

3. **Async mode is durable and timeout-resistant**
   - `POST /v1/report/jobs` should return quickly with `202 Accepted` and a `job_id`.
   - The long-running report generation happens after job creation.

4. **No read-after-write dependence on `state.json`**
   - Background job execution must generate Word directly from the current turn result.
   - Do not route through `state.json` as an intermediate source of truth.

5. **Documentation is part of the feature**
   - This update is not complete unless Markdown docs and SVG diagram(s) are added.

---

## 4. Current baseline assumptions

Codex must verify these assumptions against current code before editing:

- Runtime source of truth is under `sra_api/`.
- A shared execution service already exists (for example `execute_agent_turn()` or equivalent).
- Synchronous `POST /v1/report/word` already works and directly returns DOCX.
- Existing `/v1/chat/completions` and `/v1/export/word` behavior must not regress.

If implementation details differ, preserve the intent and adapt the plan to the real codebase.

---

## 5. Target architecture

### 5.1 High-level flow

- **Sync path**
  - Client sends `POST /v1/report/word`
  - API directly runs the agent turn
  - API directly renders DOCX from the turn result
  - HTTP response returns DOCX bytes

- **Async path**
  - Client sends `POST /v1/report/jobs`
  - API persists job with `queued` status
  - API returns `202 Accepted` + `job_id`
  - Background worker pulls queued job
  - Worker runs the same agent-turn execution core
  - Worker writes DOCX to disk atomically
  - Worker updates job status to `completed` / `failed`
  - Client polls `GET /v1/report/jobs/{job_id}` and downloads via `GET /v1/report/jobs/{job_id}/word`

### 5.2 Job statuses

Supported statuses:
- `queued`
- `running`
- `completed`
- `failed`
- `interrupted`

Behavior notes:
- `queued`: created but not yet running
- `running`: actively processing
- `completed`: Word is available
- `failed`: completed unsuccessfully; include error metadata
- `interrupted`: process restarted or died while previously `running`; do not auto-rerun in this phase

### 5.3 Restart semantics

On API startup:
- Keep `queued` jobs as `queued`
- Convert stale `running` jobs to `interrupted`
- Do not automatically retry `interrupted` jobs in this phase

---

## 6. API contract

### 6.1 Keep existing synchronous endpoint

#### `POST /v1/report/word`

Purpose:
- Generate one Word report and directly return the DOCX.

Best for:
- Chrome F12 manual test
- curl test
- one-off scripts
- short or medium runs where waiting on one connection is acceptable

Behavior:
- Response is DOCX binary on success.
- Must continue to use shared execution core.
- Must not regress compared with current working version.

### 6.2 New async endpoints

#### `POST /v1/report/jobs`

Purpose:
- Create an asynchronous report job.

Expected behavior:
- Persist job first.
- Return quickly.
- Response status: `202 Accepted`

Suggested request body:

```json
{
  "prompt": "請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊。",
  "filename": "gaza_report_2026-09-01.docx",
  "session_id": "batch-gaza-20260901",
  "metadata": {
    "task_id": "gaza-daily-001",
    "department": "political-diplomatic"
  }
}
```

Optional headers:
- `Idempotency-Key: <string>`

Suggested response body:

```json
{
  "job_id": "rpt_20260901_000123",
  "status": "queued",
  "status_url": "/v1/report/jobs/rpt_20260901_000123",
  "download_url": "/v1/report/jobs/rpt_20260901_000123/word"
}
```

#### `GET /v1/report/jobs/{job_id}`

Purpose:
- Fetch current job status and metadata.

Suggested response examples:

Queued / running:

```json
{
  "job_id": "rpt_20260901_000123",
  "status": "running",
  "created_at": "2026-09-01T09:00:00Z",
  "updated_at": "2026-09-01T09:02:00Z",
  "filename": "gaza_report_2026-09-01.docx"
}
```

Completed:

```json
{
  "job_id": "rpt_20260901_000123",
  "status": "completed",
  "created_at": "2026-09-01T09:00:00Z",
  "updated_at": "2026-09-01T09:28:30Z",
  "filename": "gaza_report_2026-09-01.docx",
  "download_url": "/v1/report/jobs/rpt_20260901_000123/word"
}
```

Failed:

```json
{
  "job_id": "rpt_20260901_000123",
  "status": "failed",
  "error": {
    "type": "runtime_error",
    "message": "Report generation failed during retrieval stage."
  }
}
```

#### `GET /v1/report/jobs/{job_id}/word`

Purpose:
- Download the generated Word file when the job is completed.

Behavior:
- Return 404 or 409-style structured error when the job is not completed.
- Return DOCX bytes with proper content type and filename when ready.

---

## 7. Persistence design

### 7.1 SQLite job store

Use SQLite for this phase.

Suggested fields:
- `job_id`
- `status`
- `prompt`
- `filename`
- `session_id`
- `metadata_json`
- `idempotency_key`
- `turn_id`
- `docx_path`
- `error_type`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`
- `updated_at`

### 7.2 File storage

Suggested output directory:
- `.api_jobs/reports/`

Suggested behavior:
- Write to temp file first
- Rename atomically to final path on success
- Store final file path in SQLite

---

## 8. Concurrency model

For this phase:
- single API process
- single background worker thread/process is acceptable
- default worker concurrency = 1

Reason:
- safer with existing session/memory assumptions
- simpler to debug and maintain

Do not assume current agent/session state is multi-thread safe.

---

## 9. Idempotency

Support optional `Idempotency-Key` for `POST /v1/report/jobs`.

Expected behavior:
- same idempotency key + same normalized request payload => return existing job
- same idempotency key + different meaningful payload => return conflict error

This prevents duplicate long-running jobs when client retries after network issues.

---

## 10. Documentation deliverables (new requirement)

Codex must create/update Markdown documentation and SVG diagram(s).

### 10.1 Required Markdown files

At minimum, create/update the following docs (adapt exact paths if repo conventions differ):

1. `docs/architecture/dual-mode-report-api.md`
   - Why both sync and async modes exist
   - System overview
   - Component responsibilities
   - Status lifecycle
   - Restart semantics
   - Trade-offs

2. `docs/api/report-api.md`
   - Endpoint reference
   - Request/response examples
   - curl examples
   - Python examples
   - Error examples
   - When to use sync vs async

3. `docs/operations/report-jobs.md`
   - Operational guidance
   - Nginx timeout guidance for sync endpoint
   - Where SQLite lives
   - Where Word files are stored
   - How to inspect/recover job issues
   - Known limitations of phase 1 async implementation

4. Update repository-level references as needed:
   - `README.md` (brief overview + links)
   - `.codex/api_contract.md`
   - `.codex/architecture.md`
   - `.codex/decisions.md`
   - `.codex/memory.md`
   - `.codex/backlog.md`
   - `.codex/known_issues.md` (if new operational caveats exist)

### 10.2 Required SVG diagram(s)

At minimum, create:

1. `docs/architecture/dual-mode-report-api.svg`
   - One high-level architecture diagram showing:
     - clients
     - sync path
     - async path
     - shared execution core
     - Word generation
     - SQLite job store
     - reports directory

Optional but encouraged:

2. `docs/architecture/report-job-lifecycle.svg`
   - State transition diagram:
     - queued → running → completed
     - queued → running → failed
     - running → interrupted (on restart/crash)

### 10.3 SVG generation constraints

- SVG should be committed as a plain text `.svg` file.
- Prefer a hand-authored clean SVG or a reproducible diagram export.
- Keep labels readable in GitHub preview.
- Avoid depending on proprietary binary diagram files as the sole source.
- If generated from Mermaid/PlantUML/etc., also keep the source text if that matches repo practices.

---

## 11. Suggested file changes

Codex should confirm actual file names, but likely changes are around:

### Modify
- `sra_api/.../report endpoint module`
- `sra_api/services/turn_execution.py`
- `sra_api/services/export_word_service.py` (or equivalent)
- `README.md`
- `.codex/*.md`
- existing tests for API / Word export

### Add
- `sra_api/services/job_store.py`
- `sra_api/services/report_job_service.py`
- `sra_api/services/report_job_worker.py`
- `sra_api/routes/report_jobs.py` (or equivalent)
- tests for job store / worker / API
- `docs/architecture/dual-mode-report-api.md`
- `docs/api/report-api.md`
- `docs/operations/report-jobs.md`
- `docs/architecture/dual-mode-report-api.svg`
- optionally `docs/architecture/report-job-lifecycle.svg`

---

## 12. Testing requirements

Follow TDD.

### 12.1 Sync regression tests
- Existing `POST /v1/report/word` still returns DOCX.
- Existing `/v1/chat/completions` still works.
- Existing `/v1/export/word` still works.

### 12.2 Async API tests
- create job returns `202` and `job_id`
- get job returns `queued` / `running` / `completed`
- download Word works only when completed
- failed job returns structured error/status

### 12.3 Persistence tests
- SQLite record written on create
- completed job stores DOCX path
- running jobs become `interrupted` on startup recovery
- queued jobs remain queued after restart recovery logic

### 12.4 Idempotency tests
- same key + same payload returns existing job
- same key + different payload returns conflict

### 12.5 File output tests
- DOCX exists on disk after completed job
- file is non-empty
- if test harness already validates DOCX zip structure, keep that coverage

### 12.6 Docs/asset checks
- Markdown docs exist and reference the correct endpoints
- SVG files exist in expected paths
- optional: simple test or lint to ensure SVG files are valid XML text (lightweight)

### 12.7 Suggested final verification
- targeted pytest for changed areas
- full `pytest tests -q --tb=short`
- `python -m compileall sra_api`
- `git diff --check`

---

## 13. Acceptance criteria

This work is complete only if all are true:

1. Sync `POST /v1/report/word` still works.
2. Async job endpoints exist and work.
3. Both sync and async modes reuse the same execution core.
4. Async mode does not call sync mode via internal HTTP.
5. Async Word generation does not depend on `state.json` read-after-write.
6. Job status persistence works via SQLite.
7. Interrupted/running restart behavior is explicit and documented.
8. Idempotency support exists for job creation.
9. Markdown architecture/API/operations docs are added.
10. SVG architecture diagram is added and committed.
11. Tests pass and results are reported honestly.
12. `.codex` memory/docs are updated.

---

## 14. Suggested prompt to Codex (review-first)

```text
請先不要修改程式碼。

請依 AGENTS.md 順序讀取 .codex 專案記憶，然後審查：

docs/superpowers/plans/2026-09-01-dual-mode-word-report-job-api-plan-v2.md

並與目前 branch 的實際程式碼比對。

請特別確認：
1. 現有同步 POST /v1/report/word 是否正常且設計上保留。
2. 是否已有共用 turn execution service 可同時支撐 sync 與 async 模式。
3. 新 Job API 是否能以 SQLite + 單 process background worker 乾淨落地。
4. async worker 是否可以直接呼叫 shared service，而不透過 HTTP 呼叫 sync endpoint。
5. 文件與 SVG 需求在目前 repo 結構中應該放在哪些路徑最合理。
6. 測試策略是否完整且不會破壞現有 /v1/chat/completions 與 /v1/export/word。

只列出：
- 開工前真的需要修正的計劃問題
- 可以直接照做的部分
- 預計新增/修改的檔案清單

如果沒有阻斷問題，最後請明確回答：
「可依此計劃實作」

此階段不要修改 code。
```

---

## 15. Suggested prompt to Codex (implementation)

```text
請依下列計劃完整實作：

docs/superpowers/plans/2026-09-01-dual-mode-word-report-job-api-plan-v2.md

開始前請依 AGENTS.md 順序讀取 .codex 專案記憶，並用目前程式碼確認 baseline；若文件與程式碼衝突，以程式碼為準，並同步修正文檔。

本次核心原則：
1. 保留現有 POST /v1/report/word，同步模式正式支援，不可移除或弱化。
2. 新增：
   - POST /v1/report/jobs
   - GET /v1/report/jobs/{job_id}
   - GET /v1/report/jobs/{job_id}/word
3. sync 與 async 必須共用同一套 turn execution core 與 Word export core。
4. async 建立 job 時必須快速回傳 202 + job_id，不得在該 HTTP request 內完整執行 agent。
5. async worker 不得透過 HTTP 呼叫 sync endpoint，也不得依賴 state.json read-after-write。
6. 本版採 SQLite + single-process background worker + concurrency=1，不引入 Redis / Celery / PostgreSQL / Airflow。
7. 支援 queued / running / completed / failed / interrupted。
8. restart 後 queued 可保留；running 改標記 interrupted，不自動重跑。
9. 支援 optional Idempotency-Key。
10. 這次功能的一部分是文件化：請新增 Markdown 架構/API/維運文件與 SVG 架構圖。

文件交付要求：
- 新增/更新 Markdown 文件（architecture / api / operations）
- 新增 docs/architecture/dual-mode-report-api.svg
- 若合適，可再補 report-job-lifecycle.svg
- README 與 .codex 記憶同步更新

請採 TDD：
- 每個 task 先補 failing tests
- 再做最小實作
- 完成後跑 targeted tests

完成後請：
1. 跑計劃內的 targeted tests。
2. 跑完整 pytest tests -q --tb=short。
3. 跑 python -m compileall sra_api。
4. 跑 git diff --check。
5. 更新 .codex/api_contract.md、.codex/architecture.md、.codex/decisions.md、.codex/memory.md、.codex/backlog.md，必要時更新 .codex/known_issues.md。
6. 回報實際測試結果，不得把未執行測試說成成功。
7. 最後整理：修改檔案、API 用法、文件路徑、SVG 路徑、測試結果、已知限制、下一步建議。
```

---

## 16. Suggested usage guidance to include in docs

### Use synchronous `POST /v1/report/word` when:
- manually testing in browser/Chrome F12
- using curl for one-off validation
- debugging a single report
- operator is okay waiting on one connection
- report duration is modest and upstream timeout is configured generously

### Use async Job API when:
- report may run 10–30+ minutes
- scheduling many report items
- network stability is uncertain
- retry safety matters
- operator wants durable status tracking and later download

---

## 17. Notes for operators

Document at least these operational caveats:
- synchronous endpoint may require Nginx `proxy_read_timeout` tuning
- async mode is safer for long-running jobs
- first async version uses SQLite and single-process worker semantics
- if service restarts during a running job, status becomes `interrupted`
- this phase intentionally avoids auto-retry to reduce duplicate expensive runs

