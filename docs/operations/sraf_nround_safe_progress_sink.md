# SRAF N 輪｜執行循環持久化進度接線（隔離、可選）

新增 `run_trusted_nround(..., checkpoint_sink=...)`，供未來
可信背景 Worker 以明確注入的方式，將協調器產生的**計數型安全進度**
傳入持久化 N 輪 checkpoint。

## 進度邊界

- 第一輪准入成功後、首筆 ES PIT 前先提交 `SEARCHING`。
  如果 checkpoint 拒絕／磁碟錯誤，**不會開始任何 ES 或 LLM**。
- 每輪 ES PIT 完整分頁後、呼叫私人語意驗證前，
  先提交已實際扣款的 ES 呼叫數。若拒絕，丟棄本輪結果，
  不進入 Evidence 覆蓋度與 Planner。
- 每輪 canonical Evidence 與可信語意覆蓋度評估結束後提交
  `ASSESSED` 或 `TERMINAL`，只有成功提交後才允許規劃下一輪。
- Planner 提交新的第 2～N 輪後，先提交新的 `SEARCHING` checkpoint，
  成功才允許下一輪 ES PIT。如果 Planner 自行安全停止則提交
  `TERMINAL`。
- `checkpoint_sink` 僅接收 `deepcopy(coordinator.safe_progress())`，
  由既有 coordinator 產生固定 schema、無原始問題、Article、
  Event 文字、ES Index、PIT ID、模型提示詞、Bearer Token 的安全進度。
  必須回傳**真正的** `True`，字串 `"true"`／數字 1／例外
  都會失敗閉鎖；回呼不能改變協調器內部的快照。

## 本 PR 沒有做的事

- 不建立或認領正式 Report Job，不直接初始化／寫入正式 SQLite。
  注入方必須使用**真正的持久化 Job／租約 CAS**；
  可以接續 PR #465 的
  `record_progress_for_running_report_job(report_store,claimed_job,...)`。
- 目前只新增隔離的 callback 接線，不修改既有單輪
  `ReportJobWorker`、API、Word 檔案或下載授權。
- 此模組不提供跨主機心跳、真正 ES／LLM 取消或中斷後續跑能力；
  原有 `NroundCheckpointStore` 明確不支援 resume。
- 即使 terminal checkpoint 記錄 `SUFFICIENT`，
  `report_generation_authorized` 仍**固定為 False**，
  正式 N 輪 Word 生成需要額外的可信 Job/Artifact CAS 與實機驗收。

## 離線 CI

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_safe_progress_sink.py \
  tests/test_sraf_nround_trusted_execution_loop.py \
  tests/test_sraf_nround_checkpoint.py
```

使用臨時 SQLite、合成 ES client、假策略 Planner／語意驗證器。
測試包含兩輪進度的單調落盤、初始寫入失敗不發 ES、
PIT 後寫入失敗不得進入 LLM、第二輪前寫入失敗不得再查 ES、
錯誤訊息去私密化，以及呼叫端修改快照也不能污染 coordinator。

## Codex P2 修正：Terminal 後持久化失敗不可殘留報告授權

若一輪已經在記憶體內被判為 `TERMINAL/SUFFICIENT`，
但**必要的** `checkpoint_sink` 回傳拒絕或丟出例外，
原有的 `coordinator.cancel()` 會因已是 terminal 而不再改變狀態，
可能讓公開進度殘留
`ready_for_external_report_generation=True`。

新增加了內部 `revoke_unpersisted_report_readiness()`：
在 checkpoint 寫入失敗時，即使先前已經是可報告的 terminal，
仍將對外 stop reason 轉成非可報告的 `CANCELLED`，
保留已驗證的 Evidence 計數以供診斷，但
`ready_for_external_report_generation` 一律轉為 False。
這不改變正常 user-cancel 的既有語意，只保護失敗的持久化接線；
CI 以 terminal 時 callback 回傳 False 及丟出含私人路徑的
`OSError` 兩種情境驗證，皆不輸出私人錯誤內容或 Word 授權。
