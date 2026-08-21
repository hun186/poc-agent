# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；實際 API source 在 `sra_api/`，`api/` 為 compatibility package，agent / retrieval / evidence 在 `agent/`，ETL 在 `data_ingestion/`。
- Chat completion 由 `sra_api/routers/chat.py` 呼叫 `agent.agent.answer_with_routing()`，分成 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`，各模式輸出皆可供 Word presenter 使用。
- Editor / Excel→SQL 共用 `sra_editor_token` localStorage 身份；SQL 資料工具限定於已啟用任務的目的表白名單，不提供任意 SQL。
- Vercel mock 僅供 preview / 唯讀用途，須明確標示 `mock_mode` 與 warnings；正式服務可用時不得以 mock 冒充成功。
- 本環境 package index 偶爾回覆 proxy 403，但既有 requirements 已安裝；缺少 Playwright / browser runtime 時，UI 以靜態測試替代並記錄限制。

## Recent Changes

### 2026-08-20 SRA API mixed-version startup 修復

- 部署端 traceback 顯示 `api.routers.chat` 載入時又以 `sra_api.routers.chat_support` 觸發第二套 `sra_api.routers` 初始化，第二份舊 chat 隨即匯入已移除的 `scope_resource_id` 而中止啟動。
- Chat support 改為 package-relative import，避免 `api.*` compatibility namespace 與 `sra_api.*` namespace 交叉遞迴載入。
- `editor_dependencies` 暫時保留 identity-only `scope_resource_id` compatibility shim；目前 agent routes 不使用它，但混合版本 worker 不再因舊 import 直接啟動失敗。
- 驗證：security/Excel/SQL targeted suite 68 tests passed；兩個全新 Python process 分別執行 `from api.main import app` 與 `from sra_api.main import app` 均成功，重現 traceback 的兩種 entrypoint 不再發生 ImportError。

### 2026-08-20 OpenWebUI agent API 相容性修復

- 前次 security patch 超出使用者要求範圍，把 Editor bearer token 強制套到 `/v1/models` 與 `/v1/chat/completions`，導致既有 OpenWebUI 連線持續收到 401；本次已還原 agent models/chat/docs/export 的既有公開整合 contract、原 session key 與 CORS 行為。
- SRA Editor、Excel 匯入、SQL 資料管理的 role、owner、enabled-task allowlist、SQL identifier 與 filename/path traversal 防護均保留。
- 新增 route regression，明確確認 OpenWebUI 所需 models/chat 以及其 docs/export 輔助路由不依賴 Editor `current_user`。
- 驗證：OpenWebUI/Editor/Excel/SQL/portable targeted suite 71 tests passed；auth store 單獨執行 21 tests passed；`TestClient(app).get('/v1/models')` 未帶 Authorization 實際回傳 200 `object=list`。
- 完整 `PYTHONPATH=. pytest tests -q` 為 221 passed / 2 個既有失敗（auth module reload identity、Vercel mock mode expectation）；OpenWebUI 相容性修復未新增失敗。

### 2026-08-20 檔名 / config path IDOR 防護

- 發現 `overwrite=true` 時 db_operator 只要知道任務設定檔名稱即可覆寫其他建立者的 JSON；現改為僅原建立者可覆寫自己的 pending 任務，已啟用任務僅 superuser 可覆寫。
- Dashboard 讀取、批次 SQL 刪除與 Excel 上傳匯入統一套用已啟用任務白名單；request 不再能以 `config_dir` 掃描系統管理目錄以外的位置。
- 匯入記錄的 per-record filename 僅接受安全 record ID（保留 legacy ID 相容），阻擋 registry 污染後的 path traversal。
- 驗證：`PYTHONPATH=. pytest tests/test_api_security_boundaries.py tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_source_editor.py tests/test_dashboard_filters.py -q`，67 tests passed。
- 完整 `PYTHONPATH=. pytest tests -q` 為 222 passed / 2 個既有失敗（auth module reload identity、Vercel mock mode expectation），未新增 regression。

### 2026-08-20 API 授權與 injection 防護稽核

- Chat、模型清單、ES 文件全文與 Word 匯出 API 改為強制 bearer 登入；process-local chat / export session 依使用者雜湊 namespace 隔離，避免猜測 session ID 越權讀取。
- 移除文件 UUID wildcard fallback，SQL Server identifier 增加結構、長度與控制字元驗證；主程式 CORS 改為明確 `CORS_ALLOWED_ORIGINS` 白名單，未設定時維持同源。
- portable auth pack 同步收緊 Bearer header parser，拒絕空 token、錯誤 scheme 與含空白的畸形 token。
- 驗證：security boundaries + SQL utils 25 tests passed；auth store 21 tests passed；portable auth preview 5 tests passed。
- 全套 `pytest tests -q` 結果為 219 passed / 2 failed；失敗為既有 suite order 下 auth module reload identity 問題，以及未修改的 `vercel.json` mock mode 與既有測試期待不一致，均與本次 security patch 無關並記錄於 known issues。

### 2026-08-20 Ollama 遠端模型設定與 router timeout 修正

- 修正共用 `call_llm()` 未把呼叫端的 `model` override 放進實際 payload 的問題；router / report 等子流程現在會使用各自指定的模型。
- router 的固定 120 秒等待改為可由 `ROUTER_LLM_TIMEOUT` 設定，並補上從 API 工作站直接測試 Ollama `/api/chat` 的部署文件。
- 驗證：`PYTHONPATH=. pytest tests/test_ollama_client_config.py tests/test_routing_input.py tests/test_pure_llm_timeout.py -q`，7 tests passed。
- 此容器透過環境 proxy 存取遠端私有 IP 時收到 HTTP 403，故實際 Ollama 推論仍須在部署 API 的遠端工作站依文件 curl 驗證。

### 2026-08-20 ES 多事件 nested mapping 相容

- `multidim_event_json.Event` 及事件關聯陣列改為 nested 後，查詢會依 outer event block 與 child nested path 分層建立，不再跨 nested context 混用 multi-match；時間線欄位改讀 `time_iso/time_raw/time_precision`。
- evidence parser 支援多層 inner hits，並將 `event_ids` 保留到 citation / evidence 輸出；DOC_FOLLOWUP 同時支援 Event 陣列。
- 驗證：`PYTHONPATH=. pytest tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py -q`，8 tests passed。

### 2026-08-13 PURE_LLM 獨立 timeout

- `REPORT_LLM_TIMEOUT` 僅作用於 SRA_REPORT，先前 PURE_LLM 固定等待 180 秒；現新增 `PURE_LLM_TIMEOUT`（預設 180 秒）供 `.env` 獨立調整。
- 路由確實使用 bounded router view；關鍵字提取的 bounded view 是另一個函式，只在檢索模式後續使用。
- 驗證：`PYTHONPATH=. pytest tests/test_routing_input.py tests/test_keyword_extraction_input.py tests/test_pure_llm_timeout.py -q`，7 tests passed。

### 2026-08-13 關鍵字提取裁切範圍隔離

- 大型檢索問句只在 `extract_topic_terms_llm()` 呼叫前建立預設 6000 字元的暫時頭尾視圖；原始查詢不被覆寫，人工詞比對、同義詞擴增與 Elasticsearch 流程仍收到完整查詢。
- 文件明確記錄路由結果與提取出的關鍵字仍會間接影響 index 選擇、同義詞種子與檢索召回，但裁切字串不會傳播成共用下游輸入。
- 驗證：`PYTHONPATH=. pytest tests/test_routing_input.py tests/test_keyword_extraction_input.py -q`，5 tests passed。

### 2026-08-13 路由裁切 terminal 提示

- 大型當輪或歷史訊息實際觸發 bounded router view 時，`agent.routing` 會輸出 WARNING，包含來源、原始字元數與路由上限，並提醒完整內容仍交給執行模型及 Word 匯出；log 不含原始本文。
- 驗證：路由測試確認大型當輪與歷史輸入會記錄提示、短訊息不記錄提示，且完整大型本文不會出現在 log。

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

### 2026-08-20 OpenWebUI 401 merge regression 修復

- 合併 PR #168 後，`sra_api/routers/chat.py`、`docs.py`、`export.py` 意外重新套用 Editor `current_user` dependency，造成未攜帶 Editor token 的 OpenWebUI `GET /v1/models` 回覆 401。
- 再次移除 agent integration routes 對 Editor bearer token 的依賴，恢復既有公開 OpenAI-compatible models/chat 與 docs/export contract；Editor、Excel→SQL 與管理 API 的授權不變。
- 驗證：`PYTHONPATH=. pytest tests/test_api_security_boundaries.py -q` 為 24 passed；`TestClient(app).get('/v1/models')` 未帶 Authorization 回傳 200 且 `object=list`。

### 2026-08-20 OpenWebUI 文件與 Word 整合驗證補強

- 補上實際 HTTP regression tests，而非只檢查 FastAPI dependency metadata：未附 Editor token 時，文件詳情、全文 JSON、全文 TXT 附件與 Word DOCX 下載皆須成功。
- 驗證涵蓋回傳內容及下載 headers（Content-Type / Content-Disposition），確認 OpenWebUI 文獻區點擊查閱、下載資料庫文件，以及報告 Word 匯出均沿用公開 integration contract。
- 驗證：`PYTHONPATH=. pytest tests/test_api_security_boundaries.py tests/test_multidim_shape_normalization.py tests/test_export_word_service.py -q`，33 tests passed。

### 2026-08-20 nested evidence source fallback 修復

- 修正 evidence parser 僅依賴 `inner_hits.evi` 的缺口：現在依序使用 inner hits、`_source.multidim_event_json[*].evidence_snippets`、舊版 `rawInfo.content`，並保留 event IDs、形狀正規化與每文件 citation 上限。
- SRA 全文日期抽取支援 nested `Event` 陣列與 `Event_Timeline.time_iso`，仍保留舊 `date_iso` 文件讀取相容；mock mapping、mock timeline fixtures 與 Editor timeline schema 對齊 nested/time 欄位。
- 驗證：nested/parser/docs/mock/editor targeted suite 25 tests passed；全套在主要修正後為 232 passed / 2 個既有失敗（auth module reload identity、Vercel mock mode expectation）。

### 2026-08-21 匯入管理子頁導航下拉自動收合

- 匯入管理的五個子頁不再預設展開目前分類；新增共用導航互動腳本，切換選單時只保留一個展開，滑鼠離開、點擊導航外部或按 Escape 都會自動收合。
- 靜態資產白名單新增共用腳本，並補上所有子頁引用與自動收合行為的靜態 regression test。
- 驗證：`node --check sra_api/static/excel_global_nav.js` 與 `PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（19 tests passed）。本環境仍無 Playwright / browser runtime，故沿用既有 known issue，以靜態 DOM、JS 語法與 FastAPI 靜態資產路由測試替代截圖。

### 2026-08-21 匯入管理導航滑入自動展開補強

- 修正前次只加入自動收合、未加入滑鼠 hover 展開的缺口：具備 hover 能力的桌機裝置在滑鼠進入導航分類時會自動展開，並關閉其他分類；觸控裝置仍保留原生點擊展開行為。
- 五個匯入管理子頁同步更新共用腳本 cache-busting 版本，避免瀏覽器沿用僅支援自動收合的舊腳本。
- 驗證：`node --check sra_api/static/excel_global_nav.js` 與 `PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（19 tests passed）。因既有 Playwright / browser runtime 限制，仍以 JS 語法、DOM 靜態與資產路由測試替代截圖。
