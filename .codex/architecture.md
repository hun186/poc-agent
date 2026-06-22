# architecture


---

## 2026-06-11 前端標題列多層導航

- `api/static/editor.html` 是 Editor / 管理系統的靜態前端入口；登入後的主要功能導航位於 `<header>` 內的 `#mainNav`。
- `#mainNav` 的第一層功能區使用 `data-nav-root` 大型按鈕切換，包括 ES 資料庫、匯入流程、系統管理與帳號安全。
- `#navSubPanel` 依 `data-nav-menu` 顯示對應第二層選單；各第二層區塊使用 `<details class="nav-level">` 逐層展開子功能，選取功能後呼叫既有 `switchMainTab()` / `newDoc()` / dashboard 導向邏輯。
- `portable_auth_pack/static/login_admin_minimal.html` 保留單檔最小 Auth 管理頁定位，並同步採用 header 內 `#authPackNav`、`data-nav-root`、`data-nav-menu` 的多層導航結構。


---

## 2026-06-11 Editor 工作區分離與紀錄分流

- `api/static/editor.html` 的登入後工作區以 `#workspaceGrid` 管理版面；`switchMainTab()` 會依目前功能切換 `.single-pane`。
- `#editorCard` 僅在 `search` 文件搜尋 / 編修頁顯示；帳號安全、帳號審核、文件異動紀錄、帳號操作紀錄與使用統計頁改為單欄工作區，避免功能混雜。
- 稽核 UI 分成 `#auditCard`（文件異動紀錄，前端只呈現 `editor.*` actions）與 `#accountAuditCard`（帳號操作紀錄，前端只呈現 `auth.*` actions）；主系統不再另設重複的登入稽核區塊，登入 / 登出 / 密碼與帳號管理紀錄統一由帳號操作紀錄查詢篩選。
- Auth 管理動作由 `api/routers/editor.py` 寫入 `api.services.editor_audit.append_audit_event()`；帳號註冊、核准、拒絕、刪除與既有密碼 / 登入動作都以 `auth.*` action 進入同一 audit log，再由前端分流呈現。

---

## 2026-06-11 共用 audit UI 工具與 Editor 統計資料流

- `api/static/audit_tools.js` 是共用前端工具模組，掛載 `window.SraAuditTools`，目前提供：
  - `bindProgressiveNav()`：桌機滑鼠 hover 展開 / 移出收合；觸控裝置維持點按展開收合。
  - `renderTimeSeriesChart()`：用 SVG 繪製 audit / usage 統計曲線。
  - `renderSummaryCards()`：繪製統計摘要卡片。
- `api/routers/editor.py` 以 `/static/audit_tools.js` 對 Editor 與 Excel→SQL dashboard 提供共用 script。
- `api/static/editor.html`、`api/static/excel_to_sql_dashboard.html` 都載入 `/static/audit_tools.js`；`portable_auth_pack/static/login_admin_minimal.html` 則載入同目錄 `audit_tools.js`，便於範例包外帶。
- Editor 使用統計資料流：前端收集類別、帳號、動作、index、起迄時間與 bucket → 呼叫 `GET /v1/editor/usage-stats` → 後端用 `filter_audit_records()` 與 `build_audit_time_series()` 回傳摘要與曲線資料 → 前端用共用 chart renderer 顯示。

---

## 2026-06-12 Auth 密碼安全架構補強

- `api/services/auth_store.py` 的密碼驗證維持 PBKDF2-HMAC-SHA256 + per-password salt + `hmac.compare_digest()`；不存在帳號登入改走固定 dummy PBKDF2 hash 驗證，避免直接快速返回造成明顯 timing account enumeration。
- `AuthStore` 內含 process-local in-memory auth failure throttle，key 為 `scope:username:client_host`，目前用於 `login` 與 `password_reset` scope；達門檻時由 router 回傳 HTTP 429 與 `Retry-After`。
- `api/routers/editor.py` 的登入流程先檢查 throttle，再執行密碼驗證；無效帳密與未啟用帳號對外回同一泛用 401 訊息，詳細 reason 僅保留於 audit log。
- token secret 仍由 `SRA_AUTH_SECRET` 優先、`SECRET_KEY` 次之；`APP_ENV` / `ENV` / `PY_ENV` 為 `prod` 或 `production` 時，不允許使用 development fallback，且 secret 至少需 32 bytes。

---

## 2026-06-12 portable_auth_pack Auth 安全同步

- `portable_auth_pack/fastapi_auth_pack` 維持可外帶 FastAPI auth 素材包定位，但已同步主系統的密碼安全行為：PBKDF2 + constant-time digest compare、missing user dummy hash verification、process-local auth throttle、production secret fail-fast。
- 外帶 router 的 `/v1/auth/login` 與 `/v1/auth/reset-password` 會在同一 process 內依 `scope:username:client_host` 節流；導入多 worker / 多 instance 專案時，文件要求改接集中式 rate limiting。
- 外帶文件與 verify script 是 portable auth pack 的契約與驗證入口；主系統 API 不直接依賴 portable auth pack runtime。

## 2026-06-12 四層 Auth Role 與權限邊界

- 主系統與 `portable_auth_pack` 的 auth store 共享四層 role model：`data_reader` < `data_editor` < `db_operator` < `superuser`。
- `api/services/auth_store.py` 提供 role 正規化、階層比較與前端公開 role options；`user` legacy role 會正規化為 `data_editor`，避免舊資料立即失效。
- `api/routers/editor_dependencies.py` 集中提供 `current_user`、`require_data_editor`、`require_db_operator`、`require_superuser`；權限不足會寫入 `authz.denied` audit event。
- Editor 文件查閱仍使用 active user；文件寫入 / 刪除使用 `require_data_editor`；Excel→SQL dashboard 查閱仍使用 active user，刪除匯入 SQL row 使用 `require_db_operator`；帳號維管仍只允許 `superuser`。
- `api/static/editor.html` 與 `portable_auth_pack/static/login_admin_minimal.html` 的帳號審核 UI 改用 role 下拉選單，從 `/v1/auth/users` 的 `role_options` 生成，避免每個 role 各一顆核准按鈕。

## 2026-06-14 Editor Audit / Usage Navigation Consolidation

- Editor 前端導覽調整為：`ES 資料庫 → 文件異動紀錄 → 使用統計` 作為文件異動統計入口，不再透過 `系統管理 → 紀錄查詢` 提供重複的文件紀錄入口。
- 帳號操作相關功能集中於 `帳號安全`：一般使用者可進入「我的使用統計」（後端強制限定本人），superuser 可額外進入「帳號操作紀錄」與「全體使用統計」。
- 使用統計頁沿用既有 `/v1/editor/usage-stats` 與共用 `audit_tools.js` 曲線 renderer；前端新增本地時間格式化與 `timezone_offset_minutes` query，後端依偏移量做曲線分桶。

## 2026-06-14 Account Audit Self-Service Boundary

- `api/routers/editor.py` 的 `/v1/editor/audit-logs` 現在同時服務 superuser 全體 audit 查詢與一般使用者自助帳號操作查詢。
- 權限邊界在後端強制：非 superuser 只能查 `auth.` prefix，且 username 固定為目前登入者；前端的「我的帳號操作紀錄」只是入口便利性，不作為安全邊界。
- 文件異動紀錄查詢仍需 superuser；一般使用者若直接以 `action_prefix=editor.` 呼叫 audit logs endpoint 會收到 HTTP 403。

## 2026-06-14 portable_auth_pack Audit Reference Sync

- `portable_auth_pack` 現在示範與主系統一致的「一般使用者可看自己的帳號稽核、superuser 可看全體」邊界。
- `login_admin_minimal.html` 的稽核時間顯示改為瀏覽器本地時間，帳號統計示範呼叫 usage stats 時傳入 `timezone_offset_minutes`；此統計 endpoint 仍是宿主專案需提供的整合點，README / import guide 已提醒移植時要接到等效 endpoint。

## 2026-06-14 Editor static asset split

- `api/static/editor.html` 現在是 Editor 的靜態 HTML shell，負責 DOM 結構與載入 `/static/audit_tools.js`、`/static/editor.css` 以及多個拆分後的 Editor JS：`editor_core.js`、`editor_form.js`、`editor_auth_nav.js`、`editor_stats.js`、`editor_audit.js`、`editor_documents.js`、`editor_bootstrap.js`。
- `api/static/editor.css` 承載原 Editor 頁面的樣式規則；Editor JS 依責任拆分為 core utilities、form rendering、auth/nav boot、stats、audit、documents/admin actions 與 bootstrap wiring，單檔目前皆低於 350 行。
- Editor 靜態測試需同時讀取 HTML shell 與 split CSS / JS assets，避免只檢查 shell 時漏掉外部化後的行為字串。

## 2026-06-14 portable_auth_pack static asset split

- `portable_auth_pack/static/login_admin_minimal.html` 現在是 portable auth pack 管理頁 HTML shell，負責 DOM 結構與載入 `audit_tools.js`、`login_admin_minimal.css`、`login_admin_minimal.js`。
- `login_admin_minimal.css` 承載 portable 管理頁樣式；`login_admin_minimal.js` 承載登入、帳號管理、稽核、統計與導航互動。
- 主系統 Editor 與 portable auth pack 的靜態測試都需合併 shell + split assets 後執行行為字串斷言。

## 2026-06-14 portable_auth_pack JS responsibility split

- `portable_auth_pack/static/login_admin_minimal.html` 除了載入 `login_admin_minimal.css`，也依序載入 `login_admin_core.js`、`login_admin_auth.js`、`login_admin_audit.js`、`login_admin_stats.js`、`login_admin_admin.js`、`login_admin_bootstrap.js`。
- portable JS 依責任拆分為 core/nav/API helpers、auth flows、login audit、account stats、admin account management 與 bootstrap event binding；單檔目前皆低於 200 行。
- portable 靜態測試需合併 shell + CSS + `PORTABLE_AUTH_PACK_SCRIPT_FILES` 後執行行為字串斷言。

## 2026-06-14 Editor static asset routing

- Editor HTML shell 透過 `/static/<asset>` 載入拆分後 assets；`api/routers/editor.py` 使用 `EDITOR_STATIC_ASSETS` 白名單服務 `editor.css`、`audit_tools.js` 與所有 `editor_*.js`。
- 不在白名單內的 `/static/{filename}` 仍回 404，避免把整個 `api/static/` 任意檔案暴露出去。

## 2026-06-14 Editor router backend split

- `api/routers/editor.py` 現在是 Editor backend 的主聚合 router，負責 `/editor` shell、白名單 `/static/{filename}`、文件 extract/search/get/save/delete 等 ES 文件操作，並 include 子 router。
- `api/routers/editor_auth.py` 承載原本在 Editor router 內的 `/v1/auth/*` route：註冊、登入、登出、密碼變更 / 重設、帳號審核與 login audit。
- `api/routers/editor_usage.py` 承載 audit / usage 查詢 route：`GET /v1/editor/usage-stats` 與 `GET /v1/editor/audit-logs`。
- 為降低拆檔對既有單元測試或內部腳本的衝擊，`api.routers.editor` 仍保留對 usage route handler 的相容 wrapper；正式 FastAPI route registration 則來自子 router。

## 2026-06-14 portable_auth_pack router backend split

- `portable_auth_pack/fastapi_auth_pack/router.py` 現在只做聚合 router，include `auth_routes.router` 與 `usage_routes.router`，維持 `from fastapi_auth_pack import router` 的外部入口。
- `portable_auth_pack/fastapi_auth_pack/auth_routes.py` 承載帳號註冊、登入、登出、密碼流程、帳號審核與 `GET /v1/auth/login-audit`。
- `portable_auth_pack/fastapi_auth_pack/usage_routes.py` 承載 portable pack 的 `GET /v1/editor/usage-stats` 帳號操作統計相容 endpoint 與其 helper。

## 2026-06-15 Report Agent 模組拆分

- `agent/report_agent.py` 現在聚焦於 report mode 的 orchestration：問題精煉、呼叫 data agent、整理 evidence、呼叫 LLM、產生 citations 與回傳結果。
- `agent/report_prompt.py` 集中保存報告 LLM 的大型 `REPORT_SYSTEM_PROMPT`，避免流程檔混入長篇提示詞。
- `agent/report_config.py` 集中解析 report LLM model id 與 timeout 相關環境變數。
- `agent/report_stats.py` 提供 `compress_stats()`，負責將 data agent 統計壓縮成報告 LLM payload 所需格式。

## 2026-06-15 Agent router 模組拆分

- `agent/agent.py` 現在聚焦於高層對話 orchestration：組合 query context、讀寫 `FileSessionStore`、呼叫任務分流結果、分派到 report / style / doc follow-up / pure LLM，並補齊統一 response shape。
- `agent/routing.py` 集中管理任務分類器相關設定與 helper：router model id、topic enum / descriptions、`TASK_ROUTER_SYSTEM`、`topic_to_index_hint()`、`llm_route_task()`、`route_task_mode()` 與 `build_router_input()`。
- 為降低拆檔對既有呼叫端的衝擊，`agent.agent` 仍 re-export `topic_to_index_hint`，主要 API `answer_with_routing()` 不變。

## 2026-06-15 Auth Store 模組邊界

- 主系統 auth storage 邊界拆為：`api/services/auth_store.py`（`AuthStore` 狀態讀寫、使用者生命週期、denylist / audit / throttle 狀態）、`api/services/auth_support.py`（角色常數、`AuthUser`、密碼雜湊、token secret、時間 / path / bootstrap helper）、`api/services/auth_tokens.py`（token payload、簽章與解析）。
- `portable_auth_pack/fastapi_auth_pack/` 採相同拆分：`auth_store.py`、`auth_support.py`、`auth_tokens.py`，維持可攜套件與主系統 auth 行為同步。
- 外部呼叫仍可從 `auth_store` import `AUTH_STORE`、`AuthStore`、`AuthUser`、role constants、`normalize_role()`、`has_role_at_least()`、`public_role_options()`、`create_token()` 與 `parse_token()`；拆檔未改變 API 路由或 response shape。

## 2026-06-15 Auth Failed Login Logging Boundary

- 主系統 `api/routers/editor_auth_logging.py` 與 portable auth pack `portable_auth_pack/fastapi_auth_pack/auth_logging.py` 各自提供 `log_failed_login_attempt()`，統一輸出 password-free `auth.login.failed` warning log。
- `editor_auth.py` / `auth_routes.py` 仍負責 HTTP login orchestration、throttle、audit persistence 與 response；即時 warning log 格式與敏感資訊控制由 logging helper 模組管理。

## 2026-06-15 Excel→SQL Dashboard backend helper split

- `data_ingestion/excel_to_sql/dashboard.py` 仍是 Excel→SQL dashboard backend 的 public module，保留 `discover_dashboard_tasks()`、`dashboard_payload()` 與 `delete_imported_sql_row()`，避免影響既有 route、測試 monkeypatch 與外部 import。
- Dashboard helper 依功能面向拆為三個同 package module：`dashboard_config.py` 管理 dashboard enable/name config helper；`dashboard_filters.py` 管理 chart bucket、時間窗、WHERE/filter normalization 與 row payload parsing；`dashboard_sql.py` 管理 JSON-safe conversion、cursor row conversion、SQL connection、audit table、table existence 與 fetch helpers。
- 此次拆檔只調整內部模組邊界；Excel→SQL dashboard HTTP contract、SQL audit table contract 與刪除匯入列 audit 行為不變。

## 2026-06-15 Excel→SQL 使用者匯入界面架構

- 使用者上傳 / 預掃描 / 確認匯入 / 記錄刪除邏輯集中於 `data_ingestion/excel_to_sql/user_imports.py`。
- 上傳 Excel 存於 `data/excel_to_sql_user_imports/active/`，刪除記錄時原檔移至 `data/excel_to_sql_user_imports/deleted/`；前端與 API response 不暴露內部檔案路徑。
- 記錄 metadata 以 JSON registry `data/excel_to_sql_user_imports/records.json` 保存，包含檔名、使用者、設定檔、狀態、預掃描結果、匯入結果與刪除資訊。
- 預掃描使用既有 workbook/header/mapping/hash helper 與 SQL existing hash 查詢，僅統計 `will_insert`、`duplicate`、`failed` 等預估結果，不寫入目的表或 audit table。
- 確認匯入會將上傳檔作為單一 `source.excel_path`，關閉既有 archive move，並重用 `process_excel_file()` 寫入 SQL 與 audit。

## 2026-06-15 Excel→SQL 使用者匯入拆檔後模組邊界

- `data_ingestion/excel_to_sql/user_imports.py`：保留為 public facade，re-export 使用者匯入工作流程對外函式。
- `data_ingestion/excel_to_sql/user_import_storage.py`：負責 registry JSON、active/deleted 檔案存放、記錄查詢、上傳保存與軟刪除。
- `data_ingestion/excel_to_sql/user_import_preview.py`：負責預掃描 Excel、依 mapping 產生 hash、查 SQL existing hash 並統計預估新增 / 重複 / 錯誤。
- `data_ingestion/excel_to_sql/user_import_runner.py`：負責確認匯入時載入設定、覆寫為單一上傳檔來源並呼叫既有 `process_excel_file()`。
- `api/static/excel_to_sql_import_records.js`：負責 dashboard 上使用者匯入記錄操作；`excel_to_sql_dashboard.html` 保留 layout 與既有監控 dashboard script。

## 2026-06-15 Excel→SQL 二次拆分後模組邊界

- `api/static/excel_to_sql_dashboard.html`：保留 dashboard layout 與 script include，不再承載大量 inline dashboard JS。
- `api/static/excel_to_sql_dashboard.js`：負責 Excel→SQL 監控 dashboard 的任務載入、audit 篩選、圖表、表格與分頁等既有監控互動。
- `data_ingestion/excel_to_sql/workbook.py`：保留 workbook discovery、sheet matching 與對外 re-export。
- `data_ingestion/excel_to_sql/workbook_rows.py`：負責欄位 mapping、header resolution、row normalization、hash 計算與 Excel row iteration。
- `data_ingestion/excel_to_sql/dashboard_delete.py`：負責 dashboard 人工刪除 SQL row 與 audit 寫入；`dashboard.py` 保留 `delete_imported_sql_row()` wrapper 以沿用既有測試 monkeypatch 點。

## 2026-06-15 Excel 匯入作業中心頁面分流

- `/excel-to-sql-dashboard` 現在定位為 Excel→SQL SQL audit 監控儀表板，負責任務選擇、audit summary / daily / file / recent event 查詢、目的地 table 與 audit 欄位篩選、SQL row delete 操作。
- `/excel-to-sql-import-center` 新增為使用者匯入作業頁，負責 Excel 上傳、預掃描、確認匯入 SQL 與匯入記錄查詢；不再提供匯入記錄刪除操作。匯入記錄儲存採 compact `records.json` ID index 搭配 `records/<id>.json` per-record payload，避免單一 registry 隨 preview/import payload 長期膨脹。
- 靜態 JS 責任分流：`excel_to_sql_dashboard.js` 僅處理監控儀表板；`excel_to_sql_import_records.js` 可在匯入作業中心獨立啟動，包含登入者顯示、任務載入、記錄列表與錯誤診斷渲染。

## 2026-06-16 Auth Store 檔案分工

- 主系統 auth store 的帳號 / token 狀態仍存於 `SRA_AUTH_USERS_FILE`（預設 `.sra_users.json`），登入稽核改存於 `SRA_LOGIN_AUDIT_FILE`；未指定時以帳號檔同目錄、同檔名前綴產生 `.login_audit.json`。
- `portable_auth_pack` 採相同架構：`AUTH_USERS_FILE` 保存帳號 / token 狀態，`AUTH_LOGIN_AUDIT_FILE` 保存登入稽核。
- 兩個 JSON store 寫入皆採 temp file + atomic replace；寫入前保留同檔名 `.bak`，讀取遇到 JSON decode 失敗時嘗試以 `.bak` 還原。

## 2026-06-16 Login Audit 分片儲存

- `SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE` 現在是 login audit manifest，不再是事件單檔；實際事件放在旁邊的 `<audit_file>.d/login_audit-YYYYMM.json`。
- `record_login_audit()` 依事件 timestamp 選擇月份 shard 寫入；`list_login_audit()` 從最新 shard 往回讀取直到滿足 limit。
- 每個 shard 仍使用 atomic replace + `.bak` 還原機制，降低單一月份 shard 損壞對其他月份紀錄的影響。

## 2026-06-16 Auth Store 模組拆分

- 主系統 auth persistence 拆為三層：`auth_store.py` 負責帳號 / 密碼 / token / throttle orchestration；`auth_json_store.py` 負責 atomic JSON IO 與 `.bak` 還原；`auth_login_audit_store.py` 負責 login audit manifest + 月份 shard。
- `portable_auth_pack/fastapi_auth_pack/` 採同名模組與同等責任分工，保持可攜素材包與主系統行為一致。

## 2026-06-16 JSON Store Backup Layout

- `JsonFileStore` 寫入時保留最新 `<file>.bak` 與最多 20 個 `<file>.bak.<YYYYMMDD>` 歷史版本；讀取正式檔壞掉時依序嘗試這些備份還原。

## 2026-06-16 JSON Store Daily Backup Layout

- JSON store 備份布局為 `<file>.bak`（每次寫入前更新）與 `<file>.bak.<YYYYMMDD>`（每天第一次改寫時建立，預設保留 20 個日期版本）。
- 還原正式檔時先嘗試最新 `.bak`，若不可解析則依日期版本由新到舊嘗試。

## 2026-06-16 JSON Recovery Records

- `JsonFileStore` 的壞檔還原流程會輸出 warning/error log，並追加 sidecar `<file>.recovery.jsonl`。紀錄包含 `action`、`path`、`backup`、`message` 與 `ts`。

## 2026-06-22 Vercel Mock Runtime 架構

- `api/services/vercel_mock_runtime.py` 集中判斷 mock runtime：`SRA_VERCEL_MOCK_MODE=force/always/on` 可強制啟用，`never/off` 可停用，預設 `auto` 會在 Vercel 環境變數或檔案系統不可寫時偏好 mock。
- `agent/es/es_client.py` 在 mock runtime 會先建立正式 Elasticsearch client 並執行 `ping()`；若正式 ES 可連線則繼續使用真實 ES，否則改用 `agent/es/mock_es_client.py` 的 in-memory `MockElasticsearch`。
- `MockElasticsearch` 提供 editor 目前需要的 `indices.exists()`、`indices.get_alias()`、`indices.get_mapping()`、`search()`、`get()`、`index()`、`delete()`，內建 `vercel_mock_vessel_activities` 測試 index 與少量示範文件。
- Excel→SQL 使用者匯入流程在 mock runtime 由 `data_ingestion/excel_to_sql/user_import_storage.py` 改用 process-local in-memory registry；preview / confirm 不讀寫 SQL Server 或磁碟 Excel，只回傳清楚標示 `mock_mode` 的示範統計。

## 2026-06-22 Vercel Mock SQL Dashboard 補強

- `data_ingestion/excel_to_sql/mock_sql.py` 是 Excel→SQL 在 Vercel mock runtime 的目的地 SQL Server / audit table 替身，提供固定的 process-local mock audit rows、dashboard summary/recent/files/options payload 與 delete-row no-op response。
- `data_ingestion/excel_to_sql/dashboard.py` 在 `should_prefer_mock_runtime()` 為 true 時，`dashboard_payload()` 不呼叫 `_connect()` / `pyodbc`，改由 `mock_dashboard_payload()` 回傳資料；`delete_imported_sql_row()` 也改為 mock no-op，不刪正式 SQL row。
- Mock SQL dashboard response 會標示 `mock_mode: true` 並提供 warning，避免使用者誤以為已連線正式 SQL Server。

## 2026-06-22 Vercel Deployment Entry

- 根目錄 `app.py` 是 Vercel Python / FastAPI runtime entrypoint，只負責 `from api.main import app`，避免搬移既有 `api/main.py` 或改變 local uvicorn 啟動方式。
- `vercel.json` 將所有 request rewrite 到 `/app.py`，並設定 `SRA_VERCEL_MOCK_MODE=auto` 與 `API_STORE_ENABLED=0` 作為 preview deployment 的非機密預設值。
- Vercel 部署說明集中在 `docs/vercel_deploy.md`，列出 mock-only preview 與 real-data deployment 需要的環境變數。
- `.env.example` 同步列出 Vercel preview mock defaults，讓本地 `.env` 與 Vercel Project Settings 有同一份變數參考。
