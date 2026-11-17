# SRAF N 輪｜正式 Report Job 與 SQLite checkpoint 原子租約（隔離階段）

## 本 PR 的改進

既有 \`NroundCheckpointStore.claim(job_id)\` 僅檢查 sidecar checkpoint 的
\`QUEUED\` 狀態，尚無法證明正式 Report Job 已經被真正的 Worker
認領、仍屬同一所有者、尚未被中斷，也無法防止 Job 失效後仍寫入
新的 N 輪進度。

新增兩個**明確使用正式 ReportJobStore 的 opt-in 方法**：

- \`claim_for_running_report_job(report_store, claimed_job)\`
- \`record_progress_for_running_report_job(report_store, claimed_job, lease_token, progress)\`

兩個方法要求 \`ReportJobStore.db_path\` 和 sidecar \`db_path\`
指向**同一個 SQLite 資料庫檔案**，並在**同一筆
\`BEGIN IMMEDIATE\` 交易**內：
1. 查詢既有 \`report_jobs\` 真實資料列（不接受單靠傳入的 Job ID），
   驗證 \`status=running\`、\`phase=agent_execution\` 及 immutable
   owner/session/原始 prompt/request hash/已開始時間/模型與
   options、metadata 等欄位與 Worker 認領的 Job 完全一致。
2. 執行 sidecar \`QUEUED → RUNNING\` 的一次性 CAS，
   僅將隨機租約 token 的 SHA-256 寫入 SQLite；沒有合法既有 Job
   或已有人認領的 sidecar，不核發第二份 lease。
3. 寫入每輪計數型進度時重新驗證兩份資料的身分和 hash lease；
   同輪進度不可倒退、不可跳輪、不能重複提交已結束的 checkpoint。
4. N 輪終止原因 \`UNTRACKED_QUERY_ADMISSION\` 可安全寫成
   \`RETRIEVAL_STOPPED\`，但永遠
   \`report_generation_authorized=False\`。**不會因此把 Report Job
   標記為 completed 或讓任何 Word 可下載。**

## 安全界線

- 本 PR 不修改現有 \`report_jobs\` schema 或目前
  \`ReportJobWorker.run/execute\`，沒有新增 HTTP API、Word
  第二個下載連結，也沒有呼叫真實 ES／LLM／SQL。
- 現有不綁定 ReportJob 的 \`claim()\` 與
  \`record_progress()\` 保留供原有隔離測試與相容程式使用；
  **正式 N 輪 Worker 必須改用新增的 owner-bound 方法**。
- 兩份 SQLite 的「同交易核對」比先查 ReportJob、
  再用另一筆交易取得 checkpoint 更嚴格，但也不能取代
  執行期間持續重驗證 Job／ES 權限、
  \`WorkerScopeBinding\`、真正的租戶 RBAC 與 query scope policy。
- 正式 Word 的提交要另外實作獨立的「驗證完畢→報告生成」
  持久化 CAS；目前不能把 \`RETRIEVAL_STOPPED\`
  視為已批准 Word。
- SQLite 結構不符合現行表格定義、跨檔案、尚未認領、
  已失效、owner 變更或 lease 不符：一律拒絕，不回傳
  原始 SQL／使用者資訊；也不自動修復或重跑。
- 目前尚無跨主機分散式 Job claim，本接口只支援單臺主機共用
  SQLite 檔案的同步交易語意；不得據此宣稱多機容錯或正式上線。

## CI（無任何正式服務存取）

\`\`\`bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_checkpoint.py \
  tests/test_sraf_nround_reportjob_atomic_checkpoint.py
\`\`\`

合成驗證涵蓋：正式 Job queued／running／failed／owner 改變、
跨兩個不同 SQLite DB、偽造 Job claim、同一 sidecar 多執行緒
爭搶租約、Job 完成或失敗後不得續寫進度、租約 hash、
服務重啟中斷、未授權 ES 並行終止碼、私人資料不進公開計數摘要。

下一步：提供正式 Worker 可使用的
**N 輪 claim+checkpoint+安全狀態更新的協調接口**，再把實際背景
N 輪檢索和單輪 Word 交付分流設為明確 opt-in；正式使用者 API
必須經過真實 ES/LLM 和 Word 驗收後才可啟用。

## Codex Review 加強項：結構版本與路徑例外拒絕

正式 ReportJob 的權限不能只靠 selected columns 判定，因此新操作必須
在相同 `BEGIN IMMEDIATE` 交易中，先透過正式
`ReportJobStore._validate_v2` 核對 `report_jobs` 欄位、
主鍵／owner 唯一索引、欄位限制及 `PRAGMA user_version=2`，
再允許 sidecar claim 或進度更新。即使狀態與 owner 相符，只要
Schema 漂移（例如版本變成 999、索引消失），就必須拒絕。

跨資料庫檔案、父目錄變成一般檔案、檔案不存在或 SQLite 無法開啟時，
新操作不能將私有磁碟路徑、資料庫名稱或原始例外暴露給呼叫端；
只會提供固定的 `nround_report_job_claim_unverified` 或
`nround_report_job_progress_unverified` 拒絕碼。
