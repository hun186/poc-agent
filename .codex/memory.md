# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；API 在 `sra_api/`（另有相容 shim），agent / retrieval / evidence 在 `agent/`，資料匯入與 ETL 在 `data_ingestion/`，設定在 `config/`，測試在 `tests/`。
- Editor / Excel→SQL 相關頁面共用 `sra_editor_token`；前端登入身份來源統一使用 localStorage，不使用 URL query/hash 或 sessionStorage 傳遞 bearer token。若修改前端靜態 JS，需同步更新 HTML script query version 以避免瀏覽器沿用舊資產。
- Excel→SQL 使用者匯入採上傳保存、預掃描、確認匯入 SQL 三階段；SQL 來源資料編輯器只允許操作已啟用 dashboard 任務的 `destination.table`，禁止任意 SQL / 任意 table name。
- Auth 採四層 role：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 正規化為 `data_editor`。新註冊帳號預設 `data_reader` + `pending`。
- Vercel / mock runtime 只用於檢閱或唯讀環境，正式 ES / SQL 可用時仍應優先使用真實服務；mock response 必須透過 `mock_mode` 與 warnings 明確揭露。
- 目前環境缺少 Playwright / browser runtime；可視 UI 變更若無法截圖，以靜態 UI 測試、JS 語法檢查與 pytest 替代，並於 known issues 記錄。

## Recent Changes

### 2026-07-02 SQL 來源資料編輯器登入修正安全調整

- 目的：回應 URL hash token handoff 的資安疑慮。
- 主要修改：移除 `#sra_token` bearer token handoff，不再把 token 放入 URL；改以既有同源 localStorage session 承接登入狀態，並新增同分頁 sessionStorage 導航承接 fallback：Editor 點 SQL 來源資料編輯器前把現有 token 寫入 sessionStorage，目標頁讀 localStorage 或 sessionStorage。同步更新 Editor bootstrap 與 SQL 來源資料編輯器 JS cache-busting 版本，避免部署後載入舊資產造成誤判未登入。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip upgrade 查詢套件索引遇 403 retry，但 requirements 已滿足）、`node --check sra_api/static/editor_bootstrap.js`、`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q`。

### 2026-07-02 SQL 來源資料編輯器登入承接修正（已被安全調整改寫）

- 曾短暫加入 URL hash token handoff；後續判定有 token 暴露風險，已於同日移除。保留結論：前端登入承接應避免 URL 帶 token，必要時優先以同源 storage / server-side cookie 設計處理。

### 2026-07-01 SQL 來源資料編輯器使用者篩選補強

- 來源編輯器頁面載入 `/static/audit_tools.js`，使用既有 `SraAuditTools` 多選 helper 呈現使用者篩選；後端 `source-rows` 支援 `username_filter` 並回傳 `username_options`。

### 2026-07-01 SQL 來源資料編輯器與 dashboard 拆檔

- `data_ingestion/excel_to_sql/dashboard.py` 維持 facade；task discovery / 批次刪除報表組裝拆出小模組。SQL 來源資料編輯器採受控 table 白名單、必填 reason、禁止修改 hash / 系統欄位並寫入 SQL audit。

### 2026-06-26 Excel→SQL 任務設定檔自助管理

- 任務 JSON 建立流程從 Excel 匯入作業中心拆成獨立頁；db_operator 只能管理自己建立的 pending 設定檔，superuser 維持審核啟用權限。

### 2026-06-25 Editor / multidim_event_json 穩定性修正

- Editor array 新增改以表單 schema 作為 array item shape 來源；`multidim_event_json` 相關讀取路徑支援 dict、list[dict] 與 JSON 字串；新增概要與 multi-event TODO 文件。

### 2026-06-23 Vercel mock preview login hardening

- Mock preview login 在 production-like 環境預設停用，只有明確 force 才可啟用；preview secret 只由環境變數提供，不寫入 repo；mock preview token 以 claim 標記並限制 mock-only ES 讀取邊界。

## Archived History

- `.codex/archive/memory.md-20260612-032146.md`：歸檔 2026-06-12 03:21 UTC 前完整 memory 歷史。
- `.codex/archive/memory.md-20260616-042648.md`：歸檔 2026-06-12 至 2026-06-16 的 active memory。
- `.codex/archive/memory.md-20260623-064506.md`：歸檔 2026-06-16 至 2026-06-23 的 active memory。
- `.codex/archive/memory.md-20260702-021320.md`：歸檔 2026-06-23 至本次濃縮前的 active memory；本次濃縮保留仍有效摘要、近期工作與 URL token handoff 安全修正結論。

### 2026-07-02 SQL 來源資料編輯器登入與說明樣式對齊

- 目的：修正從 Editor 首頁登入後進入 SQL 來源資料編輯器仍顯示未登入的使用體驗，並將「受控 SQL 來源資料表」說明改成與既有 dashboard / Editor 問號浮動提示一致的樣式。
- 主要修改：SQL 來源資料編輯器前端新增 `authToken()` / `loadCurrentUser()`，沿用其他 Excel→SQL 頁面的 `/v1/auth/me` 驗證與 header 顯示模式，同時保留 Editor 導航寫入的同分頁 `sessionStorage` fallback，並優先使用 session handoff token 再回退 localStorage，避免舊 localStorage token 壓過導航承接 token。說明 UI 移除原本 details popover，改用 `scope-help` / `scope-help-tooltip` 問號提示樣式。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 仍出現 403 retry，但 requirements 已滿足）、`node --check sra_api/static/editor_bootstrap.js`、`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q`。本環境未提供瀏覽器 / Playwright runtime，未做實機截圖；以靜態 UI 測試與 JS 語法檢查替代。


### 2026-07-02 SQL 來源資料編輯器登入流程改回 localStorage-only

- 目的：前次修正仍讓 SQL 來源資料編輯器讀取 sessionStorage，可能被舊或無效的同分頁 token 壓過有效 localStorage token；依使用者回饋，改成與 Excel→SQL dashboard、Excel 匯入作業中心、JSON 任務管理相同的身份讀取流程。
- 主要修改：SQL 來源資料編輯器 `authToken()` 改為只讀 localStorage；Editor 導航到 SQL 來源資料編輯器時不再寫入 sessionStorage handoff，四個 Excel→SQL 入口都只靠同源 localStorage token 承接登入身份；同步更新 cache-busting 版本與靜態測試。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`、`node --check sra_api/static/editor_bootstrap.js`、`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q`。

### 2026-07-02 SQL 來源資料編輯器靜態 JS 404 修正

- 目的：修正使用者回報 `/static/excel_to_sql_source_editor_app.js?v=20260702-source-editor-local-auth` 回傳 404，導致 SQL 來源資料編輯器前端 JS 未載入、登入狀態停留在「未登入」。
- 主要修改：將 `excel_to_sql_source_editor_app.js` 加入 Editor `/static/{filename}` 白名單，因目前 FastAPI 先掛載 `editor.router`，`/static/...` 會由 Editor static route 處理；未列入白名單會直接 404，即使檔案存在於 `sra_api/static/`。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 仍出現 403 retry，但 requirements 已滿足）、`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_static_asset_is_served_by_static_route tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_page_and_navigation_are_wired -q`。

### 2026-07-02 SQL 來源資料編輯器身份取得差異釐清

- 結論：目前 SQL 來源資料編輯器與 Excel→SQL 匯入查詢儀表板、Excel 匯入作業中心、JSON 任務管理皆使用同一個 localStorage key `sra_editor_token`，並呼叫 `/v1/auth/me` 驗證身份；使用者看到唯獨 SQL 來源資料編輯器顯示未登入，是因該頁專用 JS 檔被 `/static/{filename}` 白名單擋下而 404，導致身份驗證程式完全沒有執行，不是 token 傳遞流程不同。
- 主要修改：回歸測試從只檢查單一 SQL 來源資料編輯器 JS，改為掃描四個 Excel→SQL HTML 頁面引用的 `/static/*.js`，逐一用 FastAPI `TestClient` 確認都能被 static route 服務，避免同類白名單漏列問題再次發生。

### 2026-07-02 SQL 來源資料編輯器使用者欄位與共用分頁 helper

- 目的：修正 SQL 來源資料編輯器使用者篩選無選項、資料列缺少使用者欄位，並將文件異動記錄使用的完整分頁導航體驗推廣到多個容易累積大量資料的管理區塊。
- 主要修改：`data_ingestion/excel_to_sql/table_editor.py` 在目的資料表沒有 `username` / `audit_actor` / `audit_user` / `actor` 欄位時，改從 Excel→SQL audit table 依 `destination_table` 與 `hash_value` 補回使用者選項與 `_audit_username` 虛擬欄位；`sra_api/static/audit_tools.js` 新增 `updatePager()` / `bindPager()` 共用 helper；套用到 Excel→SQL audit 最近事件、Excel 匯入記錄管理、SQL 來源資料編輯器、任務 JSON「我建立的任務清單 / 審核進度」、Editor 帳號審核等分頁區塊，補上首頁 / 上一頁 / 頁碼輸入跳轉 / 下一頁 / 末頁。
- 驗證：`node --check sra_api/static/audit_tools.js && node --check sra_api/static/excel_to_sql_source_editor_app.js && node --check sra_api/static/excel_to_sql_dashboard_app.js && node --check sra_api/static/excel_to_sql_import_records.js`；`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q`。依專案要求也先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`；pip index 仍有 403 retry，但 requirements 已滿足。

### 2026-07-02 SQL 來源資料編輯器匯入使用者語意修正

- 目的：依使用者回饋，SQL 來源資料編輯器的「使用者」篩選應精確代表「執行 Excel→SQL 匯入的使用者」，不得讀取目的資料表自身可能存在的 `username` 情報欄位，以免特殊資料表欄位語意混淆。
- 主要修改：`data_ingestion/excel_to_sql/table_editor.py` 的 `username_options`、`username_filter` 與回傳列上的使用者欄位一律從 Excel→SQL audit table 取得；目的資料列即使有 native `username` 欄位，也只當一般資料欄位顯示，不再作為匯入使用者篩選來源。SQL 來源資料編輯器 UI 文案改為「匯入使用者」，回傳列補 `_import_username` 虛擬欄位表示匯入操作者。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 仍有 403 retry，但 requirements 已滿足）、`node --check sra_api/static/audit_tools.js && node --check sra_api/static/excel_to_sql_source_editor_app.js && node --check sra_api/static/excel_to_sql_dashboard_app.js && node --check sra_api/static/excel_to_sql_import_records.js && node --check sra_api/static/editor_documents.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q`。

### 2026-07-02 Excel→SQL 匯入使用者系統欄位落地

- 目的：將 SQL 來源資料列的原生 `username` 欄位保留為一般目的資料欄位，同時讓 `_import_username` 成為匯入時由程式寫入的系統欄位，語意專指「執行匯入的使用者」。
- 主要修改：Excel→SQL 使用者匯入若有 `_audit_actor`，會在目的資料表自動建立 / 補齊 `_import_username NVARCHAR(255)`，並於新增 destination row 時填入當下匯入者；SQL 來源資料編輯器只把 `_import_username` 視為不可編輯系統欄位，目的表原生 `username` 不再被系統欄位清單攔截。既有 rows 顯示 `_import_username` 時仍優先用 audit table 補值，沒有 audit 對應時回退目的資料表欄位值。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 查詢仍出現 403 retry，但 requirements 已滿足）、`python -m pytest tests/test_audit.py tests/test_excel_to_sql_source_editor.py tests/test_sql_utils.py -q`。

### 2026-07-02 Excel→SQL 我建立的任務檢示 JSON 轉換細節

- 目的：讓 db_operator / superuser 在「我建立的任務清單 / 審核進度」也能回看自己建立的 Excel→SQL 任務 JSON 轉換細節，避免建立後忘記欄位對應、目的資料表或遮蔽後 JSON 內容時只能請 superuser 查審核區。
- 主要修改：任務 JSON 管理頁在我的任務操作欄新增「檢示」按鈕；點擊後以 dialog 顯示與 superuser 審核區共用的 JSON 任務轉換細節、欄位對應與遮蔽敏感資訊後的 JSON preview。共用前端 render helper，維持 DB server、database、user、password 等敏感欄位只顯示遮蔽值。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 查詢仍出現 403 retry，但 requirements 已滿足）、`node --check sra_api/static/excel_to_sql_import_records.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py::test_import_center_static_contains_user_import_controls -q`。

### 2026-07-02 API Contract 記憶濃縮

- 目的：`.codex/api_contract.md` 超過 400 行觸發記憶濃縮。
- 主要修改：完整舊版 API contract 已歸檔至 `.codex/archive/api_contract.md-20260702-063606.md`；active contract 重寫為目前仍有效的摘要，並保留本次 SQL 來源資料編輯器權限、篩選、刪除與 audit scope 變更。
- 驗證：以 `wc -l .codex/api_contract.md` 確認濃縮後低於 200 行，並保留歸檔檔名於 active memory。

### 2026-07-02 SQL 來源資料編輯器權限、刪除、audit 與批次篩選補強

- 目的：回應受控 SQL 來源資料表欄寬、權限、刪除操作、audit 缺口與依來源 Excel / 匯入時間篩選批次錯誤資料的需求。
- 主要修改：`data_reader` 可唯讀 source rows；`data_editor` 可單列編輯與單篇刪除；`db_operator` 可在來源資料編輯器勾選批次刪除，沿用 dashboard 風格的原因、確認文字與最後確認。source rows 由 audit table 補 `_imported_at` / `_source_excel`，並支援 audit source_file 與 processed_at 起迄篩選；dashboard selected-task audit scope 納入 manual-control config_path 事件，避免來源資料編輯器操作不出現在最近 audit 事件。前端縮窄 `_import_username` 欄寬並新增匯入時間 / 來源 Excel 顯示。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 查詢仍出現 403 retry，但 requirements 已滿足）、`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`python -m py_compile data_ingestion/excel_to_sql/table_editor.py data_ingestion/excel_to_sql/dashboard.py sra_api/routers/excel_to_sql.py`、`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py tests/test_dashboard_filters.py::test_dashboard_source_scope_filters_selected_task_registry_and_configured_sources tests/test_excel_to_sql_dashboard_static.py::test_excel_pages_static_scripts_are_served_by_static_route tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_page_and_navigation_are_wired -q`。

### 2026-07-02 共用分頁導航排版修正

- 目的：修正 Excel 匯入記錄管理與所有使用共用分頁導航工具的區塊中，首頁按鈕貼到上一行、sr-only label 可見、頁數輸入框占滿整欄造成分頁控制破碎不緊湊的問題。
- 主要修改：`sra_api/static/audit_tools.js` 在 `updatePager()` / `bindPager()` 時注入共用 pager CSS，強制 `.pager` 使用 flex row、`.pager-jump` inline-flex、頁碼 input 固定寬度，並補上 `.sr-only` 視覺隱藏規則；不需逐頁複製 CSS，所有共用 pager 使用點會一致套用。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 查詢仍出現 403 retry，但 requirements 已滿足）、`node --check sra_api/static/audit_tools.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py::test_import_center_static_contains_user_import_controls tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_page_and_navigation_are_wired tests/test_editor_auth_ui_static.py::test_editor_audit_views_are_client_paginated_after_sorting -q`。

### 2026-07-02 共用分頁每頁筆數控制

- 目的：修正共用分頁導航仍缺少統一每頁顯示筆數控制，避免各頁自帶「每頁筆數 / 列數上限」欄位與共用分頁互相衝突。
- 主要修改：`sra_api/static/audit_tools.js` 的 `bindPager()` 新增共用 page-size 控制，包含下拉選項與直接輸入筆數；Excel 匯入記錄、任務 JSON 我的任務、Excel→SQL 最近 audit、SQL 來源資料編輯器與 Editor 帳號審核改由共用 pager 控制 page size。SQL 來源資料編輯器移除工具列原本的 `limit` input；Excel→SQL dashboard 移除原本的「列數上限」 input，改以最近 audit 分頁控制送出的 `limit`。既有 client-side 顯示仍維持先產生已篩選 / 已排序 row list，再呼叫 `paginateRows()` 切出目前頁面。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 仍有 403 retry，但 requirements 已滿足）、`node --check sra_api/static/audit_tools.js sra_api/static/excel_to_sql_source_editor_app.js sra_api/static/excel_to_sql_dashboard_app.js sra_api/static/excel_to_sql_import_records.js sra_api/static/editor_documents.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py::test_import_center_static_contains_user_import_controls tests/test_excel_to_sql_dashboard_static.py::test_excel_pages_static_scripts_are_served_by_static_route tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_page_and_navigation_are_wired tests/test_editor_auth_ui_static.py::test_editor_audit_views_are_client_paginated_after_sorting -q`。

### 2026-07-02 帳號操作記錄查詢移除最多筆數

- 目的：回應帳號安全 → 帳號操作記錄下方已有分頁導覽，因此查詢區塊不再顯示容易與分頁混淆的「最多筆數」欄位。
- 主要修改：`sra_api/static/editor.html` 移除 `accountAuditLimit` 欄位並更新 `editor_audit.js` cache-busting 版本；`sra_api/static/editor_audit.js` 改以固定後端載入上限 500 筆查詢帳號 audit，再由既有前端分頁顯示目前頁面；清空篩選不再重設已移除的欄位。同步更新靜態 UI 測試。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 仍有 403 retry，但 requirements 已滿足）、`node --check sra_api/static/editor_audit.js`、`PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py::test_editor_workspace_separates_document_and_account_work_areas tests/test_editor_auth_ui_static.py::test_editor_static_shell_loads_split_assets tests/test_editor_auth_ui_static.py::test_editor_audit_views_are_client_paginated_after_sorting -q`。曾誤用不存在的 pytest target `test_editor_static_scripts_are_split_and_loaded`，已改跑正確測試名稱。


### 2026-07-02 帳號操作記錄安全上限與未完整載入告警

- 目的：回應帳號操作記錄固定載入 500 筆可能太少、但完全不限量又可能造成瀏覽器或後端過載的疑慮。
- 主要修改：`GET /v1/editor/audit-logs` 的 `limit` 上限由 500 提高至 5000，response 新增 `truncated` 表示篩選後資料超過本次回傳筆數。帳號操作記錄前端移除手動筆數欄位後，固定以安全上限 5000 查詢；若後端回報截斷或載入筆數達安全上限，會跳出告警並在 status 提醒使用者用帳號、動作或時間條件縮小查詢範圍。同步更新 API contract 與靜態 / router 測試。
- 驗證：`python -m py_compile sra_api/routers/editor_usage.py`、`node --check sra_api/static/editor_audit.js`、`PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py::test_editor_workspace_separates_document_and_account_work_areas tests/test_editor_auth_ui_static.py::test_editor_static_shell_loads_split_assets tests/test_editor_audit_queries.py::test_list_audit_logs_reports_truncated_hits tests/test_editor_audit_queries.py::test_list_audit_logs_allows_regular_user_own_account_events -q`。依專案要求本輪也先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`；pip index 仍有 403 retry，但 requirements 已滿足。


### 2026-07-02 載入列數/筆數上限命名與控制補正

- 目的：回應 Excel→SQL 匯入查詢儀表板仍需要保留列數上限控制，以及帳號安全 → 帳號操作記錄雖有分頁但仍應讓使用者控制後端載入筆數上限。
- 主要修改：Excel→SQL dashboard 查詢列恢復 `limit` 控制並改名為「載入列數上限」，仍使用後端既有 1-1000 安全上限；帳號操作記錄恢復 `accountAuditLimit`，改名為「載入筆數上限」、預設 5000、最大 5000，前端以使用者輸入送出 `/v1/editor/audit-logs` limit，若 `truncated=true` 或已達該上限則跳窗提醒使用者縮小帳號、動作或時間條件。同步更新靜態測試與資產版本。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip index 仍有 403 retry，但 requirements 已滿足）、`for f in sra_api/static/editor_audit.js sra_api/static/excel_to_sql_dashboard_app.js; do node --check "$f" || exit 1; done`、`PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py::test_editor_workspace_separates_document_and_account_work_areas tests/test_editor_auth_ui_static.py::test_editor_static_shell_loads_split_assets tests/test_excel_to_sql_dashboard_static.py::test_excel_pages_static_scripts_are_served_by_static_route tests/test_excel_to_sql_dashboard_static.py::test_dashboard_refresh_and_audit_filters_preserve_explicit_time_range -q`。


### 2026-07-03 audit / source editor 載入上限調整

- 目的：依使用者要求，帳號操作記錄「載入筆數上限」保留使用者控制且最大提高到 50000；SQL 來源資料編輯器也新增同樣的載入筆數上限；Excel→SQL dashboard 最近 audit 事件載入上限預設提高到 50000、最大 400000 以支援安全查核大量檢索。
- 主要修改：`GET /v1/editor/audit-logs` limit 上限改為 50000，帳號操作記錄 UI 預設 5000 / max 50000，且只在後端 `truncated=true` 時用明確文案提示「已達載入上限，尚有資料未載入」；SQL 來源資料編輯器 router / table editor limit 上限提高到 50000，前端新增 `sourceLimit` 預設 5000；Excel→SQL dashboard limit 預設 50000 / max 400000，router / dashboard / mock clamp 同步提高。高上限可能增加 SQL 查詢、network payload 與瀏覽器 DOM 負載；目前以使用者可調上限 + 篩選條件控制風險，後續若需要更大量查核，建議追加後端匯出或 server-side cursor / cache。
- 驗證：`python -m py_compile sra_api/routers/editor_usage.py sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/table_editor.py data_ingestion/excel_to_sql/mock_sql.py`、`for f in sra_api/static/editor_audit.js sra_api/static/excel_to_sql_dashboard_app.js sra_api/static/excel_to_sql_source_editor_app.js; do node --check "$f" || exit 1; done`、`PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py::test_editor_workspace_separates_document_and_account_work_areas tests/test_editor_auth_ui_static.py::test_editor_static_shell_loads_split_assets tests/test_editor_audit_queries.py::test_list_audit_logs_reports_truncated_hits tests/test_excel_to_sql_dashboard_static.py::test_excel_pages_static_scripts_are_served_by_static_route tests/test_excel_to_sql_dashboard_static.py::test_dashboard_refresh_and_audit_filters_preserve_explicit_time_range tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_page_and_navigation_are_wired -q`。


### 2026-07-03 audit count/truncation 與 dashboard 統計範圍釐清

- 目的：回應帳號 audit 截斷判斷是否應用 COUNT、以及 Excel→SQL dashboard 上方統計是否不受最近事件載入上限影響。
- 主要修改：帳號 audit 來源目前是 JSONL 檔案而非 SQL table，因此沒有 SQL COUNT 語法可用；本次移除「limit+1」過度讀取方式，改固定讀取目前安全上限 50000 內的 audit records 後用篩選總數 `total` 與回傳 `hits` 長度決定 `truncated`。Excel→SQL dashboard 既有上方 summary / daily / filtered time-series 皆為 SQL `COUNT(1)` 聚合，不受最近事件 `limit` 影響；新增測試確認 `limit` 只會進入來源檔案摘要 / 最近事件載入，不會套到 status summary COUNT。
- 驗證：`python -m py_compile sra_api/routers/editor_usage.py`、`PYTHONPATH=. pytest tests/test_editor_audit_queries.py::test_list_audit_logs_reports_truncated_hits tests/test_dashboard_filters.py::test_dashboard_payload_applies_destination_table_filter -q`。
