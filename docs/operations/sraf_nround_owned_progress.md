# SRAF N 輪｜所有者限定的唯讀進度檢視（內部橋接）

新增 `sra_api/services/sraf_nround_owned_progress.py`：
`get_owned_nround_progress(...)` 可以為未來的 Report Job
狀態頁、OpenWebUI 使用者進度檢視，提供**無證據內容的計數型資料**。

## 讀取授權與範圍

- 呼叫端必須先以**真正的** HTTP/API 認證、`REPORT_JOB_READ`
  權限取得 canonical `owner_kind` / `owner_id`。
  本函式**不驗證 API Key、不接收使用者冒充的 owner 作為授權**；
  目前尚未掛到任何路由。
- `ReportJobStore` 與 `NroundCheckpointStore` 必須位於
  **同一個 SQLite 檔案**；以 SQLite `mode=ro` 打開，
  不得因狀態查詢新建 DB、sidecar、Job 或修改狀態。
- SQLite `mode=ro` 與 `PRAGMA query_only=ON` 禁止建立正式
  資料庫檔案、修改 Report Job／checkpoint／schema，但**SQLite
  WAL 的正常讀取可能會建立或維護 `-wal`、`-shm` 輔助檔案**；
  這些是 SQLite 內部交易／共享記憶體協調檔，不是新的業務資料。
  為了保證讀到尚未 checkpoint 的**最新授權與 Job 狀態**，不能
  使用 `immutable=1`：它可能忽略 WAL 中剛撤銷的 owner 權限。
  本服務目前不保證磁碟上「完全零檔案變動」，只保證
  **沒有 SQL 寫入或建立主資料庫／sidecar 資料表**。
  若未來環境要求連 SQLite 內部檔都不得產生，必須改由可信
  持久化連線管理器持有資料庫生命週期並提供一致讀取快照，
  不能靠探測有無 WAL 檔案來解決併發關閉競爭。
- 同一份 read transaction 下先驗證既有
  `report_jobs` canonical schema v2 與 sidecar schema，
  再以 `job_id + owner_kind + owner_id` 查正式 Job，
  成功才讀取同一 Job 的 N 輪側錄。
- 未知、不屬於目前 owner、舊式無 owner 或沒有 N 輪 sidecar：
  統一回傳 `None`，讓未來 API 以同樣的 404 模型處理；
  不會公開查詢是否真的存在其他人的 Job。
- 成功回傳允許清單：main Job `status`、sidecar
  `state/phase/round_number/completed_rounds/es_calls_this_round/
  termination/revision`，並固定
  `checkpoint_resume_supported=False`、
  `report_generation_authorized=False`、
  `word_download_authorized=False`。
  **不包含** Job ID、owner/session、問題文字、index、Event、
  Evidence、lease token、私人路徑、錯誤堆疊與原始 Provider 資料。
- Report Job 已 failed 但 N 輪側錄仍顯示 RUNNING 時，
  如實分別顯示兩者不同來源的狀態，**不假稱已成功或仍授權工作**。
  這個服務不會幫其他 Job 做全域中斷，也不做 resume。

## 尚未完成

- 此 PR 不修改 `ReportJobWorker`、Word 產製或原始單輪 API，
  不提供新的 `GET` route，也**沒有**正式 OpenWebUI UI。
- 未來狀態路由仍須接到現有 owner/principal、API
  `REPORT_JOB_READ` 授權模型，驗證權限撤銷與 404 隔離；
  SQLite 同一交易的 owner 狀態讀取只是必要條件，不是完整 RBAC。
- 沒有實機 Linux／SQL Server／ES／LLM／DOCX 驗收，沒有任何
  Word 下載或生成權限，也不啟用 N 輪。

## 離線測試

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_owned_progress.py
```

以真正臨時 SQLite 覆蓋本帳號可見、不同 owner 不可見、
跨檔案拒絕、無 sidecar 不新增業務資料、WAL 未 checkpoint 的 owner 撤銷、仍在 RUNNING 的 sidecar
與已 FAILED 的原 Job 分開呈現、schema 漂移拒絕、私人 SQLite
路徑遮蔽。CI 使用 Python3.10/3.11；合成 PASS 不代表正式部署。
