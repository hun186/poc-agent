# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；實際 API source 在 `sra_api/`，`api/` 為 compatibility package，agent / retrieval / evidence 在 `agent/`，ETL 在 `data_ingestion/`。
- Chat completion 由 `sra_api/routers/chat.py` 呼叫 `agent.agent.answer_with_routing()`，分成 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`，各模式輸出皆可供 Word presenter 使用。
- Editor / Excel→SQL 共用 `sra_editor_token` localStorage 身份；SQL 資料工具限定於已啟用任務的目的表白名單，不提供任意 SQL。
- Vercel mock 僅供 preview / 唯讀用途，須明確標示 `mock_mode` 與 warnings；正式服務可用時不得以 mock 冒充成功。
- 本環境 package index 偶爾回覆 proxy 403，但既有 requirements 已安裝；缺少 Playwright / browser runtime 時，UI 以靜態測試替代並記錄限制。

## Recent Changes

### 2026-08-13 大型輸入路由功能文件補充

- 目的：補足前次功能僅記錄於 persistent memory、未出現在一般開發者 README / 流程文件的缺口。
- 修改：新增 `docs/chat_agent_flow.md`，說明 bounded router view、完整 execution payload、PURE_LLM 與 Word/DOCX 資料流、環境變數及權衡；根目錄與 `sra_api/README.md` 加入入口，`.env.example` 加入兩項設定範例。
- 驗證：Markdown 相對連結與文件必要章節靜態檢查通過；路由單元測試通過。

### 2026-08-13 大型 PURE_LLM 任務路由輸入瘦身

- 目的：避免使用者把大量分析資料與指令同時送入時，120B 級模型在任務路由階段先讀完整資料而逾時。
- 修改：`agent/routing.py` 將目前問題的路由輸入限制為預設 6000 字元、每筆歷史問題限制為 1500 字元；超限時保留 75% 頭部與 25% 尾部並標示中段省略。完整原始輸入不變，仍交給選定的實際執行模型，因此不影響 PURE_LLM 回答與後續 Word 匯出。
- 設定：可用 `ROUTER_CURRENT_MAX_CHARS`、`ROUTER_HISTORY_MAX_CHARS` 調整上限，並設最低安全值。
- 驗證：dependency preflight 完成（pip index upgrade 查詢有既知 403 retry，但 requirements 皆已安裝）；`PYTHONPATH=. pytest tests/test_routing_input.py -q` 通過，3 tests passed。

### 2026-08-13 Persistent memory compaction

- 因 `memory.md` 超過 40 KB，且 `architecture.md` / `decisions.md` 已累積大量歷史區塊，依規範歸檔並重寫 active summary。
- 歸檔：`.codex/archive/memory.md-20260813-000000.md`、`.codex/archive/architecture.md-20260813-000000.md`、`.codex/archive/decisions.md-20260813-000000.md`。
- 驗證：確認 active files 低於 200 行，且完整濃縮前內容存在於上述 archive。

### 2026-07-01～2026-07-04 SQL 來源工具與全域導航

- SQL 來源資料編輯器 / 統計儀表板沿用 Excel→SQL 已啟用任務白名單、audit 與分頁 helper；匯入管理子頁使用與 Editor 一致的全域樹狀導航。

### 2026-06-23～2026-06-26 Auth、Editor schema 與任務審核

- Mock preview login 採 production hardening；Editor array 欄位以 form schema + ES mapping metadata 建立；Excel→SQL 任務由 db_operator 建立 pending 草稿、superuser 審核啟用。

## Archived History

- `.codex/archive/memory.md-20260612-032146.md`：2026-06-12 前歷史。
- `.codex/archive/memory.md-20260616-042648.md`：2026-06-12～2026-06-16。
- `.codex/archive/memory.md-20260623-064506.md`：2026-06-16～2026-06-23。
- `.codex/archive/memory.md-20260702-021320.md`：2026-06-23～2026-07-02。
- `.codex/archive/memory.md-20260813-000000.md`：本次濃縮前完整 active memory，涵蓋至 2026-08-13 路由輸入瘦身前。
