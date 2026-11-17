# SRAF N 輪｜實際持久化 Report Job Claim 身分重驗證（隔離式接線）

## 做了什麼

新增 \`sra_api/services/sraf_nround_claimed_job_scope.py\` 的
\`PersistedClaimedNroundJobScope\`。本次**沒有修改**現有單輪
\`ReportJobWorker\`、Report Job 資料表、API、Word 輸出、既有進度
或下載路由；N 輪尚未在正式使用者介面啟用。

既有 \`WorkerScopeBinding\` 可以檢查請求的 Job 與索引，但傳入的
\`ReportJob\` 是記憶體中的物件，單靠它不能知道 SQLite 裡的 Job
是否已被取消、失敗、服務重啟標記為 \`interrupted\`，或遭到跨帳號
替換。因此現在多一層**真正讀取現有 SQLite ReportJobStore**的
可信橋接，供將來的正式背景 Worker 使用：

1. 只接受可信背景 Worker 從 \`ReportJobStore.claim_next()\` 取得的
   \`running\`、\`agent_execution\` Job；再次 \`store.get(job_id)\`
   必須與已認領物件的 ID、owner kind/ID、session、完整 prompt、
   model、request_hash、idempotency_key、建立及開始時間、
   options/metadata 等固定欄位完全一致。
2. \`make_binding()\` 產生原有的 \`WorkerScopeBinding\`，並將真實
   當前資料庫中的 Job 傳給可信的索引權限 policy 與「原始問題是否
   確實只有 canonical main ES 查詢分支」policy。兩種 policy 必須
   回傳真正的 Boolean \`True\`；不能用文字 \`"true"\`、數字 1、
   例外或模型宣稱取代。
3. **每一輪**在 ES PIT 開啟前及完整 PIT 回執之後，
   \`WorkerScopeBinding.preflight/attest\` 會再觸發上述 store
   重驗證及目前 policy。任何 Job 轉為 failed／cancelled／
   interrupted、owner/session/原始 prompt／request_hash
   改變、權限撤銷或多查詢分支需求都 fail closed，不允許進入
   Evidence 語意處理或下一輪。
4. 診斷 \`safe_audit()\` 只提供固定狀態碼，不暴露 Job ID、
   owner、session、問題原文、日期、索引、回傳 ES 內容或憑證。

## 尚未完成（不可誤稱已上線）

- 橋接**不會自己呼叫** \`claim_next()\`、不能證明傳入 Job 一定是
  目前這個 Worker 親自認領。正式程式必須在伺服器信任邊界中
  領取 Job，再使用此橋接；不可讓 LLM 或 HTTP 用戶端建構
  假 \`ReportJob\`。
- 使用者／租戶 per-index RBAC 和原始問題的多分支語意範圍政策仍
  需要真實正式實作；測試使用獨立假 policy 並不代表已部署政策。
- 事前與事後重驗證無法撤回已在途的 HTTP／ES 請求；
  也無法保證兩次檢查之間不存在競態。正式系統仍應搭配
  可撤銷的 ES 權限、單一 Worker Claim／lease、可靠超時與
  完成前的持久化 Job Fence。
- 未把 N 輪任務接到 \`ReportJobWorker.run/execute\`，
  沒有建立第二份 Word 或可下載 Artifact，也不修改 SQLite schema。
  現有單輪 Job 及使用者介面不受本 PR 影響。

## 合成驗收（不用操作正式 ES／LLM）

在 Linux 完成 Windows→7z 增量部署**後**，若要驗證本 PR：
\`\`\`bash
cd /mntCZJ/TopicClassification/poc-agent
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_persisted_claimed_job_scope.py \
  tests/test_sraf_nround_worker_scope_binding.py \
  tests/test_sraf_nround_trusted_execution_loop.py
\`\`\`

CI 在 Python 3.10／3.11 以**私人臨時 SQLite DB** 和假 ES client
完成完整兩輪與負向驗證，包括：Job 還在 queued、claim 身分偽造、
owner/session/hash 被竄改、服務重啟後 interrupted、ES 執行前失效、
ES 執行期間被標記失敗、權限或多分支政策撤銷及私人資料不洩漏。

下一個整合工作：在獨立、明確 opt-in 的背景 N 輪 Job 路徑中
同時綁定既有 ReportJobStore 與 NroundCheckpointStore 的租約，
且不能讓尚未準備好的條件預設觸發真實 ES 或 LLM。
