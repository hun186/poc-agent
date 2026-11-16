# SRAF N 輪檢索歷程：Word／OpenWebUI 共用可讀呈現（未接正式多輪 Job）

## 需求與本次位置

研究人員需要在 Word 報告直接看見檢索過程，了解系統為何放寬門檻、增減 Evidence、何時停止、是否發生異常。先前已有 `Topic Match Adaptive`、LLM Evidence Review 和 Evidence 選取統計共用 Word／Markdown 呈現器。

此 PR 追加 `sra_api/core/presenters/nround_progress.py`，**只處理數值化、無原文的 `AdaptiveRequestCoordinator.safe_progress()` 契約**，並在既有 `evidence_usage` 物件**可選**提供 `nround_progress` 時，由 `evidence_usage_rows` 一併列入 Word 與 Markdown。

因為正式 N 輪 Job、ReportJobWorker 資料回傳與 Word 連接尚未完成，目前一般單輪報告**不會出現 N 輪檢索歷程**，也不會冒充已執行；本 PR 不自動注入假的資料。

## 可讀紀錄內容

1. **多輪智慧檢索歷程**：尚未開始、搜尋中、評估中、策略規劃中或已終止；目前輪次／完成輪次；本輪准入 ES 次數（注意：只是准入，**不能保證實際查詢成功**）。
2. **第 N 輪 Evidence**：該輪 ES 候選來源、Parser 輸出、通過本層日期／主題驗證、fallback 未列合格、同輪去重、真正新增合格 Evidence、新增來源與累計合格 Evidence／來源數。
3. **資料完整性**：由可信上層是否已完成整輪檢索與研究評估；缺失時列「尚未確認整輪完整性」。
4. **多輪檢索停止原因**：資料已足夠、資源額度用盡、兩輪沒有新增證據、使用者鎖定關鍵字、取消、資料不完整等固定中文名稱；不顯示外部模型例外字串、原始問題、索引名稱或 ES 文章 ID。
5. **多輪報告生成狀態**：只表示協調器本層是否符合交接條件；**不表示 Word 已生成或通過 Linux L3-A**。
6. **判讀限制**：此階段數據非人工 Precision、全部 ES Recall、Token 計數或最後 Word 引用數；尚未做正式 Report Job 整合與持久化恢復。

## 嚴格隱私與品質邊界

輸出一律通過 `safe_nround_progress` 的欄位白名單與型別檢查。最多 8 輪，相關列必須完整且依序、統計間保持數學一致；所有私有字串／來源資訊／未知欄位無條件剔除。為防止 Markdown 的既有「原始 JSON」除錯附錄繞過顯示白名單，提取器也只對其中的 `evidence_usage` 欄位產生安全副本再序列化；不修改原始 `out`。此範圍並不會自動隱藏其他被刻意輸出的原始問題或正式引用內容。偽造的 `live_es=LIVE_PASSED`、`report_job=COMPLETED`、`checkpoint_resume=YES`、錯誤計數、型別不對或未完成輪次卻謊稱可以生成 Word 的輸入直接拒絕，**不會被輸出到 DOCX 或 Markdown**。

此規則預設不更動原有 Evidence 使用統計；若 `evidence_usage` 沒有 `nround_progress` 或不合規，維持原有 Word／Markdown 行為。

## 測試範圍

`tests/test_sraf_nround_progress_presentation.py` 使用真實 `ExportWordService.build_docx_bytes` 產生合成 DOCX，以 `python-docx` 解析內容，再與 Markdown 共用的 `evidence_usage_rows` 核對。測試也會使用 PR #447 真正的**離線協調器**產生進度快照，確認序列化契約一致。所有測試均使用合成 ES hit／假 LLM，不對正式資料庫、OpenWebUI 或 ES 發出網路請求。

## 還需要什麼才會在使用者實際 Word 報告看到？

正式 N 輪 Job 完成可信檢索與完整性驗證，並由 Report Job／export pipeline 傳遞其經安全驗證的 `nround_progress` 到 `evidence_usage`，共用 Word／Markdown 呈現器就會輸出上述可讀行。**本 PR 僅完成安全展示端與合成檔案測試，不會自行創建 N 輪 Job 或將歷程寫入 SQL／SQLite。**
