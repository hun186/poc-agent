# SRAF N 輪｜已認領 Report Job 的隔離式背景執行入口

## 完成的接線

本階段新增 `sra_api/services/sraf_nround_claimed_job_runner.py` 的
`execute_claimed_nround_job`，把前四個 PR 的獨立模組
**收斂成一個可以由可信背景 Worker 明確呼叫的入口**：

- `PersistedClaimedNroundJobScope`：反覆核對 SQLite 裡正式
  `ReportJobStore` 已認領 Job 的所有者、session、原始問題和
  是否仍是 `running/agent_execution`。
- `WorkerScopeBinding`：對一條 canonical ES 查詢計畫及其
  owner/index 權限做事前與事後檢查，並要求真實授權策略，
  不能只以查詢有命中就認定可執行。
- `NroundCheckpointStore.claim_for_running_report_job`：在同一筆
  SQLite `BEGIN IMMEDIATE` 交易中驗證正式 Job，再核發
  單一 N 輪 checkpoint 租約。**不會自動建立 sidecar**：
  只能使用明確事先登記的 `QUEUED` N 輪 checkpoint。
- `run_trusted_nround`：保留日期、主題、來源及語意證據來源驗證，
  使用完整 ES PIT 分頁、N 輪覆蓋度評估、獨立 Planner 與剩餘時間預算。
- `checkpoint_sink`：在第一筆 ES 前、每輪 ES 後、證據評估後、
  下一輪准入後，透過 owner-bound 的同交易 CAS 寫入只有計數的
  checkpoint。落盤失敗會停止並撤銷可報告狀態。
- `fail_owned_lease`：任何不可恢復錯誤只撤銷該任務自己的 lease，
  **不呼叫**會讓所有 N 輪 Job 中斷的全域方法。

流程成功後，會重新核對正式 Job 尚未撤銷，以及 sidecar 確實是
`RETRIEVAL_STOPPED/TERMINAL`、輪次與已完成 Evidence 一致，
才將**私有的檢索結果**交給未來的 Worker。

## 非常重要：這不是正式上線

此功能目前**沒有接到正式** `ReportJobWorker.run/execute`、
HTTP API、OpenWebUI 或 Word 產製。原有單輪 Word 流程不會改變。
`ClaimedNroundRetrieval.safe_audit()` 明確回報：
`report_job=NOT_FINALIZED`、`word_generated=False`、
`word_download_authorized=False`、`live_acceptance=NOT_TESTED`。

函式不會自行：
- 建立 Job、從佇列 `claim_next()`，或初始化／修改 SQLite schema；
  正式 Worker 必須從可信伺服器狀態認領 Job，預先登記 N 輪 sidecar。
- 產生租戶 RBAC、獨立「整題真的只需一條 canonical 查詢」的
  政策或真實語意驗證器；這些仍需由正式受信任配置提供，
  **不能用 `lambda: True` 當作正式授權**。
- 把 checkpoint `RETRIEVAL_STOPPED` 當成可供使用者下載的
  Word；真正報告產製、檔案完整性、owner-bound 下載路由
  需要另一個獨立、審核過的 Artifact CAS。
- 自動恢復被中斷或失敗的 N 輪 Job。沒有跨主機可靠執行的聲明。

## CI 合成端到端範圍

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_claimed_job_runner.py \
  tests/test_sraf_nround_safe_progress_sink.py \
  tests/test_sraf_nround_reportjob_atomic_checkpoint.py
```

使用真正的**私有臨時 SQLite** ReportJobStore 與 checkpoint
（同一個檔案）、注入 fake ES PIT client、fake Planner／可信語意
回呼。驗證：
1. 第一輪合格 Evidence 仍不足、第二輪成功、權限與 checkpoint
   均同步核對，最後側錄 `RETRIEVAL_STOPPED`，但不產生 Word。
2. 未登記 sidecar、跨 DB、失效或 owner 改變的 Report Job，
   必須在第一筆 ES 前拒絕。
3. 索引或查詢分支政策拒絕、ES 途中 Job 被撤銷、語意驗證丟錯、
   checkpoint 落盤失敗，必須只將本任務的租約標為 FAILED，
   不影響另一個正在執行的任務。

**上述均不是你的 Linux 實機驗收**。現階段不要求操作部署機；
只有整個 Job／Word／API 路徑完整、真實 ES／LLM 驗收完成之後，
才應考慮向一般使用者開放 N 輪。
