# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；實際 API source 在 `sra_api/`，`api/` 為 compatibility package，agent / retrieval / evidence 在 `agent/`，ETL 在 `data_ingestion/`。
- Chat completion 由 `sra_api/routers/chat.py` 呼叫 `agent.agent.answer_with_routing()`，分成 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`。
- Report query refiner 以 request-time 與設定時區解析相對日期；時間 context 採 caller opt-in，並在 trace / Word 中保留可稽核基準。
- 相對週以週一至週日為完整週；「前 N 週」、「N 週前」及「過去 N 週」採不同且明確的區間語意。
- Editor / Excel→SQL 共用 `sra_editor_token` localStorage 身份；SQL 資料工具限定已啟用任務目的表白名單，不提供任意 SQL。
- Vercel mock 僅供 preview / 唯讀用途，須標示 `mock_mode` 與 warnings；正式服務不得以 mock 冒充成功。
- 環境 package index 偶爾因 proxy 403 無法更新套件，但既有 requirements 可用；缺少 Playwright / browser runtime 時以靜態測試替代 UI 截圖。

## Recent Changes

### 2026-08-26 問題精煉 timeout 預設延長

- 將 report query refiner 的通用 timeout 預設由 20 秒延長為 60 秒，並同步 report refiner 設定載入器與 `.env.example`。
- 盤點 agent/API/ingestion Python 路徑的 timeout：其餘 LLM 預設皆為 60 秒以上；較短者僅 Elasticsearch request timeout 30 秒，屬資料庫 I/O 而非生成式 LLM 呼叫，未調整。
- 驗證：`PYTHONPATH=. pytest tests/test_query_refiner_time_context.py -q` 與 `git diff --check` 通過。

### 2026-08-26 時間優先序 prompt 範例去除驗測月份

- 將「任務時間範圍優先於背景事件時間」規則中的示例月份由 10 月改為 3 月，避免 system prompt 直接包含高難度驗測案例的 10 月線索而影響效能評估。
- 回歸測試明確確認 system prompt 不含「10月」，實際驗測問題仍可在 user prompt 保留原始 10 月背景。

### 2026-08-26 去年全年範圍與背景月份優先序

- Query refiner 明定任務指令的時間範圍優先於背景事件時間；「請蒐集去年」預設換算為去年 1 月 1 日至 12 月 31 日，背景中的「10月間」只能保留為重點時段。
- 只有任務指令本身明確要求「去年10月」、「僅限10月」或同等限制時，才可縮窄至單月。
- 驗證：`PYTHONPATH=. pytest tests/test_query_refiner_time_context.py tests/test_ollama_client_config.py tests/test_export_word_service.py tests/test_routing_input.py -q`，16 tests passed；`git diff --check` 通過。

### 2026-08-25 相對週期語意與週界線補強

- Refiner 支援通用日／週／月／季／年與帶數量相對時間；週以週一至週日為界。
- 明確區分「前 N 週」（目前週之前連續 N 個完整週）、「N 週前」（往前偏移 N 週的單一完整週）與「過去 N 週」（截至 reference date 的滾動 N×7 天）。

### 2026-08-25 「去年」解析、時間 context 與模型稽核

- Refiner 明示今年／去年並要求把相對時間換成明確日期，不得依模型知識截止日猜測；reference time、時區與去年年份寫入 Data Agent payload 並顯示於 Markdown / Word。
- `call_llm()` 的目前時間採 opt-in，只有 query refiner 與 PURE_LLM 明確啟用；啟用時記錄 reason、timezone、reference time 與 output risk warning。
- Word 匯出會列出任務路由、問題精煉、資料整備及報告／風格生成階段的實際模型 ID。

### 2026-08-21 靜態 UI 導航與 Dashboard 分頁

- 代理人資料流程頁及匯入管理子頁沿用共用全域樹狀導航與延遲收合互動。
- Excel→SQL dashboard 移除重複的載入筆數欄位，以 pager「每頁顯示」作為唯一 server-side `limit` 來源，預設 2000。

### 2026-08-20 API 相容、安全與 ES nested evidence

- 修復 `api.*` / `sra_api.*` mixed-version import recursion，並保留 rolling deployment 所需 compatibility shim。
- OpenWebUI models/chat/docs/export 維持既有公開 integration contract，不誤套 Editor bearer token；Editor、Excel 與 SQL 管理端仍保留 role、owner、allowlist、identifier 及 path traversal 防護。
- ES 多事件資料按 child path 分別建立 nested query，避免跨事件欄位誤配，evidence 保留 `event_ids` 追溯。

### 2026-08-13 大型輸入路由與 timeout

- Router 與關鍵字提取使用局部 bounded view，不覆寫下游完整 query；保留頭尾並以省略標記取代中段。
- PURE_LLM 與 SRA_REPORT 使用獨立 timeout 設定，避免調整其中一條路徑影響另一條。

### 2026-07-01～2026-07-04 SQL 來源工具與全域導航

- SQL source rows / stats、排序、篩選與 audit 均受已啟用任務白名單及欄位驗證保護；靜態子頁統一使用全域樹狀導航。

### 2026-06-23～2026-06-29 Auth、Editor schema 與任務審核

- Editor 採 ES mapping metadata 作欄位型別權威；Excel→SQL 任務由 db_operator 建立 pending 設定並由 superuser 審核。
- SQL / ES 跨系統刪除保留 lineage / outbox 後續設計，不在 dashboard request 內同步硬刪 ES。

## Archived History

- `.codex/archive/memory.md-20260813-000000.md`：2026-06-11 至 2026-08-13 的完整歷史。
- `.codex/archive/memory.md-20260826-043925.md`：2026-08-26 濃縮前全文，涵蓋 2026-06-11 至 2026-08-25 的工作紀錄；因 active memory 已累積超過 20 個工作區塊而濃縮。

### 2026-08-26 Word 附加 LLM 階段埋行稽核

- Agent 將任務路由、問題精煉、資料整備、證據欄位選擇、報告／風格／一般回答生成的成功、錯誤或 fallback 狀態整理為 `llm_execution`，包含實際模型、耗時與截短後錯誤訊息。
- Word 報告在所有既有內容之後新增「附錄：LLM 各階段執行情況」，方便確認正常回傳與糾錯；錯誤回應也保留已收集的執行軌跡。
- 驗證：`PYTHONPATH=. pytest tests/test_export_word_service.py -q`，8 tests passed；`git diff --check` 通過。依賴安裝完成，pip index 查詢仍出現既有 proxy 403 retry，但 requirements 均已安裝。
