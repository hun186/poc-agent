# System Architecture

## Current Summary

### Runtime layout

- `app.py` 是 root ASGI entrypoint；`api/` 提供 compatibility import，實際 FastAPI app、routers、services、presenters 與 static assets 位於 `sra_api/`。
- `agent/agent.py::answer_with_routing()` 是對話主協調器；API 建立 history / memory / trace 後呼叫它，再保存 session 並產生 OpenAI-compatible response。
- `agent/routing.py` 以 LLM 將任務分類為 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`，topic 再映射到 Elasticsearch indexes。
- `agent/report_agent.py`、`style_agent.py`、`doc_followup_agent.py` 分別承接資料報告、風格改寫與既有文件追問；PURE_LLM 直接呼叫一般模型。
- `sra_api/core/presenters/` 將統一輸出轉成 Markdown / DOCX；Word 匯出不依賴任務必須走 RAG。

### Chat data flow and bounded routing

1. API 保留完整當輪 `user_msg`，並準備 history / memory / session context。
2. `build_router_input()` 只建立分類所需的瘦身視圖：目前問題預設最多 6000 字元、每筆歷史最多 1500 字元；超限保留頭 75% 與尾 25%。
3. Router 僅讀瘦身視圖以判斷 mode / topic，不讀完整大量資料。
4. 執行階段仍使用完整 `user_msg` 或既有 `query_for_agent`；PURE_LLM 的大量資料、回答內容及 Word 匯出資料不被截斷。
5. 上限可由 `ROUTER_CURRENT_MAX_CHARS`、`ROUTER_HISTORY_MAX_CHARS` 調整。
6. 檢索模式另在關鍵字提取 LLM 前建立獨立 bounded view（預設 6000 字元）；完整精煉查詢仍傳給人工詞比對、同義詞擴增及 Elasticsearch 搜尋。
7. PURE_LLM 直接生成不經 report agent，使用獨立 `PURE_LLM_TIMEOUT`；`REPORT_LLM_TIMEOUT` 只控制 SRA_REPORT 的報告模型呼叫。

### Data and administration boundaries

- Elasticsearch 是 agent retrieval 與 Editor 文件層；Excel→SQL 匯入、audit、來源資料編輯 / 統計位於 `data_ingestion/excel_to_sql/` 與 `sra_api/routers/excel_to_sql.py`。
- SQL 來源工具只能操作啟用任務設定內的 `destination.table`，並以 role、欄位白名單、reason、audit 限制修改。
- Auth roles 為 `data_reader`、`data_editor`、`db_operator`、`superuser`；前端 session 使用同源 localStorage key `sra_editor_token`。
- Vercel mock runtime 與正式 ES / SQL 路徑分離，mock response 必須揭露其狀態。

## Recent Changes

- 2026-08-13：關鍵字提取裁切限制於 extractor 呼叫邊界，不改寫下游共用查詢。
- 2026-08-13：Chat router 新增 bounded head/tail input view，大型資料只在執行階段交給模型。
- 2026-07-01～07-04：SQL 來源編輯 / 統計與 Excel 匯入全域樹狀導航完成。
- 2026-06-25～06-29：Chat helpers、data-agent prompts、auth flows、task config builder 拆分並保留 facade contracts。

## Archived History

- `.codex/archive/architecture.md-20260813-000000.md`：濃縮前完整 architecture，含 Vercel、auth、Editor、Excel→SQL 與資料流歷史細節。
