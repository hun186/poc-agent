# SRAF N 輪 Job：SQLite 持久化中斷保護（離線安全邊界）

## 本輪實作

新增 agent/adaptive_retrieval/job_checkpoint.py，提供 NroundCheckpointStore。
它建立獨立的 sraf_nround_checkpoints 資料表，可和既有 report_jobs 共用一個 SQLite 檔案，但不更動舊表欄位、索引或 user_version。

流程為 create（排隊）→ claim（單 Worker 原子領取租約）→ record_progress（只保存協調器既定欄位的數字／狀態代碼）→ RETRIEVAL_STOPPED。租約 Token 只交給呼叫者，資料庫只儲存 SHA-256。重複 Job ID、第二個 Worker、錯誤 Token、狀態回退、超出輪數與跳號都會拒絕。

Worker 意外中斷後，僅能在 **單機且確定舊 Worker 已停止** 的情況下呼叫 interrupt_running()，把仍在 RUNNING 的作業改為 INTERRUPTED 並讓舊租約失效。不可將其視為已完成或自動重跑；目前不支援 checkpoint resume。

若協調器在第一輪開始前就被取消，或首次預算准入遭拒，允許 round=0、已完成輪次=0 的 TERMINAL 進度；仍禁止視為完成檢索或獲得 Word 生成權限。

record_progress 接收 AdaptiveRequestCoordinator.safe_progress() 的固定格式，嚴格驗證整數、輪次、Evidence 累計、狀態代碼與稽核欄位。資料庫不保存原始提問、關鍵詞、來源 ID、文章片段、雜湊或 exception 字串。get_public 固定回報 checkpoint_resume_supported=false 及 report_generation_authorized=false。

## 重要限制

- **尚未接正式 API／ReportJobWorker，既有單輪報告流程不變。**
- 無 ES、LLM、SQL Server、OpenWebUI 或 Word 實機工作；不能宣稱驗證 PIT／分頁完整性、RBAC、品質評估或 SDK timeout。
- RETRIEVAL_STOPPED 不是 Report Job COMPLETED。正式 Worker 仍須另行驗證 Evidence、Job owner、Word artifact 與下載權限。
- 這是單機 SQLite 防重入契約，不是跨主機租約服務，也不能在舊 Worker 仍在執行時直接清理它的租約。
- 後續整合需確保舊 Worker 停止、授權綁定、持久化產物、ES 限時與雙 Word 連結。

## 離線驗收

tests/test_sraf_nround_checkpoint.py 驗證併發領取、重啟中斷、不允許續跑、非法 Token／隱私資料／狀態倒退拒絕、無效 Job ID、原有 report_jobs 表不變，以及既有不相容資料表拒絕覆蓋。專用 CI 在 Python 3.10／3.11 運行，但不等同 Linux 實機驗收。
