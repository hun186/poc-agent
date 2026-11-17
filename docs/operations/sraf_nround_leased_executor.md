# SRAF N 輪｜既有 Report Job 的租約式執行器整合（隔離階段）

## 實作邊界

本版 `sra_api/services/sraf_nround_leased_executor.py` 是**可信背景 Worker
未來可以直接呼叫的同步整合助手**，仍**沒有**接到正式
`ReportJobWorker`、任何 HTTP/OpenWebUI 路由或 Word 產製器。

輸入只能由伺服器信任邊界提供，包含：
- `ReportJobStore.claim_next()` 真正返回且仍 running/agent_execution 的
  `ReportJob`，不可由使用者參數、LLM 輸出或重新建構的假 Job 取代；
- 同一 SQLite 檔案上的 `NroundCheckpointStore`，且同 Job 必須事先
  由可信 admission 建立 **QUEUED** checkpoint。執行器不建立第二隊列；
- 不可被模型輸出冒充的真實 per-index owner RBAC 與原始問題單一查詢
  分支政策，以及可信原始問題、QueryConstraints 和 canonical Evidence；
- 可信 ES client 與獨立語意評估器。離線測試的假 callback
  **不是**正式 RBAC/LLM 接線或功能驗收。

## 執行序

1. 使用 `PersistedClaimedNroundJobScope` 重新讀取 SQLite 真實 Job
   owner/session/prompt/metadata 等身分，建立每個 PIT 前後重驗的 binding。
2. 用 `claim_for_running_report_job()` 在同一個 `BEGIN IMMEDIATE`
   中核對正式 Job 和 sidecar QUEUED→RUNNING，只領一次 SHA256 租約。
3. 將 `record_progress_for_running_report_job()` 注入既有
   `run_trusted_nround(..., checkpoint_sink=...)`，只有必要的原子進度
   **成功**提交，才可開始下一個昂貴階段／下一輪 ES。
4. 正常結束後讀回固定 `RETRIEVAL_STOPPED/TERMINAL`、
   相同終止原因與已完成輪數；僅回傳**內部**檢索結果與數字診斷。
5. 任一階段失敗、拒絕或私人例外：對外只顯示
   `claimed_nround_execution_denied`，撤銷記憶體報告就緒狀態，
   並僅以此 Job 的租約呼叫 `fail_owned_lease()`。若 DB 無法確認
   cleanup，**不可假稱成功**，也不可跨 Job 清除或自動重跑；
   原有重啟 interrupt 行為仍是獨立程序。

## 未授權與尚未完成

- **不**呼叫 `claim_next()`；不將單輪 Worker 改成多輪 Worker。
- **不**呼叫正式 ES/LLM，除非未來受信任 Worker 明確使用本入口提供
  對應 client。N 輪預設 OFF，沒有新 flag/API/帳號權限路由。
- **不**標記正式 Report Job completed，不呼叫 Word 產製，
  `report_generation_authorized` 一律為 False，
  不提供第二份 Word 或下載權限。
- 即使 sidecar 已持久化為 SUFFICIENT，也不能取代
  「N 輪證據→Word 產製」的獨立正式 Job/Artifact CAS。
- 同機 SQLite CAS 不能中斷已在途 ES/LLM 連線，也不是跨主機 HA、
  30 分鐘硬超時、復原續跑或正式 RBAC 證明。
- 正式 owner-index policy、原始問題/多分支證明、單輪完成後分流
  Job admission、真正服務 Worker 串接、取消/超時、DOCX、OpenWebUI
  雙載點交付與私有 Linux ES/LLM/DOCX E2E 均屬後續門檻。

## 離線驗證

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_leased_executor.py \
  tests/test_sraf_nround_safe_progress_sink.py \
  tests/test_sraf_nround_reportjob_atomic_checkpoint.py \
  tests/test_sraf_nround_fail_owned_lease.py \
  tests/test_sraf_nround_persisted_claimed_job_scope.py
```

測試真實使用**臨時 SQLite 檔案**、合成 ES PIT 與假語意模型，包含：
兩輪成功與進度終止、Owner RBAC 拒絕在首個 PIT 前停止、
正式 Job 在 PIT 中失效、語意模型錯誤、sidecar 已取消不能重新領取、
ReportJob schema 漂移、SQLite 調查失敗後撤銷記憶體就緒，
以及跨 SQLite 檔案禁止租約。這些是 Hosted 離線驗證，
**不是**私有 Linux、正式 ES、LLM 或 Word 功能驗收。
