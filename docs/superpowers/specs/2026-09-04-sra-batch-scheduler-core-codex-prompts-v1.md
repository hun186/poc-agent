# Codex Prompts — SRA Batch Scheduler Core Phase 1 v1

## Codex Prompt — Phase 1 Batch Scheduler Core Implementation Contract

你是這個 repository 的 implementation agent。請依 actual repository 實作 **SRA Batch Scheduler Core Phase 1**。你的角色是按既有 Design / Plan 執行，不是重新定義產品需求或另起架構。

### A. Baseline / authority

開始修改前必須依序完整閱讀：

1. `AGENTS.md`
2. `.codex/memory.md`
3. `.codex/architecture.md`
4. `.codex/api_contract.md`
5. `.codex/known_issues.md`
6. `.codex/decisions.md`
7. `.codex/backlog.md`
8. `docs/superpowers/specs/2026-09-04-sra-batch-scheduler-core-design-v1.md`
9. `docs/superpowers/plans/2026-09-04-sra-batch-scheduler-core-plan-v1.md`
10. Phase 0 authoritative security design/review files currently present under `docs/superpowers/`

然後執行並記錄：

```bash
pwd
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
```

回報：Repository、Branch、baseline commit、working tree state。

如果本 Prompt / Plan 中的檔案路徑與 actual repository 已重構，**actual source code 優先**。先分析衝突，採取最小必要調整；不得因路徑差異自行擴張 scope。

### B. Architectural contract — 不可自行改寫

Phase 1 的 canonical architecture 是：

```text
CSV/XLSX/JSON
    -> standalone batch_scheduler process
    -> dedicated batch service key
    -> POST /v1/report/jobs
    -> GET status
    -> GET completed Word
    -> local atomic DOCX publication
```

禁止把 Batch Scheduler 改成：

- 直接 import / 呼叫 Agent；
- 直接查 Elasticsearch；
- 直接呼叫 `ReportJobWorker`；
- 直接使用 `ExportWordService` 產報告；
- 直接讀寫 SRA Report Job SQLite；
- 內嵌到 FastAPI lifespan 變成第二個 server worker；
- 另建 Redis/Celery/RQ/Kafka/Airflow；
- Server Dashboard；
- Windows GUI。

除非你能以 actual repository 證明現有 Report Job HTTP contract 有 blocking incompatibility，否則不得重新設計這個邊界。若發現 blocking incompatibility，先停止相關擴張、清楚回報衝突與最小修正建議，不要默默改 API architecture。

### C. Security contract

Batch Scheduler 使用獨立 Service Key，scope 必須正好是：

```text
report:job:create
report:job:read
report:job:download
```

不得重用 OpenWebUI Key；不得要求 `report:job:admin`、`model:*`、`report:sync`、`document:read` 或 legacy-download scope。

不得將 raw key、Authorization header、credential digest 或 signed secret 寫入：

- source code；
- SQLite execution records；
- input files；
- logs；
- test output；
- `.codex` memory/docs。

Plan Task 0 要先移除目前 operator E2E harness 中的 raw-looking acceptance key literals，改由 environment variable 供應。這是 source hygiene；若你無法連到 operator deployment，不得虛構「已 revoke/rotate live keys」。

### D. Execution rules

1. 完整依 **Plan v1 Task 0 → Task 10** 執行。
2. 修改前先檢查 actual implementation，不重做已存在的等價功能。
3. TDD：對 production behavior change 先寫 failing test、實際看到預期 RED，再做最小實作並驗證 GREEN。
4. 不得默默弱化 security、transaction、validation、path confinement、atomic file publication、idempotency、error handling。
5. 不得用 mock/fake result 宣稱真實 Batch / Agent / Elasticsearch E2E 完成。
6. repository regression 可 mock HTTP transport seam；**deployment acceptance 必須真實走 SRA API → Report Job worker → Router → Elasticsearch → long Agent → Word**。
7. 遠端 `failed` / `interrupted` 在 Phase 1 不自動重送新 job。
8. scheduler restart 必須透過穩定 Idempotency-Key 恢復，不能建立 duplicate remote report。
9. long report 由 remote Job async 執行，scheduler 不應用 30–60 分鐘單一 HTTP read timeout 等待生成。
10. 遇 Plan 與 source 衝突時先分析，採最小必要調整並在 Deviations from Plan 中列出。

### E. Required functional result

至少完成：

```text
batch_scheduler/
  config/models
  CSV/XLSX/JSON loader
  versioned local SQLite store
  narrow SRA Report Job HTTP client
  resumable scheduler state machine
  atomic validated DOCX output
  CLI validate/import/run/resume/status/execute
```

Canonical input至少支援：

```text
task_id
prompt
filename (optional)
session_id (optional)
model (optional/default)
scheduled_at (optional offset-aware ISO8601)
metadata / metadata_json (optional object)
```

Phase 1 只支援一次性 immediate / scheduled-at execution，不實作 cron/recurrence。

### F. Required tests

至少新增並執行：

```text
tests/test_batch_scheduler_input.py
tests/test_batch_scheduler_store.py
tests/test_batch_scheduler_client.py
tests/test_batch_scheduler_service.py
tests/test_batch_scheduler_cli.py
tests/test_batch_scheduler_security.py
```

必須覆蓋：

- CSV/XLSX/JSON normalization equivalence；
- validation / duplicate task rejection；
- offset-aware scheduled time；
- source import idempotency/conflict；
- scheduler DB `user_version`；
- deterministic task Idempotency-Key；
- POST/poll/download HTTP contract；
- retryable vs non-retryable failures；
- `401/403` credential fail-fast；
- crash after accepted POST but before local persistence → resume 使用同一 key / 同一 remote job；
- restart reconciliation；
- path traversal confinement；
- invalid DOCX rejection；
- atomic publication；
- raw key not persisted/logged；
- CLI exit codes / JSON status。

### G. Verification gate

依 AGENTS.md 先確認 dependencies：

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

然後至少執行：

```bash
PYTHONPATH=. pytest -q \
  tests/test_batch_scheduler_input.py \
  tests/test_batch_scheduler_store.py \
  tests/test_batch_scheduler_client.py \
  tests/test_batch_scheduler_service.py \
  tests/test_batch_scheduler_cli.py \
  tests/test_batch_scheduler_security.py \
  --tb=short

PYTHONPATH=. pytest -q \
  tests/test_report_jobs_api.py \
  tests/test_report_job_store.py \
  tests/test_report_job_worker.py \
  tests/test_job_authorization.py \
  tests/test_service_key_store.py \
  tests/test_service_key_api.py \
  tests/test_phase0_security_acceptance.py \
  --tb=short

PYTHONPATH=. pytest tests -q --tb=short
python -m compileall -q batch_scheduler sra_api api tests
git diff --check
```

再做 focused secret/runtime-artifact scan。掃描不得把 raw secret 值回顯到報告。

### H. Real deployment acceptance

如果 Codex environment 可連到 private SRA deployment 與 real Elasticsearch，依 Plan Task 10 跑真實 Batch E2E：

```text
dedicated batch key
-> import real CSV/XLSX/JSON tasks
-> POST /v1/report/jobs
-> real remote state transitions
-> Router / Elasticsearch / long Agent
-> completed job
-> GET Word
-> valid local DOCX
-> stop/restart scheduler
-> resume without duplicate remote job
```

至少兩個真實 task，並使用至少一個 tabular input（CSV/XLSX）和一個 JSON input。

如果 private network 不可達，明確回報：

```text
Phase 1 real deployment acceptance: NOT EXECUTED
```

不得把 mock transport / local unit test 當作真實 E2E。

### I. Project memory / docs

完成後依 `AGENTS.md` 更新：

```text
.codex/memory.md
.codex/architecture.md
.codex/api_contract.md
.codex/known_issues.md
.codex/decisions.md
.codex/backlog.md
```

並建立/更新：

```text
docs/operations/batch-scheduler.md
.env.example
README.md（只做必要連結/入口更新）
```

若 active memory 觸發 compaction threshold，依 AGENTS.md 先歸檔再濃縮，不可直接丟失歷史。

### J. Completion report — 必須逐項回報

最後回報固定包含：

```text
Repository
Branch
Baseline commit
Resulting commit (if created)
Design version
Plan version
Changed files
Behavior changes
Tests executed
Exact test results
Real deployment acceptance status
Deviations from Plan
Remaining issues / risks
Working tree status
PR status
```

特別列出：

```text
Phase 0 source-secret hygiene: PASS / NOT PASS
Batch Scheduler repository gate: PASS / NOT PASS
Real SRA/Elasticsearch batch E2E: PASS / NOT EXECUTED / FAIL
Restart/resume duplicate-prevention evidence: PASS / NOT EXECUTED / FAIL
Credential rotation/revocation evidence: PASS / NOT EXECUTED / FAIL
```

只有 repository tests 及真實 deployment acceptance 都通過時，才可以宣稱：

> Phase 1 Batch Scheduler repository gate passed and real SRA/Elasticsearch deployment acceptance passed.

若只完成 repository gate，必須分開寫：

> Phase 1 Batch Scheduler repository gate passed; real deployment acceptance remains pending/not executed.

---

## Codex Prompt — Phase 1 Post-Implementation Review

只 review Phase 1 Batch Scheduler implementation，不新增功能。

依序讀：

1. Design v1
2. Plan v1
3. actual source/diff
4. test results
5. `.codex` updates

逐項檢查：

- scheduler 是否只走 HTTP Report Job boundary；
- Batch Key scopes 是否最小化；
- raw credential 是否可能被 source/db/log/status 洩漏；
- CSV/XLSX/JSON 是否真正 converges to one canonical model；
- import 是否 all-or-nothing；
- scheduler DB 是否 versioned；
- submit crash window 是否由 deterministic Idempotency-Key 安全恢復；
- resume 是否不會重複建立 remote report；
- remote failed/interrupted 是否沒有被偷偷 auto-retry；
- path traversal / overwrite / invalid DOCX 是否 fail closed；
- credential 401/403 是否是 process-level failure 而不是大量 task fake failures；
- CLI 是否只做 adapter，不複製 service logic；
- repository tests 是否有 fresh evidence；
- real deployment acceptance 是否真的是 real SRA/ES/Agent，而非 mock。

Review 結果用：

```text
Blocking issue
Major issue
Minor issue
Improvement / optional suggestion
```

若沒有 Blocking/Major，才建議 repository gate PASS；real deployment acceptance 必須獨立判定。
