# Requirement Automatic Operator E2E Harness Implementation Plan v1

## 1. Baseline

**Repository:** `hun186/poc-agent`  
**Design:** Requirement Automatic Operator E2E Harness Design v1  
**Plan version:** v1  
**Design baseline:** hosted `main` `4fd6f1adad66c3cfc20a91ad556c6da7e8a2da9b`

Implementation 開始時仍必須重新查 hosted `main`。

如果 HEAD 已變：

- 重新讀 affected source。
- source 優先。
- 若只是 unrelated change，可記錄新 baseline 後繼續。
- 若 Design contract 所依賴的 Requirement/Schedule/Handoff/Report Job source 已發生 material change，停止實作並要求 Design/Plan rebaseline。
- 不得自行 redesign。

---

# 2. Intended File Set

預期新增：

```text
operator_e2e/test_requirement_schedule_e2e.py
operator_e2e/requirement_e2e_support.py
operator_e2e/requirement_e2e_profile_v1.json
tests/test_requirement_operator_e2e_harness.py
docs/operations/requirement-automatic-operator-e2e.md
```

預期修改：

```text
requirement_scheduler/store.py
.gitignore
```

必要時修改現有 focused test：

```text
tests/test_requirement_schedule_store.py
```

原則上不需修改：

```text
sra_api/routers/requirement_schedules.py
requirement_scheduler/schedule_worker.py
requirement_scheduler/coordinator.py
requirement_scheduler/legacy_report_job_gateway.py
requirement_scheduler/artifacts.py
run_sra_api.sh
```

除非 fresh source rebaseline 證明 Design assumption 已改變。

---

# 3. Task 1 — Add Read-Only Batch Evidence Projection

## Goal

讓 existing Batch Run GET 可以提供 Harness 已存在但目前未 projection 的 durable evidence。

## Production change

在 existing `ScheduleStore.get_batch_run()` projection 中加入：

Batch：

```text
snapshot_id
phase1a_output_root_fingerprint
```

Run Item：

```text
remote_job_id
remote_job_state
```

Current schema 本來就有這些欄位，因此不得新增 migration。

## TDD

先新增 failing tests，證明 GET projection 必須包含上述欄位。

驗：

```python
assert run["snapshot_id"] == "snap-1"
assert run["phase1a_output_root_fingerprint"] == "a" * 64
assert run["items"][0]["remote_job_id"] == "job-1"
assert run["items"][0]["remote_job_state"] == "running"
```

再做最小 SELECT projection 修改。

## Regression

至少執行：

```bash
pytest -q \
  tests/test_requirement_schedule_store.py \
  tests/test_requirement_schedule_api.py \
  tests/test_requirement_schedule_v5_closure.py
```

Acceptance：

- no schema change
- no write behavior change
- no Handoff behavior change
- no Report Job ownership change

---

# 4. Task 2 — Harness Core Types, Configuration and Redaction

## Files

```text
operator_e2e/requirement_e2e_support.py
tests/test_requirement_operator_e2e_harness.py
```

## Implement

建立 focused types/helpers：

```text
StageStatus
StageResult
HarnessFailure
HarnessResult
ExitCode
E2EConfig
```

加入：

- `SRA_E2E_*` env file parser
- env override precedence
- auth-mode validation
- timeout validation
- e2e_run_id generator
- atomic JSON/text writer
- output directory creation
- single-run file lock
- safe redaction
- bounded log tail

## TDD Cases

必須先寫 failing tests：

1. e2e.env.local 出現 non-`SRA_E2E_*` key → reject。
2. process environment override local file。
3. token 與 username/password 同時存在 → reject ambiguity。
4. missing model → exit code 2。
5. missing artifact root → exit code 2。
6. known bearer token 不得出現在 redacted diagnostics。
7. `Authorization: Bearer ...` redacted。
8. password/secret/PWD/connection string redacted。
9. raw `os.environ` 永不進 result。
10. concurrent lock → safe precheck failure。
11. result write 使用 atomic replace。
12. output uses per-run directory，不覆寫 previous result。

---

# 5. Task 3 — XLSX / Requirement Fixture / Import Flow

## Files

```text
operator_e2e/requirement_e2e_profile_v1.json
operator_e2e/test_requirement_schedule_e2e.py
operator_e2e/requirement_e2e_support.py
tests/test_requirement_operator_e2e_harness.py
```

## Fixture profile

建立 exact canonical profile v1。

使用：

```text
external_item_id
title
prompt_content
source_updated_at
source_created_at
expires_at
```

Current manual source config允許 xlsx/csv/json；本 Harness v1 明確只測 XLSX。

## Implement

依序：

```text
authenticate
→ GET pipeline readiness
→ ensure Profile
→ ensure approved Profile Version
→ ensure Source
→ preview XLSX
→ validate exactly 3
→ commit
→ identify Requirement Set
→ identify exact new Snapshot
→ list Snapshot Items
→ validate 3 active
```

## Create/reuse tests

Fake HTTP transport 測：

- absent fixture → create
- one exact fixture → reuse
- exact draft profile version → safely complete
- one drifted fixture → fail
- duplicate fixture → fail
- disabled exact source → safe enable if Design-owned
- unrelated source 不得 patch

## Ambiguous write tests

特別測 Import Commit：

```text
request timeout
→ durable reread
```

三種結果：

- exactly one matching Snapshot → recover as success
- zero → bounded retry
- >1 → fail ambiguous

不得 blind retry。

---

# 6. Task 4 — Automatic Schedule Lifecycle

## Implement

對 exact E2E Schedule：

1. ensure exact schedule shell。
2. 若 previous Harness-owned schedule 還 enabled，正常 API disable。
3. capture baseline Batch Run IDs。
4. create new Schedule Version。
5. recurrence：
   ```text
   interval / 10080 minutes / future anchor
   ```
6. approve。
7. enable。
8. capture returned `next_run_at`。
9. validate near-future window。
10. **只 poll GET APIs。**
11. locate exactly one new scheduled Batch。
12. validate:
   ```text
   trigger_type
   schedule_version_id
   scheduled_for
   snapshot_id
   ```
13. validate 3 selected items。
14. validate `next_run_at` advanced。
15. immediately disable schedule。

## Mandatory negative tests

測試 Harness code 不會呼叫：

```text
POST .../runs
```

可以讓 fake transport 在收到此 route 時直接：

```python
raise AssertionError("manual run forbidden")
```

也不得 shell out：

```text
schedule-worker --once
handoff-worker
```

## Timing tests

涵蓋：

- future anchor → valid next run
- next_run_at 一週後 → fail out-of-window
- no batch before deadline → automatic_claim_timeout
- one matching scheduled batch → pass
- two new matching scheduled batches → fail
- trigger_type=manual → fail
- wrong snapshot_id → fail
- wrong schedule_version_id → fail

---

# 7. Task 5 — Handoff / Remote Jobs / Terminal State

## Implement polling

對 exact `batch_run_id`：

### HANDOFF

等待全部 selected items：

```text
remote_job_id != null
dispatched_at != null
```

### REPORT_JOBS

驗：

```text
len(items) == 3
len(unique remote_job_id) == 3
```

### REMOTE_EXECUTION

持續 observe：

```text
remote_job_state
execution_state
```

直到：

```text
3 remote_job_state == completed
```

若任一：

```text
failed
recovery_required
expired
```

立即結束相應 stage，不等滿 timeout。

### TERMINAL

最後：

```text
all item.execution_state == completed

batch.state == completed
batch.success_count == 3
batch.failure_count == 0
```

## Tests

涵蓋：

- 3 unique jobs
- duplicate remote_job_id → fail
- missing remote_job_id → timeout/fail
- one failed remote job → fail early
- recovery_required → fail early
- remote timeout
- batch completed_with_failures → fail

---

# 8. Task 6 — DOCX / SHA / Artifact Root Verification

## Implement

使用與 current ArtifactPublisher 相容的 independent verifier。

驗：

```text
artifact root fingerprint
safe relative path
exists
regular file
ZIP package
[Content_Types].xml
word/document.xml
no traversal member
testzip()
actual sha256
persisted sha256
```

再 copy verified artifact 到：

```text
<e2e_run_id>/artifacts/<run_item_id>.docx
```

## Tests

用 temporary ZIP fixture 測：

- good docx
- invalid zip
- missing document.xml
- corrupt zip member
- `../evil`
- absolute zip member
- artifact_relative_path traversal
- SHA mismatch
- output-root fingerprint mismatch
- identical valid artifact pass

不得使用 production output 做 destructive test。

---

# 9. Task 7 — Runtime Worker Verification and Safe Diagnostics

## Worker checks

參照 current launcher identity contract：

```text
.run_sra_api_launcher.identity
.run_sra_api_schedule.identity
.run_sra_api_handoff.identity
```

驗：

- regular file
- not symlink
- expected owner
- expected mode where current launcher requires it
- PID numeric
- `/proc/<pid>` alive
- process start time matches identity
- cwd matches project root
- command corresponds to schedule-worker / handoff-worker

僅 read。

不得 signal process。

## Diagnostics

failure-only：

```text
SRA-API_output.txt
SRA-ScheduleWorker_output.txt
SRA-HandoffWorker_output.txt
```

bounded tail → redact → diagnostics JSON。

## Tests

- stale PID
- PID reused / start time mismatch
- wrong cwd
- wrong command
- symlink identity file
- missing worker
- healthy worker
- logs containing synthetic secrets → output contains no secret

---

# 10. Task 8 — CLI, Result Schema and Cleanup Contract

## CLI

Required:

```bash
python operator_e2e/test_requirement_schedule_e2e.py \
  --excel <path>
```

Optional:

```text
--output-dir
--env-file
```

Do not add dozens of operational flags for production internals。

## Result files

Always attempt:

```text
result.json
summary.txt
diagnostics.json
```

Even on failure。

## Cleanup

`finally` block：

```text
if this invocation enabled verified E2E schedule:
    disable schedule via existing API
```

Do not delete durable historical state。

## Exit tests

Assert:

```text
PASS                         -> 0
config/auth/input            -> 2
E2E chain failure            -> 3
internal/evidence failure    -> 4
cleanup failure              -> 5
```

---

# 11. Task 9 — Operator Documentation

Create:

```text
docs/operations/requirement-automatic-operator-e2e.md
```

文件只描述 operator workflow：

```text
prepare e2e.env.local
prepare 3-item XLSX
run one Python command
read summary
inspect diagnostics if failed
```

加入：

- required env variables
- sample invocation
- stage meanings
- output paths
- exit codes
- offline behavior
- explicit manual-run prohibition
- failure handling
- no SQL repair policy

不把 curl/SQL 變成正常操作步驟。

---

# 12. Task 10 — Git Hygiene

加入：

```text
operator_e2e/output/requirement_e2e/
```

至 `.gitignore`。

不得 commit：

- test credentials
- live DOCX output
- result.json from real deployment
- runtime logs
- service key

---

# 13. Required Test Gate

Implementation completion 前至少執行：

```bash
pytest -q tests/test_requirement_operator_e2e_harness.py
```

以及：

```bash
pytest -q \
  tests/test_requirement_api.py \
  tests/test_requirement_import_service.py \
  tests/test_requirement_schedule_api.py \
  tests/test_requirement_schedule_store.py \
  tests/test_requirement_schedule_worker.py \
  tests/test_requirement_handoff_prepare.py \
  tests/test_requirement_handoff_submit.py \
  tests/test_requirement_handoff_reconciliation.py \
  tests/test_requirement_handoff_completion.py \
  tests/test_requirement_handoff_artifacts.py \
  tests/test_requirement_report_job_gateway.py \
  tests/test_run_sra_api_launcher.py
```

---

# 14. Live Acceptance Policy

Codex implementation completion **不等於 deployment live PASS**。

真正 live PASS 只能來自部署環境實際執行：

```bash
python operator_e2e/test_requirement_schedule_e2e.py \
  --excel operator_e2e/input/requirement_e2e_3items.xlsx
```

並得到：

```text
REQUIREMENT_E2E = PASS
```

---

# 15. Completion Report Contract

Codex 完成時必須回報：

```text
Hosted base SHA
Branch
Candidate HEAD SHA
PR URL/number

Changed files
Behavior implemented
Tests added
Exact test commands
Exact results

Production-side changes
Harness-only changes

Any deviations from Design v1
Any deviations from Plan v1
Remaining risks

Live E2E executed? YES/NO
If NO: explicitly state NO FRESH LIVE PASS
```

不得把 local SHA 說成 hosted authority。

不得自行 merge PR。
