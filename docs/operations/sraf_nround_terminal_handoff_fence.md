# SRAF N 輪｜終止 checkpoint 與正式 Report Job 同交易核對

這是**只讀、隔離、尚未接入正式 Word Worker**的下一個階段。
新增 `NroundCheckpointStore.verify_terminal_for_running_report_job()`
以防未來 Worker 用兩筆不同時間的查詢，誤認原始 Job 和 N 輪進度
在同一個可信狀態。

## 安全契約

- 要求 sidecar 與 `ReportJobStore` 是**同一個 SQLite 檔案**；
  一個 `BEGIN IMMEDIATE` 交易中先驗證既有
  `report_jobs` canonical schema v2、owner/session/prompt 等
  immutable claim、狀態必須 `running/agent_execution`。
- 原 Job 的 `turn_id/docx_basename` 仍須為 NULL，禁止
  已有 Word 產物的任務再宣稱等待檢索交棒。
- N 輪 sidecar 必須已完整終止：
  `RETRIEVAL_STOPPED/TERMINAL`、`termination=SUFFICIENT`、
  無活躍 lease、完成輪數 1～8 與期望值相同、`revision`
  符合持有私有檢索結果之 Worker 的版本。過時、跳輪、
  FAILED/CANCELLED/INTERRUPTED、非充足的停止原因皆拒絕。
- 這項核對**不更動資料庫、不是租約、也不核准 Word**；
  `get_public.report_generation_authorized=False` 原樣保留。
  不寫入原始問題、Event／ES 內容、授權憑證或任何新的公開欄位。
- 例外只提供 `nround_terminal_handoff_unverified` 固定錯誤，
  不外洩私有 SQLite 位置。

## 尚未完成的重要邊界

- 已結束的 sidecar 不會保存逐篇 Evidence 原文；此檢查只證明
  同一交易中的 Job + **計數型** checkpoint 狀態，不能憑它
  宣稱有品質足夠的私有證據、真實 owner/index RBAC 或 Word 交付權限。
- 只允許 `SUFFICIENT` 供下一階段研究；
  `ROUND_BUDGET_EXHAUSTED` 等部分證據情境應另外設計明確可辨識
  的報告狀態和政策，不能暗中將不足的證據當成充分。
- 交易提交後 Job 權限可能再次變動；正式
  報告生成／Artifact 提交還需要自己的 atomic CAS、
  最新授權驗證、時間預算、審核過的輸出根目錄及下載 RBAC。
- 此 PR 不呼叫 `ReportJobWorker`、不更動既有單輪 API/DOCX、
  不開啟任何 N 輪旗標，也不執行真正 ES/LLM/SQL。

## 離線 CI

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_terminal_handoff_fence.py \
  tests/test_sraf_nround_reportjob_atomic_checkpoint.py \
  tests/test_sraf_nround_fail_owned_lease.py
```

採用臨時真實 SQLite 和合成進度，覆蓋正確終止版本、
過期 revision、非充足終止、已中斷側錄、改變所有者、
失效正式 Job、跨 DB、舊 Word artifact、schema 漂移及路徑錯誤遮蔽。
這**不是** Linux／真實 ES／LLM／DOCX E2E 驗收。
