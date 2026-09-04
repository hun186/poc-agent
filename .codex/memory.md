# Project Memory

## 2026-09-04 Phase 1B final repository closure follow-up

- Closed Review v1 follow-up findings against baseline `70f1c99b1c86a6cc6a418a315404bf8631972237` (the merge commit for PR #194): canonical PK/UQ/FK validation now proves table and ordered-column bindings, and the only version-1 compatibility repair is the transactional `import_run_rows.source_row_number` nullable correction required for non-row-scoped diagnostics.
- Added actual `RequirementStore` fake-ODBC evidence for profile/source writes, monotonic immutable draft versions and approval, snapshot modes/binding/order, version reuse/insertion, stale/anomaly audit rollback, and forced persistence rollback. Expanded HTTP evidence across unauthenticated, reader, database-operator, and superuser roles, including audited activation denials, upload boundaries, and safe error taxonomy.
- Verification: actual-store focused selection 11 passed; Phase 1B gate 80 passed with 2 warnings; Phase 0/1A gate 62 passed with 3 warnings; full repository 450 passed with 10 warnings. `compileall`, `git diff --check`, execution-dependency/sample-mapping guards, and tracked runtime-artifact scan passed.
- Live Requirement SQL Server acceptance was **NOT EXECUTED** because no explicitly authorized control-plane connection or credentials were provided. Fake ODBC is repository evidence only, not deployment acceptance.

## 2026-09-04 Phase 1B Requirement source/import pipeline

- Added strict configuration-driven mapping, UTC normalization, required hashes, manual/file/named-SQL adapters, confinement, and secret/executable-config rejection.
- Added explicit SQL Server schema v1, immutable approval/history, strict atomic snapshots, side-effect-free preview, RBAC/audit APIs, and opt-in fail-closed startup.
- Added deterministic ten-row XLSX coverage and a sample profile without committing a binary workbook or source-specific branch.
- Live SQL Server acceptance was not executed because no explicitly authorized database is available. Final repository verification is recorded after completion commands.

## 2026-09-03 Phase 0 v3 Plan v6.1 completion delta

- Restored the missing Review v2 traceability path and preserved Review v3 as the authoritative completion review.
- Added safe authorization-denied auditing for direct signed-resource scope failures and concealed Report Job owner mismatches; nonexistent Jobs remain unaudited 404 responses.
- Replaced helper-only Service Key RBAC coverage with create/list/revoke HTTP regressions through the Editor authentication dependency seam, and completed signed Word security-header assertions.
- Repeated fresh concurrent initialization exposed an intermittent SQLite WAL setup lock; `_connect()` now retries only locked WAL setup until the existing busy-timeout deadline. Five consecutive concurrency regressions passed afterward.
- Verification: targeted Phase 0 gate 87 passed with 3 warnings after one initial intermittent SQLite failure; full suite 346 passed with 10 warnings; compileall, diff check, namespace guard, tracked-runtime-artifact scan, and focused changed-file secret scan passed.
- Fast live smoke and real Elasticsearch/long-Agent/signed-Word E2E were not executed because the configured private deployment was intercepted with uniform HTTP 403 responses. Existing acceptance credentials were intentionally preserved unchanged.
- Compacted `.codex/backlog.md`; the pre-compaction history is preserved at `.codex/archive/backlog.md-20260903-000000.md`, and the active backlog retains all unresolved work. Verified the archive matches the pre-compaction content before rewriting.

## 2026-09-02 Service Key 中文設定與維運文件

- 將 OpenWebUI Service Key 設定文件擴充為中文版，補齊 production prerequisites、最小 scope、OpenWebUI 管理端設定、驗證、撤銷／更換與故障排除。
- 將 Service Key 維運文件擴充為中文版，記錄 credential model、完整 scope matrix、CLI／HTTP 操作、store 權限與跨 process transaction、備份復原及 incident rotation。
- 新增靜態文件測試，防止關鍵安全步驟與中文版標題在後續修改中遺失。
- 驗證：`PYTHONPATH=. pytest -q tests/test_security_docs.py` 為 2 passed；`git diff --check` 通過。

## 2026-09-02 Phase 0 v3 unified API security boundary

- Added unified user/service principals, registered scopes, one-time service keys with atomic cross-process persistence, service-key administration/CLI, owner-isolated Report Jobs, and exact HMAC browser capabilities.
- Fixed Editor dependency singleton staleness by resolving `AUTH_STORE` through the canonical `api.services.auth_store` module at dependency execution time.
- Job schema migrates legacy SQLite `user_version=0` to owner-aware version 1 using the approved transactional rebuild order; fresh databases start at version 1. Four rollback checkpoints preserve the complete legacy state.
- Verification recorded: new security/migration suite 10 passed; pre-change full suite after intentional route enforcement was 271 passed/19 failed, where 18 failures were obsolete anonymous-route test expectations/direct call signatures and one was the pre-existing Vercel mock expectation. A final updated-suite result is recorded in the completion entry below.
- Final verification: security/auth gate 57 passed; affected API/Job regression gate 29 passed; complete suite 305 passed with 8 warnings and zero failures. Compileall, diff check, canonical namespace guard, 12-process service-key mutation, four migration rollback injections, and manual no-key/OpenWebUI/Batch/revoked smoke checks passed.

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；實際 API source 在 `sra_api/`，`api/` 為 compatibility package，agent / retrieval / evidence 在 `agent/`，ETL 在 `data_ingestion/`。
- Chat completion 由 `sra_api/routers/chat.py` 呼叫 `agent.agent.answer_with_routing()`，分成 `SRA_REPORT`、`SRA_STYLE`、`DOC_FOLLOWUP`、`PURE_LLM`。
- Report query refiner 以 request-time 與設定時區解析相對日期；時間 context 採 caller opt-in，並在 trace / Word 中保留可稽核基準。
- 相對週以週一至週日為完整週；「前 N 週」、「N 週前」及「過去 N 週」採不同且明確的區間語意。
- Editor / Excel→SQL 共用 `sra_editor_token` localStorage 身份；SQL 資料工具限定已啟用任務目的表白名單，不提供任意 SQL。
- Vercel mock 僅供 preview / 唯讀用途，須標示 `mock_mode` 與 warnings；正式服務不得以 mock 冒充成功。
- 環境 package index 偶爾因 proxy 403 無法更新套件，但既有 requirements 可用；缺少 Playwright / browser runtime 時以靜態測試替代 UI 截圖。

## Recent Changes

### 2026-09-01 Dual-mode Word report Job API

- 保留同步 `POST /v1/report/word` 與 snapshot `GET /v1/export/word`，新增 dedicated persisted Job create/status/download resources。
- lifespan 管理唯一 worker；startup 先把 stale running 原子更新 interrupted。worker 以直接 session parameter 呼叫 shared turn service，DOCX temp write、驗證後 atomic rename。
- SQLite 每操作獨立 connection與 busy timeout，transaction-safe claim，idempotency 使用 UNIQUE key + normalized hash；正式圖只留 `docs/architecture/`。
- 驗證：Job targeted tests 9 passed、1 warning；新增 transport-neutral regression 後 review suite 42 passed、1 warning（原 baseline 為 41 passed）；完整 suite 288 passed、2 個既有 failure、8 warnings（auth module identity 403 與 Vercel mock expectation）；`python -m compileall sra_api`、SVG XML parse、`git diff --check` 通過。

### 2026-09-01 已部署 API 的非 Swagger 瀏覽器呼叫說明

- 釐清 `PUBLIC_API_BASE=http://192.168.0.133:9002` 是 origin，根路徑依既有 app contract 轉入 `/editor`，Word endpoint 必須使用 `POST /v1/report/word`，不能靠瀏覽器網址列 GET 傳送長提問。
- 自動化文件新增同源 Editor 頁面 DevTools Console `fetch()` 範例，可直接呼叫現有 Word API、檢查錯誤、把 DOCX Blob 下載成檔案並顯示 session/turn/request IDs；此方式不使用 Swagger UI，也不引入第二套非 FastAPI backend。
- 驗證：requirements 已確認安裝；`PYTHONPATH=. pytest -q tests/test_report_word_api.py tests/test_chat_word_export_metadata.py` 為 4 passed、1 warning；從 Markdown 擷取 JavaScript 為 `.mjs` 後執行 `node --check` 通過，`git diff --check` 通過。

### 2026-09-01 Word API 瀏覽器測試說明與 OpenAPI binary contract

- 補充 Swagger UI 瀏覽器測試步驟與完整加薩提問 request body，說明 POST endpoint 不能只靠網址列帶入長提問，應開啟 `/docs` 後使用 Try it out / Execute。
- `POST /v1/report/word` 的 OpenAPI 200 response 現在明確宣告 DOCX MIME 與 binary schema，讓 Swagger UI 與 API client generator 不再把成功結果誤認為 JSON。
- 驗證：先新增 OpenAPI failing test，確認原 contract 錯誤宣告為 `application/json`；最小修改後 targeted suite 為 41 passed、1 warning，compileall 與 diff check 通過。完整 `PYTHONPATH=. pytest tests -q --tb=short` 為 278 passed、2 個既有 failure、8 warnings；failure 仍是 full-suite auth module identity 403 與 `vercel.json` mock mode expectation 差異。

### 2026-09-01 自動化 API 直接回傳 Word 報告

- 新增 synchronous `POST /v1/report/word`，沿用 Chat messages/session contract，同輪 Agent 完成後直接以 structured result 產生 DOCX，不讀取 `state.json`；response 附 session/turn/request tracking headers。
- 抽出共用 Agent turn execution service，供 Chat 與 Word endpoint 統一處理 history、memory、reuse、routing call、structured identifiers 與 snapshot compatibility side effect；Chat response 新增精確輪次 `word_export` metadata。
- 新增 API automation 文件與 turn/API/DOCX/metadata/regression tests。實作前已確認使用者指定的 `docs/superpowers/plans/2026-09-01-report-word-api-automation.md` 不存在於目前 branch，因此以目前程式碼及使用者明列 scope/contract 為準完成最小設計。
- 驗證：相依套件已確認安裝（pip index upgrade 查詢仍有既有 proxy 403 warning）；targeted suite `PYTHONPATH=. pytest -q tests/test_export_word_service.py tests/test_api_security_boundaries.py tests/test_turn_execution_service.py tests/test_report_word_api.py tests/test_chat_word_export_metadata.py` 為 40 passed、1 warning。完整 `PYTHONPATH=. pytest tests -q --tb=short` 已實際跑完，結果 277 passed、2 failed、8 warnings；兩個 failure 是 `.codex/known_issues.md` 已記錄且本次未改動的 full-suite module identity 403 與 `vercel.json` mock mode expectation 差異，相關 auth 單檔驗證通過。

### 2026-08-31 Report explicit terms 與 contextual synonym contract

- Report core-term prompt 移除最低數量要求，補上人工關鍵詞控制、受控一階語義擴充、明示案例／模型聯想案例區分與背景議題跳躍限制，並將相關 prompt 範例泛化以避免驗測提示污染。
- `核心關鍵詞組如下：...` 改由限定 Report prefix 的 deterministic parser 依序清理與去重，跳過第二次 topic extraction；自然語言與 Style structured prefix 保持既有行為，Style 的 `< 5` style-only fallback 與 index_hint 傳遞未改。
- synonym LLM 改為完整 query context 下的等價／近等價名稱擴充，收斂跨領域義項與 semantic-axis 合併；Python 拒絕非原 core term 的 representative key，簡繁與 manual synonym 架構維持 deterministic。
- 驗證：`python -m compileall agent` 通過（僅有既有 `markdown_tables.py` invalid escape SyntaxWarning）；`PYTHONPATH=. pytest -q tests/test_query_terms_contract.py tests/test_keyword_extraction_input.py tests/test_routing_input.py tests/test_nested_event_mapping.py` 為 23 passed；`git diff --check` 通過。
- 相依套件 preflight 已執行；requirements 皆已安裝。package index 經 proxy 查詢 pip 更新時仍出現既有 403 retry，但未阻礙測試。

### 2026-08-27 Word 文件改以 Base64 文字保存

- 因 PR 工具無法提交 binary，移除 tracked `.docx`，改提交 `docs/SRA代理人參考文本與多層全文下載技術說明.docx.b64` 與 `docs/restore_docx.py`；restore script 會先驗證內建 SHA-256，成功後才寫出 DOCX。
- 原始與還原檔 SHA-256 均為 `ea08d8bef0498e003c0b6133379234fa10e97f8233767914c87d4560d252f2bc`，`cmp --silent` 確認 byte-for-byte 完全相同，還原檔 `unzip -t`、script `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 代理人參考文本技術介紹 Word

- 新增 `docs/SRA代理人參考文本與多層全文下載技術說明.docx`，以非開發者也能理解的方式整理更新背景、目標、核心名詞、資料流、OpenWebUI/API 行為、相容性、部署步驟、測試範圍、效益與 30 秒介紹話術。
- 文件包含資料流圖示表、相容性矩陣、下載層次表與主要技術元件附錄，可直接用於內部說明或對外簡報前的技術附件。
- 驗證：`unzip -t docs/SRA代理人參考文本與多層全文下載技術說明.docx` 通過；以 `python-docx` 重新開啟並確認 55 個 paragraphs、12 個 tables、必要章節與文件 metadata 均存在；`git diff --check` 通過。

### 2026-08-27 OpenWebUI 全文下載入口分層

- Citation 原本的單一「下載全文」連結改為參考文本、原始文本與雙層比對三個明確入口，JSON link 也直接顯示 both 層次。
- 舊文件若沒有 `agent_context`，下載參考文本會明確 404，但下載原始文本與雙層比對仍能取得 `rawInfo.content`，不再讓單一按鈕造成使用者無法判斷下載內容或只有錯誤頁。
- 新增 citation URL 與 Markdown label 測試；`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_export_word_service.py tests/test_api_security_boundaries.py -q`（49 tests passed）、presenter `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 舊文件相容性與 ingestion 雙寫測試

- 未設定 reference env 時，只有 `rawInfo.content` 的舊文件維持完整相容；切換到新欄位但尚未 backfill 時，reference 明確 404，而 raw / both 仍可供人工檢核。
- TXT→ES / SQL→ES 新資料改為保留 raw 並 seed configured reference field，使舊版 reader、新版 agent 與後續精煉 pipeline 能平順共存。
- 新增舊文件 default／切換後行為、雙層 ingestion 與 API layer 回歸測試；`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_sql_to_es_odbc_driver.py tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py tests/test_api_security_boundaries.py -q`（57 tests passed）、相關模組 `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 全文下載多層次文本

- `/v1/docs/{doc_id}/fulltext` 新增 `text_layer=reference|raw|both`，讓預設代理人參考文本與固定 `rawInfo.content` 原始材料可分別取得或並列比對。
- JSON 回傳層次可用性、欄位與長度，both 模式包含兩份文本；TXT both 使用清楚的層次／欄位標題，下載檔名含 layer suffix。
- 驗證：`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_multidim_shape_normalization.py tests/test_api_security_boundaries.py -q`（43 tests passed）、docs router `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 代理人參考文本 ingestion 串接

- 補齊 TXT→ES 與 SQL→ES 寫入端及新 index mapping，使其與 agent/API 共用 `SRA_REFERENCE_TEXT_FIELD`，避免替換讀取欄位後新匯入文件斷流。
- 確認 Excel→SQL 不直接建立 ES `_source`；其 destination 內容欄由 SQL→ES `source.columns.content` 選取後，寫入設定的代理人參考文本欄位。
- 驗證：`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_sql_to_es_odbc_driver.py tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py tests/test_api_security_boundaries.py -q`（53 tests passed）、ingestion `py_compile` 與 `git diff --check` 通過。

### 2026-08-27 代理人參考文本欄位模組化

- 將具前後文的原始全文或精煉詳文命名為「代理人參考文本」，明確與局部、可追溯的 `evidence_snippets` 分工。
- 新增 `SRA_REFERENCE_TEXT_FIELD`，預設 `rawInfo.content`；搜尋、證據 fallback、依 ID 取得參考文本與 docs 下載改用共用 accessor，無效欄位設定安全退回預設值。
- 驗證：`PYTHONPATH=. pytest tests/test_reference_text_config.py tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py tests/test_doc_followup_fetcher.py tests/test_api_security_boundaries.py -q`（47 tests passed）與 `git diff --check` 通過。

### 2026-08-26 SRA Elasticsearch 原文欄位契約盤點

- 確認 `rawInfo.content` 並非全域可設定欄位，而是在搜尋加分與 fallback、證據日期 fallback、全文／風格文件取得及 Editor 設定中直接引用。
- 結構化主搜尋主要依賴 `multidim_event_json` 與 `communication.subject`；保留完整結構化欄位時，原文改名未必使所有報告立即報錯，但會降低召回並破壞或降級全文相關功能。
- 新增 `docs/es_source_field_contract.md`，記錄安全遷移方式與需同步修改的邊界。
- 驗證：`PYTHONPATH=. pytest tests/test_nested_event_mapping.py tests/test_multidim_shape_normalization.py -q` 與 `git diff --check` 通過。

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

### 2026-08-27 Word 模型清單整合執行狀態與耗時

- Word 最後的「各階段使用模型」清單改為在每個階段的模型 ID 後直接顯示執行狀態與耗時，不再另建內容重複的 LLM 執行情況附錄；fallback / error 仍保留安全截短的錯誤備註。
- 舊 session 若只有 `data_agent.model_usage`，仍在文件最後輸出既有模型清單，不虛構無法取得的狀態或耗時。
- 驗證：`PYTHONPATH=. pytest tests/test_export_word_service.py -q`，8 tests passed；相關模組 `py_compile` 與 `git diff --check` 通過。依賴確認成功，pip index 查詢出現既有 proxy 403 retry，但 requirements 均已安裝。

### 2026-08-27 Word 模型執行階段依資料處理流排序

- 「各階段使用模型」固定依任務路由、問題精煉、資料整備、證據欄位選擇、報告生成及後續生成階段排列；Word 匯出也會穩定排序舊 session 或外部傳入的未排序執行紀錄，未知階段保留在已知階段之後。
- 驗證：`PYTHONPATH=. pytest tests/test_export_word_service.py -q`（10 tests passed）、相關模組 `py_compile` 與 `git diff --check` 通過。

## 2026-09-02 Phase 0 v3 Plan v4 completion follow-up

- Baseline `522be61636a2c36d7238429ed201ceb919217fec` on branch `work`; the requested implementation review was found under `docs/superpowers/plans/`, not the requested `docs/superpowers/reviews/` path.
- Security environment bootstrap now precedes router/security singleton imports, and the service-key CLI bootstraps before choosing its store. Shared capability authorization rejects non-canonical/duplicate/extra signed query parameters before resource lookup and applies browser security headers.
- Service-key expiration is validated and UTC-normalized; malformed persisted expiration fails credential resolution closed. Report Job migration now validates legacy constraints, staged rows, fresh/reopened v1 schemas, and exposes SQL-operation-boundary rollback injection.
- Fresh verification: security targeted gate 51 passed, 2 warnings; complete repository suite 318 passed, 9 warnings. `python -m compileall sra_api api tests`, static guards, and manual smoke gates are recorded only if run later; no prior 305-pass claim was reused.

## 2026-09-03 Phase 0 v3 Plan v6 repository acceptance delta

- 完成 unified authn/authz、Service Key 管理及 admin cross-owner Report Job 安全稽核；稽核只含非敏感 metadata。
- 新增 HTTP admin、scope/OpenWebUI、跨 process key store、並行 Job migration、signed capability 對抗、startup/CORS tracked regressions；signed `download` 僅接受 canonical `0`/`1`。
- 驗證：Phase 0 targeted 84 passed/3 warnings；full suite 343 passed/10 warnings；dependency install、compile/static gates另見本次 execution report。
- Live private API 經本環境 proxy 全部回覆 403，未能連線至 configured deployment，故 real ES/long Agent/signed Word E2E 為 NOT EXECUTED；既有 acceptance credentials 依 contract 保留未動。

## 2026-09-04 Phase 1 Batch Scheduler Core

- Added the standalone `batch_scheduler` HTTP client for canonical CSV/XLSX/JSON loading, versioned local SQLite state, deterministic idempotent submission, remote reconciliation, and confined atomic DOCX publication.
- Added validate/import/run/resume/status/execute CLI commands and removed raw-looking Phase 0 acceptance credentials from the tracked operator harness in favor of environment variables.
- Repository verification: Phase 1 targeted suite passed 24 tests. Full and affected-gate results are recorded by the implementation completion commit. Private deployment acceptance was not executed from this environment; live key rotation/revocation remains an operator action.
- Final verification evidence: Phase 1 targeted 24 passed; affected Report Job/security gate 38 passed with 5 warnings; full repository suite 370 passed with 10 warnings; compileall and diff check passed. Dependency installation succeeded from already-installed requirements despite the documented package-index proxy retries.

### Final verification evidence

- Phase 1B focused gate: 14 passed, 0 failed, 2 warnings.
- Phase 0/1A regression gate: 62 passed, 0 failed, 3 warnings.
- Full repository gate: 384 passed, 0 failed, 10 warnings.
- `compileall`, `git diff --check`, direct Agent/ES/Word/Report-worker import guard, and no-value-printing tracked-diff credential scan passed.
- Dependency preflight completed with installed requirements; the package index returned the already-known proxy 403 retries while pip continued with satisfied packages.

## 2026-09-04 Phase 1B completion delta v1.1

- Closed Implementation Review v1 findings: failed Import Runs now persist bounded row diagnostics; commit-lock stale/anomaly races roll back before a separate failure-audit transaction; CSV parsing preserves duplicate/empty positions for strict ambiguity detection; SQL schema startup migrates version 0 and structurally validates version 1; SQL/persistence errors map to stable safe codes.
- Added real `RequirementStore` recording-ODBC coverage for failed diagnostics, migration states, rollback, and persistence sanitization, plus dependency-layer HTTP 401/403/operator/superuser and safe-error regressions. Existing MemoryStore integration coverage continues to prove authoritative/upsert snapshot semantics.
- Documented that named SQL security uses reviewed registry SQL plus a read-only database principal; SQL parsing is not the security boundary.
- Phase 1B focused gate: 28 passed, 0 failed, 2 warnings. Phase 1A/Phase 0 regression gate: 62 passed, 0 failed, 3 warnings after removing raw-looking operator-harness keys in favor of required environment variables. Full repository gate: 398 passed, 0 failed, 10 warnings. Compileall, diff check, direct execution-import/sample-branch guards, tracked runtime-artifact scan, and no-value credential literal scan passed.
- Live Requirement SQL Server acceptance was NOT EXECUTED because this environment has no explicit authorization/credentials for the intended control-plane database. Repository fake-ODBC evidence is not deployment acceptance.
