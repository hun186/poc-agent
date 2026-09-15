# Requirement Automatic Operator E2E Harness Design v1

## 1. Document Control

**Repository:** `hun186/poc-agent`  
**Authoritative branch:** hosted GitHub `main`  
**Source baseline:** `4fd6f1adad66c3cfc20a91ad556c6da7e8a2da9b`  
**Design version:** v1  
**Status:** PROPOSED / FOR REVIEW  
**Date:** 2026-09-15

本 Design 僅針對 **Requirement Automatic Operator E2E Harness v1**。

不重新設計 Phase 1B Requirement Import、Phase 1C-A Schedule Control Plane、Phase 1C-B Execution Bridge，不重新實作 Golden Path。

---

# 2. Primary Goal

建立一個 operator-facing、可在斷網內網獨立執行的一鍵 Python E2E Harness，使操作人員只需執行一次：

```bash
python operator_e2e/test_requirement_schedule_e2e.py \
  --excel operator_e2e/input/requirement_e2e_3items.xlsx
```

就可以判定：

> Excel Requirement Import  
> → Snapshot  
> → automatic Schedule  
> → real schedule-worker claim  
> → Handoff  
> → Report Jobs  
> → Agent / Elasticsearch / LLM  
> → DOCX  
> → reconciliation  
> → completed

整條技術鏈是否正常，以及失敗停在哪一層。

**HTTP 200 絕對不等於 PASS。**

PASS 必須建立在 durable state、identity、terminal state、artifact integrity 與 SHA256 evidence 上。

---

# 3. Current Source Findings

## 3.1 Existing architecture remains suitable

Current `main` 仍由 API lifespan 建立 Requirement Import Service、Schedule Service 與 Report Job Worker；Requirement Schedule Worker 與 Handoff Worker 則由 `run_sra_api.sh` 作為獨立 process 監督。

因此 Harness 不應再建立 worker，也不應把 worker logic embed 進 E2E script。

Harness 的角色是：

**stimulate + observe + verify + diagnose**

而不是：

**execute production workflow on behalf of production workers**。

## 3.2 Manual Run API exists

Current Schedule API 同時提供正常 schedule lifecycle 與 manual Run endpoint。

因此 Harness 必須有明確 invariant：

> **永遠不得 POST manual Run endpoint。**

也不得執行：

```bash
python -m requirement_scheduler schedule-worker --once
```

否則就不能證明 production schedule-worker automation 正常。

## 3.3 Existing durable evidence is already strong enough

Current schedule schema 已保存：

- Batch `snapshot_id`
- `scheduled_for`
- `trigger_type`
- selected/success/failure counts
- Run Item execution state
- `remote_job_id`
- `remote_job_state`
- artifact relative path
- artifact SHA256
- artifact reconciliation timestamp

Current schema version為 **3**。

Handoff completion 邏輯只有在 remote completed、artifact evidence durable、SHA/path recorded 後才允許 Run Item close 成 `completed`。

因此新 Harness **不需要創造第二套 execution truth**。

## 3.4 Required minimal evidence projection

Current `get_batch_run()` API projection 尚未回傳所有上述 durable fields；尤其缺少：

- Batch:
  - `snapshot_id`
  - `phase1a_output_root_fingerprint`
- Run Item:
  - `remote_job_id`
  - `remote_job_state`

但這些欄位已存在 durable schema。

因此 v1 唯一建議的 production-side change 是：

> **將這四個既有 durable fields 加入 existing Batch Run GET projection。**

不新增 table。

不新增 column。

不新增 write endpoint。

不新增 repair endpoint。

不改 Handoff semantics。

不改 Report Job ownership。

這是 read-only observability enhancement。

---

# 4. Harness Architecture

建議結構：

```text
operator_e2e/
├── test_requirement_schedule_e2e.py
├── requirement_e2e_support.py
├── requirement_e2e_profile_v1.json
├── input/
│   └── requirement_e2e_3items.xlsx
└── output/
    └── requirement_e2e/
        └── <e2e_run_id>/
            ├── result.json
            ├── summary.txt
            ├── diagnostics.json
            └── artifacts/
                ├── <run_item_id-1>.docx
                ├── <run_item_id-2>.docx
                └── <run_item_id-3>.docx
```

`test_requirement_schedule_e2e.py` 是唯一 operator entry point。

`requirement_e2e_support.py` 僅放：

- safe HTTP helper
- bounded retry
- polling
- evidence/result model
- fixture matching
- redaction
- DOCX validation
- process/read-only runtime checks

不得把 Requirement production business logic 複製進 support module。

---

# 5. Runtime Model

v1 定義為：

> **Deployment-host E2E Harness**

也就是 Harness 預期從實際執行 `run_sra_api.sh` 的 Linux deployment host 執行。

原因是它要同時驗證：

- API HTTP
- schedule-worker process
- handoff-worker process
- local published DOCX
- launcher runtime logs

Current launcher 已維護 launcher/API/schedule/handoff identity records，並驗證 PID、process start time、UID、cwd 與 process command。

Harness 可以 **read-only** 使用相同 evidence 判斷 worker 是否 alive。

Harness：

- 不 kill process
- 不 restart process
- 不修改 identity file
- 不修改 launcher
- 不讀 generated credential state contents

---

# 6. Configuration / Credential Contract

沿用 existing Phase 0 operator pattern：

```text
operator_e2e/e2e.env.local
```

該檔已被 `.gitignore` 排除。

其中只允許：

```text
SRA_E2E_*
```

Harness 不得接受 e2e.env.local 中其他 prefix。

## Required

以下兩種 authentication mode 二選一：

```text
SRA_E2E_EDITOR_USERNAME
SRA_E2E_EDITOR_PASSWORD
```

或：

```text
SRA_E2E_EDITOR_TOKEN
```

另外：

```text
SRA_E2E_MODEL
SRA_E2E_REQUIREMENT_ARTIFACT_ROOT
```

Requirement/Schedule lifecycle 需要足以建立、approve、enable fixture 的權限；v1 acceptance credential 預期為 `superuser`。

## Optional

```text
SRA_E2E_BASE_URL=http://127.0.0.1:9002

SRA_E2E_OUTPUT_DIR=operator_e2e/output/requirement_e2e

SRA_E2E_PROFILE_NAME=SRA Requirement Operator E2E Profile v1
SRA_E2E_SOURCE_NAME=SRA Requirement Operator E2E Source v1
SRA_E2E_SCHEDULE_NAME=SRA Requirement Operator E2E Schedule v1

SRA_E2E_AUTO_CLAIM_TIMEOUT_SECONDS
SRA_E2E_HANDOFF_TIMEOUT_SECONDS
SRA_E2E_REMOTE_TIMEOUT_SECONDS
SRA_E2E_RECONCILE_TIMEOUT_SECONDS

SRA_E2E_EXPECTED_SOURCE_SHA

SRA_E2E_API_LOG_PATH
SRA_E2E_SCHEDULE_LOG_PATH
SRA_E2E_HANDOFF_LOG_PATH
```

禁止要求 operator 提供：

- SQL connection string
- Handoff Service Key
- Report Job Service Key
- signing secret
- credential-store contents

Harness 不需要這些 secret。

---

# 7. Fixture Contract

## 7.1 Stable fixture objects, unique execution data

E2E 不應每次建立無限多個 Profile/Source/Schedule shell。

採：

**stable fixture + unique execution**

Stable：

- dedicated Profile
- dedicated Source
- dedicated Schedule

Per-run unique：

- `e2e_run_id`
- Import Run
- Snapshot
- Schedule Version
- `next_run_at`
- scheduled Batch Run
- Run Items
- Report Jobs
- published artifacts
- result directory

## 7.2 Profile fixture

使用 tracked：

```text
operator_e2e/requirement_e2e_profile_v1.json
```

Profile contract 採 canonical XLSX 欄位：

```text
external_item_id
title
prompt_content
source_updated_at
source_created_at
expires_at
```

其中前五項為 current Requirement canonical required fields。

Profile：

- format = `xlsx`
- source mode = `authoritative_snapshot`
- source timezone = `UTC`
- header row = 1
- first data row = 2
- worksheet = active worksheet unless fixture explicitly pins sheet

Current XLSX reader 使用 existing `openpyxl` implementation；Harness 不另寫 XLSX parser。

## 7.3 Create vs reuse rule

### Object absent

建立新的 E2E fixture。

### Exactly one fixture exists and fingerprint/config matches

安全 reuse。

### Partial previous creation

例如：

- Profile 存在
- expected Profile Version 存在但仍 draft

可以在確認：

- exact E2E name
- exact expected configuration fingerprint
- exactly one matching object

之後完成正常 API lifecycle。

### Existing fixture differs

FAIL：

```text
FIXTURE_DRIFT
```

不得自動 patch 成期待值。

### Multiple ambiguous matches

FAIL：

```text
FIXTURE_AMBIGUOUS
```

不得「猜一個」。

---

# 8. Input Excel Rules

Harness 開始前先做 local sanity validation：

- regular file
- extension `.xlsx`
- readable
- non-zero
- SHA256 可計算
- XLSX package/openpyxl 可開啟

真正的 Requirement semantic validation 仍由 production Preview API 決定。

Preview 必須：

```text
has_errors = false
accepted_count = 3
rejected_count = 0
```

Import 後再從 Snapshot Items 驗證：

```text
item_count = 3
```

且三筆：

```text
expires_at is NULL
OR
expires_at > current acceptance time
```

因此「3 active items」由 durable imported snapshot 驗證，而不是只相信 workbook row count。

---

# 9. Re-run / Idempotency Strategy

同一份 Excel 可以重複跑。

Requirement Import current transaction 對相同 Requirement content 可以 reuse Requirement Version，但每次成功 commit 仍會產生新的 Import Run 與 Snapshot。

因此不需要每次竄改 `external_item_id`。

這反而讓 E2E fixture穩定。

每次 invocation 的 execution identity 由：

```text
e2e_run_id
snapshot_id
schedule_version_id
scheduled_for
batch_run_id
run_item_id
remote_job_id
```

共同建立。

---

# 10. Concurrency Protection

Harness 啟動時對：

```text
operator_e2e/output/requirement_e2e/.lock
```

取得 non-blocking local exclusive lock。

已有另一個 Harness 正在跑：

```text
CONFIG_PREFLIGHT = FAIL
failure_category = concurrent_e2e_run
```

不等待、不搶 fixture。

即使有人從其他主機同時修改 E2E Source，後面的：

```text
batch.snapshot_id == this_run.snapshot_id
```

仍會偵測 contamination。

---

# 11. Requirement Import Identity

成功 Import 後 Harness 必須取得：

```text
import_run_id
snapshot_id
requirement_set_id
```

再確認：

```text
Requirement Set.active_snapshot_id == snapshot_id
```

並確認 Snapshot Items exactly 3。

這個 `snapshot_id` 是本次 execution chain 的第一個 durable correlation key。

---

# 12. Schedule Fixture Strategy

Schedule shell stable reuse。

**每一次 E2E invocation 必須建立新的 immutable Schedule Version。**

原因：

- recurrence time 每次不同
- 可明確 correlation 到這次 execution
- 不污染以前 version
- 不修改歷史 version

RunPolicy 固定：

```text
all_active
```

Model：

```text
SRA_E2E_MODEL
```

Timezone：

```text
UTC
```

---

# 13. Schedule Timing Design

Current recurrence 支援 interval，最小 interval 是 1 minute，`anchor_at` 必須 timezone-aware 且 second precision。

但 E2E 不應建立「每分鐘永久跑一次」的 schedule。

因此採：

```json
{
  "kind": "interval",
  "every": 10080,
  "unit": "minutes",
  "anchor_at": "<UTC now + lead time>"
}
```

`10080 minutes = 7 days`

預設：

```text
anchor lead = 120 seconds
```

效果：

- 第一次 occurrence 約 2 分鐘後
- 即使 schedule-worker 晚幾十秒 claim，仍是同一 occurrence
- claim 完之後下一次是 7 天後
- 即使 Harness crash，短時間內也不會每分鐘再產生新 Report Jobs

Approve + Enable 後以 **API 回傳的 `next_run_at` 為 authority**。

Harness 必須檢查：

```text
now < next_run_at <= now + allowed_near_future_window
```

若因操作過慢導致第一個 anchor 已錯過、`next_run_at` 跳到一週後：

```text
SCHEDULE_ENABLE = FAIL
failure_category = next_run_at_out_of_window
```

立刻 disable schedule。

不等待一週。

---

# 14. Proving Automatic Scheduling

Enable 前：

```text
baseline_batch_run_ids = GET existing runs
```

然後：

**只 poll read APIs。**

不得：

```text
POST /runs
```

不得：

```text
schedule-worker --once
```

不得：

```text
coordinator.run_once()
```

AUTO_CLAIM PASS 必須出現新的 Batch Run 且：

```text
batch_run_id not in baseline_batch_run_ids
trigger_type == "scheduled"
schedule_version_id == this_run.schedule_version_id
scheduled_for == captured_initial_next_run_at
snapshot_id == this_run.snapshot_id
```

而且：

```text
new_matching_scheduled_runs == 1
```

若 0：

```text
automatic_claim_timeout
```

若 >1：

```text
multiple_scheduled_runs
```

若 Snapshot 不同：

```text
snapshot_identity_mismatch
```

---

# 15. Proving next_run_at Advancement

偵測到 scheduled Batch 後，重新 GET Schedule。

在 disable 之前必須證明：

```text
advanced_next_run_at > initial_next_run_at
```

且對本 E2E interval：

```text
advanced_next_run_at
==
scheduled_for + 10080 minutes
```

PASS 後立即透過正常 Schedule API：

```text
enabled = false
```

---

# 16. Run Selection

Batch 必須：

```text
trigger_type = scheduled
selected_count = 3
skipped_count = 0
snapshot_id = expected snapshot_id
```

三個 items 必須：

```text
selection_status = selected
```

並且 `requirement_id` 集合等於本次 Snapshot Items 的 requirement IDs。

---

# 17. Handoff / Report Job Identity

Handoff ACK durable 記錄 `remote_job_id`，並以 Run Item identity 保護 reconciliation。

因此加入 read-only projection 後：

HANDOFF PASS：

```text
3/3 selected run items:
  dispatched_at != null
  remote_job_id != null
```

REPORT_JOBS PASS：

```text
count(unique remote_job_id) == 3
```

而且這三個 ID 必須直接來自：

```text
this batch_run_id
  -> this run_item_id
  -> durable remote_job_id
```

不得以：

- 建立時間相近
- log 字串
- Report Job list 的最後三筆

來猜是哪三個 Job。

---

# 18. Remote Job Polling

Harness 本身不冒充 Handoff worker 的 service principal。

Handoff Gateway 已使用 production credential 建立/查詢 owner-scoped Report Jobs，並將狀態 reconcile 回 Run Item。

因此 v1 的 operator Harness poll：

```text
Batch Run GET
```

觀察 durable：

```text
remote_job_id
remote_job_state
execution_state
```

即可。

terminal acceptance 必須為：

```text
remote_job_state = completed
execution_state = completed
```

三筆全部成立。

---

# 19. Embedded Report Job Worker Readiness

Report Job Worker 由 API lifespan 啟動，current source 沒有獨立 operator-facing health endpoint。

因此 v1：

- API process readiness 可在 preflight 驗
- schedule-worker / handoff-worker 可由 launcher identity 驗
- Report Job Worker 不創造假的 health 判斷

它的 functional readiness 最終由：

```text
remote_job_id created
→ remote state progresses
→ completed
```

來證明。

---

# 20. Artifact Verification

ArtifactPublisher current production contract 已執行：

- DOCX ZIP validation
- `[Content_Types].xml`
- `word/document.xml`
- ZIP path traversal rejection
- `ZipFile.testzip()`
- SHA256
- output-root fingerprint
- idempotent publication

Harness 要獨立 verify evidence，但不重新定義 publication semantics。

對每個 completed Run Item：

1. `artifact_relative_path` 非空
2. `artifact_sha256` 為 64 lowercase hex
3. Batch `phase1a_output_root_fingerprint` 與 configured artifact root 計算值相同
4. safe resolve 必須仍在 artifact root 下
5. file exists
6. ZIP readable
7. 包含 `[Content_Types].xml` 與 `word/document.xml`
8. 無 absolute / traversal member
9. `testzip()` clean
10. actual SHA256 == persisted `artifact_sha256`

成功後將 verified bytes copy 到：

```text
<e2e_run_id>/artifacts/<run_item_id>.docx
```

Evidence copy 不取代 production artifact。

---

# 21. Polling / Timeout Layers

建議 defaults：

```text
API readiness              30 s
normal HTTP request        connect 5 s / read 30 s
upload / preview           60 s
automatic claim            initial next_run_at + 90 s grace
handoff / remote_job_id    120 s
remote Agent/ES/LLM        1800 s
artifact reconciliation    180 s
cleanup                     30 s
```

Polling：

```text
initial 1 s
normal 2 s
cap 5 s
```

---

# 22. Retry Rules

## Safe reads

GET 可以 bounded retry：

- connection failure
- timeout
- 429
- 502
- 503
- 504

## Writes

不得因 timeout 直接 blind retry。

對 ambiguous write：

> durable re-read → identify winner → then decide whether retry is safe

例如 Schedule create timeout 後重新 list exact E2E schedule。

Import Commit timeout 後：

- reread Requirement Set / Snapshots
- match source
- match source SHA256
- match active profile version
- match invocation time window

exactly one durable winner：接受為 committed。

zero：bounded retry。

multiple：`ambiguous_write`。

---

# 23. Failure Stage Taxonomy

每個 Stage：

```text
PASS
FAIL
NOT_REACHED
```

建議 canonical stages：

```text
CONFIG_PREFLIGHT
API_READINESS
AUTH
PIPELINE_READINESS
RUNTIME_WORKERS
INPUT_VALIDATION
FIXTURE_PROFILE
FIXTURE_SOURCE
REQUIREMENT_PREVIEW
REQUIREMENT_IMPORT
SNAPSHOT
REQUIREMENT_ITEMS
SCHEDULE_FIXTURE
SCHEDULE_VERSION
SCHEDULE_APPROVE
SCHEDULE_ENABLE
AUTO_CLAIM
RUN_IDENTITY
RUN_SELECTION
NEXT_RUN_ADVANCE
HANDOFF
REPORT_JOBS
REMOTE_EXECUTION
ARTIFACT_RECONCILIATION
RUN_ITEMS_TERMINAL
BATCH_TERMINAL
DOCX_INTEGRITY
SHA256_MATCH
CLEANUP
FINAL_EVIDENCE
```

代表性 safe failure categories：

```text
configuration_error
api_unreachable
authentication_failed
authorization_failed
pipeline_disabled
scheduler_disabled
worker_unavailable
input_invalid
fixture_ambiguous
fixture_drift
preview_rejected
import_failed
snapshot_identity_mismatch
item_count_mismatch
schedule_config_invalid
next_run_at_out_of_window
automatic_claim_timeout
automatic_claim_identity_mismatch
multiple_scheduled_runs
handoff_timeout
remote_job_identity_missing
remote_job_count_mismatch
remote_execution_failed
remote_execution_timeout
artifact_reconciliation_timeout
artifact_missing
artifact_invalid
artifact_sha256_mismatch
batch_terminal_failure
cleanup_failed
evidence_write_failed
internal_harness_error
```

---

# 24. Failure Diagnostics

失敗時 console 例如：

```text
REQUIREMENT_IMPORT = PASS
SNAPSHOT           = PASS
SCHEDULE           = PASS
AUTO_CLAIM         = FAIL
HANDOFF            = NOT_REACHED
REPORT_JOBS        = NOT_REACHED

FAILED_STAGE = AUTO_CLAIM
FAILURE_CATEGORY = automatic_claim_timeout

REQUIREMENT_E2E = FAIL
```

`diagnostics.json` 可以保留：

- schedule_id
- schedule_version_id
- batch_run_id
- run_item_id
- remote_job_id
- initial next_run_at
- observed next_run_at
- observed states
- timestamps
- attempt counts
- worker PID / verified-alive boolean
- safe log tails

不得保留：

- Authorization header
- Bearer token
- editor password
- Service Key
- SQL password
- DB connection string
- generated credential file content
- complete environment dump
- Requirement prompt content

---

# 25. Safe Log Collection

成功時不收大量 logs。

失敗時最多擷取：

```text
100 lines
AND
64 KiB
```

from：

```text
SRA-API_output.txt
SRA-ScheduleWorker_output.txt
SRA-HandoffWorker_output.txt
```

Redaction 最少涵蓋：

```text
Authorization: Bearer ...
Bearer ...
password=...
token=...
secret=...
service_key=...
connection_string=...
PWD=...
User ID=...
```

把 Harness process memory 中已知 credential literal 全部替換成：

```text
<REDACTED>
```

永遠不要 serialize `os.environ`。

---

# 26. Cleanup Policy

Cleanup 是正常 API cleanup，不是 DB repair。

Always-attempt：

```text
disable exact E2E schedule
```

不得：

- DELETE Requirement rows
- UPDATE SQL manually
- DELETE Snapshot
- reset checkpoint
- rewrite Batch state
- delete Report Job
- rotate credential
- kill worker
- restart API

保留 Import Run、Snapshot、Schedule Version、Batch、Run Items、Report Job identity、production DOCX。

若最後 disable E2E schedule 失敗：

```text
CLEANUP = FAIL
REQUIREMENT_E2E = FAIL
exit code = 5
```

---

# 27. Existing E2E Data Policy

重跑時：

1. 找 exact reserved Profile。
2. 驗 fingerprint。
3. 找 exact reserved Source。
4. 驗 source config/Profile association。
5. 找 exact reserved Schedule。
6. 驗 requirement_set association。
7. 若是 Harness-owned schedule 且因前次 crash 還 enabled，先正常 API disable。
8. 不刪舊 versions/runs/snapshots。
9. 建立本次新 Snapshot。
10. 建立本次新 Schedule Version。

如果 existing object 的 ownership/config 無法證明：

```text
FAIL CLOSED
```

---

# 28. Evidence Output Schema

`result.json`：

```json
{
  "schema_version": "requirement_e2e_result_v1",
  "e2e_run_id": "20260915T101530Z-a1b2c3d4",
  "started_at": "...",
  "finished_at": "...",
  "duration_seconds": 0,
  "source": {
    "repository": "hun186/poc-agent",
    "design_baseline": "4fd6f1adad66c3cfc20a91ad556c6da7e8a2da9b",
    "expected_runtime_sha": null,
    "local_git_sha": null,
    "local_git_dirty": null
  },
  "overall_status": "PASS",
  "exit_code": 0,
  "failed_stage": null,
  "failure_category": null,
  "input": {
    "path": "...",
    "sha256": "...",
    "size_bytes": 0
  },
  "fixtures": {
    "profile_id": "...",
    "profile_version_id": "...",
    "source_id": "...",
    "requirement_set_id": "...",
    "schedule_id": "...",
    "schedule_version_id": "..."
  },
  "requirement_import": {
    "import_run_id": "...",
    "snapshot_id": "...",
    "accepted_count": 3,
    "rejected_count": 0
  },
  "schedule": {
    "initial_next_run_at": "...",
    "scheduled_for": "...",
    "advanced_next_run_at": "...",
    "trigger_type": "scheduled"
  },
  "batch": {
    "batch_run_id": "...",
    "snapshot_id": "...",
    "state": "completed",
    "selected_count": 3,
    "skipped_count": 0,
    "success_count": 3,
    "failure_count": 0
  },
  "items": [],
  "stages": [],
  "artifacts": [],
  "warnings": []
}
```

不得把 response headers、token、prompt、source_raw 放入 result。

---

# 29. Exit Code Contract

```text
0 = PASS
2 = PRECHECK / CONFIG / AUTH / INPUT failure
3 = E2E functional chain failure or timeout
4 = Harness internal / evidence-write failure
5 = Cleanup safety failure
```

任何 FAIL / partial success 都不得 exit 0。

---

# 30. Console Contract

成功：

```text
PREFLIGHT          = PASS
REQUIREMENT_IMPORT = PASS
SNAPSHOT           = PASS
SCHEDULE           = PASS
AUTO_CLAIM         = PASS
HANDOFF            = PASS
REPORT_JOBS        = PASS
DOCX               = PASS

ITEMS = 3/3 COMPLETED

REQUIREMENT_E2E = PASS
```

失敗：

```text
FAILED_STAGE = AUTO_CLAIM
FAILURE_CATEGORY = automatic_claim_timeout

REQUIREMENT_E2E = FAIL
```

---

# 31. Final PASS Contract

`REQUIREMENT_E2E = PASS` 只有在以下全部成立時才能輸出：

1. API reachable。
2. authenticated operator authority verified。
3. Requirement Pipeline available。
4. Scheduler API available。
5. schedule-worker verified alive。
6. handoff-worker verified alive。
7. Excel valid。
8. Preview accepted exactly 3。
9. Import committed。
10. exact new Snapshot identified。
11. Snapshot exactly 3 active items。
12. E2E Schedule Version approved/enabled。
13. `next_run_at` valid。
14. real schedule-worker produced exactly one matching scheduled Batch。
15. 沒有 manual run。
16. Batch uses exact this-run Snapshot。
17. selected_count = 3。
18. 3 selected Run Items。
19. 3 unique durable `remote_job_id`。
20. 3 remote jobs complete。
21. 3 Run Items complete。
22. Batch complete。
23. success_count = 3。
24. failure_count = 0。
25. next_run_at correctly advanced。
26. schedule safely disabled。
27. 3 production DOCX exist。
28. 3 DOCX ZIP integrity valid。
29. 3 actual SHA256 == durable SHA256。
30. result/summary/diagnostics evidence successfully persisted。

---

# 32. Explicit Non-Goals

v1 不做：

- LangGraph
- JT-1
- Task/Attempt/Event Store
- Requirement Task Center
- OpenWebUI UI
- new orchestration framework
- Phase 1B redesign
- Phase 1C redesign
- Agent redesign
- Report Job redesign
- SQL repair
- deployment manifest
- robocopy verification
- SD-1～SD-7
- package provenance redesign
- external internet dependency

---

# 33. Source-Bound Design Conclusion

Current main 的核心 execution chain 已存在。

Requirement Automatic Operator E2E Harness v1 應採：

> **薄 Harness + 強 durable evidence + 最小 read-only API projection**

而不是：

> 新增另一套 scheduler / handoff / Report Job execution logic。

這樣才能真正回答 operator 最需要的問題：

> **「Excel 要項＋自動排程＋Handoff＋Report Job＋DOCX，現在到底通不通？如果不通，是壞在哪一層？」**
