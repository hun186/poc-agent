# SRAF Report：有效 Evidence 為零時不呼叫撰稿 LLM

## 目的

使用者 2026-11-18 的正式 Report Job 曾生成不具來源依據、且誤解 SRAF 名稱的 Word。Issue #477 仍包含廣泛的內容可信度議題。為避免在一般報告管線完全沒有可核對 Evidence 時仍產生貌似確定的事件分析，新增**零證據保守返回**。

## 位置與行為

在 `agent.report_agent.ask_with_report` 收到 `run_data_agent` 的 `evidence_snippets` 後，如果已完成原本的「日期候選掃描不完整」特例判斷，而列表仍是空的，直接返回不會編造事件或驗收結論的固定繁體中文警示。此路徑不呼叫報告 LLM，也不會產生假來源、假事件或杜撰通過率；不是「沒有新聞」判定。

原本**日期查詢不完整且 Evidence 為零**的保守中斷邏輯保持不變，帶有 `result_incomplete` 和掃描上限資訊。若有任何 Evidence，保持既有報告路由與模型調用，不改動主題群組、時間篩選、信度或引用規則。

Word／Markdown 共用 Presenter 在 `evidence_usage.llm_skipped_no_evidence=True` 時，以文字顯示「未執行（缺少可核對的有效 Evidence，並非已證實沒有事件）」。資料只傳送通過型別與計數白名單的指標，不將原始問題、片段、日期或文章 ID 帶進這項診斷。

## 侷限與驗證

這只阻擋**原始有效 Evidence 清單為空**的 LLM 幻覺，不能阻擋清單非空、片段過短、來源張冠李戴、內容無法核實的其他問題。也不等於已在真實 ES 中證實「完整零件」案例。Python 3.10/3.11 Hosted CI 用合成 Agent payload、假 LLM 和實際 Word／Markdown Presenter 測試，無實機 ES、SQL、LLM 呼叫。
