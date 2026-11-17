# SRAF N 輪｜單一租約失敗關閉（非正式 Worker）

SRAF N 輪在外部 ES／LLM、原始 Job 權限、SQLite checkpoint 或 Word
前置驗證發生不可恢復的錯誤後，不能繼續將該 checkpoint
留在 `RUNNING`，也不能以全域 `interrupt_running()` 中斷別的 Job。

新增 `NroundCheckpointStore.fail_owned_lease(job_id, lease_token)`，
使用現有 SQLite `BEGIN IMMEDIATE`、只有 SHA-256 的租約比對，
原子執行：

- 僅精確的 `job_id`＋目前活躍且合法的 lease 能將自己從
  `RUNNING` 轉為 `FAILED`，記錄固定終止原因 `CANCELLED`，
  將 phase 轉 `TERMINAL`、lease_hash 清空、revision 加一。
  不儲存失敗例外、私人問題、ES 內容或其他憑證。
- 無效 token、其他 Job 的 token、先前中斷／完成的 checkpoint、
  重複 fail 及已放行 `RETRIEVAL_STOPPED` 均不修改任何資料。
- **即使正式 Report Job 已不在 running**，此針對租約的清理仍可
  拒絕未來的進度寫入；它不需要重驗主 Job 的 running，
  因為原始 Job 的撤銷可能正是本次失敗的原因。
- 公開 `get_public` 仍維持
  `report_generation_authorized=False`，不產生或刪除任何 Word。
- SQLite／檔案系統異常使用固定拒絕碼
  `nround_lease_failure_unverified`，不可輸出私人資料庫路徑。

本 PR 仍不修改正式 `ReportJobWorker`、
不自動認領 N 輪 Job，不打開 API／ES／LLM 連線，也不啟用 N 輪。
未來 opt-in 背景 Worker 應在執行失敗後，僅對自己持有的租約
呼叫 `fail_owned_lease`；不得清除其他 Job 的資料。

本地離線測試：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_fail_owned_lease.py \
  tests/test_sraf_nround_reportjob_atomic_checkpoint.py
```

驗證多執行緒搶同一個 fail、租約錯置、跨 Job 隔離、終止後
不可復活、重啟中斷與私人路徑不洩漏。
