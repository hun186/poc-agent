# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；API 在 `api/`，agent / retrieval / evidence 在 `agent/`，資料匯入與 ETL 在 `data_ingestion/`，設定在 `config/`，測試在 `tests/`。
- Auth 採四層 role：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 正規化為 `data_editor`。新註冊帳號預設 `data_reader` + `pending`，由 superuser 核准 / 更新層級。
- 主系統與 `portable_auth_pack` 的 Auth 行為需同步：dummy password hash timing balance、登入 / reset-password / register process-local throttle、production secret fail-fast、generic login / register response、登入失敗 warning log。
- Auth JSON 儲存已拆分：`auth_store.py` 保留帳號 / 密碼 / token / throttle orchestration；`auth_json_store.py` 管理 atomic JSON IO 與備份還原；`auth_login_audit_store.py` 管理 login audit manifest + 月份 shard。
- Login audit 不再寫入 users JSON；`SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE` 是 manifest path，實際事件寫入旁邊 `<audit_file>.d/login_audit-YYYYMM.json` shard。
- JSON 寫入保留最新 `.bak`，並在每天第一次改寫該檔案時建立 `.bak.<YYYYMMDD>` 歷史備份；預設保留 20 天版本。讀取正式檔 JSON 損壞時會先試最新 `.bak`，再往歷史備份回溯。
- 初始 superuser 不採用「第一個註冊者自動升權」；仍應使用 bootstrap superusers 檔案、環境變數或 secret manager 注入。
- 目前環境缺少 Playwright / browser runtime；可視 UI 變更若無法截圖，以靜態 UI 測試與 JS 語法檢查替代，並於 known issues 記錄。

## Recent Changes

### 2026-06-16 JSON Store daily backups

- 依使用者要求，JSON 多版本備份改為「每天第一次改寫該檔案時保留一份歷史備份」，避免每次登入 / audit 寫入都產生大量版本，並把預設歷史版本數量改為 20。
- `JsonFileStore` 仍每次寫入前更新最新 `.bak` 以支援最近一次還原；`.bak.<YYYYMMDD>` 每日只建立一次，保留較長時間跨度。
- Validation：`pytest tests/test_auth_store_security.py -q` 通過（20 passed）；`python -m py_compile api/services/auth_json_store.py portable_auth_pack/fastapi_auth_pack/auth_json_store.py` 通過；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests -q` 通過（89 passed，5 個既有 warning）。

### 2026-06-16 Auth Store persistence refactor

- 新增主系統與 portable 版 `auth_json_store.py` / `auth_login_audit_store.py`，將 JSON IO、備份還原、login audit sharding 從 `auth_store.py` 拆出。
- `AuthStore.record_login_audit()` / `list_login_audit()` 保留 public API，內部委派給 `LoginAuditStore`。
- Validation：完整測試曾通過（87 passed）。

### 2026-06-16 Login Audit sharding

- Login audit 改為 manifest + 月份 shard：舊 users file 中的 `login_audit` 與舊單檔 audit `events` 會遷移到 shard。
- `SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE` 保留為 manifest 設定入口。
- Validation：auth store tests、portable verify script 與完整測試曾通過。

### 2026-06-15 Excel 匯入儲存與 UI 調整

- Excel 使用者匯入採上傳保存、預掃描、確認匯入 SQL 三階段；匯入記錄 storage 拆為 compact index + per-record payload。
- Excel 匯入作業中心與 SQL 監控 dashboard 分頁；匯入記錄刪除能力已移除。

### 2026-06-14 Editor / portable auth UI 與統計調整

- 帳號操作紀錄、統計儀表板、使用者 / IP 多選篩選、本地時間顯示與 tooltip 已同步主系統與 portable auth pack。
- 因環境缺少 Playwright，相關可視 UI 變更以靜態 UI 測試、node syntax check 與 pytest 替代。

## Archived History

- `.codex/archive/memory.md-20260612-032146.md`：歸檔 2026-06-12 03:21 UTC 前完整 memory 歷史。
- `.codex/archive/memory.md-20260616-042648.md`：歸檔 2026-06-12 至 2026-06-16 的完整 active memory，包含 Editor / Auth / Excel 匯入 / login audit sharding / auth store 拆檔與 JSON backup 演進細節。

## Compaction Record

- 2026-06-12：首次濃縮 `.codex/memory.md`，歸檔至 `.codex/archive/memory.md-20260612-032146.md`。
- 2026-06-16：因 active memory 接近 400 行且本次仍需追加任務紀錄，已將濃縮前內容歸檔至 `.codex/archive/memory.md-20260616-042648.md`，並重寫為目前有效摘要、近期變更與歸檔索引。
- Validation：`wc -l .codex/memory.md` 確認濃縮後低於 200 行；本次功能驗證以 auth store tests、portable verify script 與完整 pytest 為準。

## 2026-06-16 JSON Recovery Warning / Record

- 目的：讓正式 JSON 壞檔觸發備份還原時，有告警訊息與持久紀錄提醒管理者。
- 主要修改：`JsonFileStore` 還原成功會輸出 `auth_json_recovered_from_backup` warning log；備份不可用會輸出 `auth_json_backup_unusable` warning log；無可用備份時輸出 `auth_json_recovery_failed` error log。每次還原流程也會寫入同目錄 `<file>.recovery.jsonl`，記錄 action、正式檔路徑、備份路徑與錯誤訊息。
- 驗證：`pytest tests/test_auth_store_security.py -q` 通過（20 passed）；`python -m py_compile api/services/auth_json_store.py portable_auth_pack/fastapi_auth_pack/auth_json_store.py` 通過；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests -q` 通過（89 passed，5 個既有 warning）。

## 2026-06-16 Auth File Usage Documentation

- 目的：補強主系統與 portable auth pack 使用說明，明確描述 `SRA_AUTH_USERS_FILE` / `SRA_LOGIN_AUDIT_FILE` 與 `AUTH_USERS_FILE` / `AUTH_LOGIN_AUDIT_FILE` 的角色、建議路徑、產物與不要指到同一檔案的注意事項。
- 驗證：本次為文件補強，使用 `rg "SRA_AUTH_USERS_FILE|SRA_LOGIN_AUDIT_FILE|AUTH_USERS_FILE|AUTH_LOGIN_AUDIT_FILE" README.md portable_auth_pack/README.md portable_auth_pack/CODEX_IMPORT_GUIDE.md portable_auth_pack/examples/env.example -n` 檢查相關說明存在。

## 2026-06-16 Excel 匯入記錄導入檔名與 audit 快速查詢

- 目的：讓 Excel 匯入作業中心可直接對應原始上傳檔名與實際寫入 audit 的磁碟導入檔名，並提供一鍵跳轉至 SQL 監控儀表板查詢該檔 audit 條目。
- 主要修改：匯入記錄列表新增「導入檔名」欄位顯示 `stored_filename`；檔名篩選同步比對原始檔名與導入檔名；操作欄新增「查詢已匯入條目」按鈕，帶入 `config`、`source_file_filter` 與較長回看天數跳轉至 `/excel-to-sql-dashboard`；監控儀表板啟動時可讀取 URL query 並套用篩選。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）；`node --check api/static/excel_to_sql_import_records.js` 與 `node --check api/static/excel_to_sql_dashboard.js` 通過；`pytest tests/test_dashboard_filters.py tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（20 passed）；`pytest tests -q` 通過（90 passed，5 個既有 warning）。

## 2026-06-18 Word 匯出回答標題

- 目的：讓下載的 Word 報告在「使用者提問」之後，於 AI 代理人回答前也有明確 heading，避免提問與回答界線不清。
- 主要修改：`ExportWordService.build_docx_bytes()` 在 `pres.answer` 存在時先加入 `AI 代理人回答` level 2 heading，再渲染回答 Markdown。
- 驗證：`pytest tests/test_export_word_service.py -q` 通過（1 passed，1 個既有 docx table escape warning）；`python -m py_compile api/services/export_word_service.py` 通過。

## 2026-06-18 Word 匯出區塊段落編號確認

- 目的：確認新增 `AI 代理人回答` heading 不會移除或改變回答內既有 `一、資料概況`、`二、活動時間線（依日期排列）`、`三、趨勢分析` 等區塊段落標題。
- 主要修改：補上 DOCX 匯出回歸測試，使用回答 Markdown 中的粗體區塊標題驗證其仍會由既有 markdown renderer 轉成 `Heading 2`，且出現在 `AI 代理人回答` heading 之後。
- 驗證：`pytest tests/test_export_word_service.py -q` 通過（2 passed）；`python -m py_compile api/services/export_word_service.py` 通過。

## 2026-06-18 Word 匯出智慧合併表格確認

- 目的：確認新增 `AI 代理人回答` heading 後，回答 Markdown 內的表格仍會進入既有 DOCX table renderer，並保留智慧垂直合併重複儲存格功能。
- 主要修改：補上 DOCX 匯出回歸測試，使用活動時間線 Markdown 表格驗證 Word 仍產生表格，且重複的「船名」「海域」欄位會合併，日期欄位不會被錯誤合併。
- 驗證：`pytest tests/test_export_word_service.py -q` 通過（3 passed）；`python -m py_compile api/services/export_word_service.py` 通過。

## 2026-06-18 Excel 匯入記錄查詢已匯入列跳轉

- 目的：調整 Excel 匯入作業中心的匯入記錄操作欄文案與排序，並讓「查詢已匯入列」可直接跳到 SQL 監控儀表板的最近 audit 事件區塊，以導入檔名快速篩選。
- 主要修改：操作按鈕順序改為「預掃描」、「確認匯入SQL」、「查詢已匯入列」；深連結加入 `#recentAuditSection`，並保留以 `stored_filename` 帶入 `source_file_filter`、`config` 與 `page=1` 的快速查詢行為（不額外限制 days）；監控儀表板最近 audit 事件區塊新增 anchor id。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）；`node --check api/static/excel_to_sql_import_records.js` 與 `node --check api/static/excel_to_sql_dashboard.js` 通過。

## 2026-06-18 Excel 匯入記錄查詢 days 限制移除

- 目的：依使用者回饋，查詢特定匯入檔案已匯入列時已有明確檔名標的，不應再預設加上回看天數限制。
- 主要修改：移除「查詢已匯入列」深連結中的 `days=365` query；保留 `config`、`source_file_filter`、`page=1` 與 `#recentAuditSection`。同時恢復先前非必要的 dashboard JS cache-busting token 與操作欄 CSS，避免把與需求無直接關係的版面調整混入修正。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）；`node --check api/static/excel_to_sql_import_records.js` 與 `node --check api/static/excel_to_sql_dashboard.js` 通過。


## 2026-06-18 Excel 匯入作業中心操作欄按鈕等寬

- 目的：改善 Excel 匯入作業中心匯入記錄操作欄三個按鈕併列時寬度不一致，避免「確認匯入SQL」因跨欄而特別寬。
- 主要修改：操作欄改為三欄等寬 grid，三個按鈕同列同寬；手機版維持單欄直排。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）；`node --check api/static/excel_to_sql_import_records.js` 通過；目前環境仍缺少 Playwright，無法執行瀏覽器截圖。


## 2026-06-18 Excel 匯入作業中心操作欄改為窄版直排

- 目的：回應使用者回饋，電腦版三顆操作按鈕同列等寬仍會占用過多表格欄寬；因前方欄位本就可能多列顯示，操作欄改採窄版直排以節省水平空間。
- 主要修改：操作欄由三欄等寬 grid 改為單欄直排，縮小操作欄桌機欄寬比例；保留三顆按鈕等欄寬但不佔用額外水平空間。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）；`node --check api/static/excel_to_sql_import_records.js` 通過；目前環境仍缺少 Playwright，無法執行瀏覽器截圖。

## 2026-06-18 Excel 匯入記錄錯誤診斷開合與文案調整

- 目的：避免 Excel 匯入記錄管理表格的「錯誤診斷」欄因長錯誤摘要撐高版面，並將「監控任務」等較不直覺文案改為操作語境較清楚的「匯入任務」。
- 主要修改：匯入記錄錯誤診斷改用可點擊展開 / 收合的 `<details>`；匯入作業中心與匯入查詢儀表板的任務選擇 label 改為「匯入任務」；頁首與儀表板標題改為「Excel→SQL 匯入查詢儀表板」；範例設定任務名稱改為「船舶活動 Excel 匯入任務」。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）；`node --check api/static/excel_to_sql_import_records.js` 通過；目前環境仍缺少 Playwright，無法執行瀏覽器截圖。

## 2026-06-18 Excel audit 最近事件使用者篩選

- 目的：在 Excel→SQL 匯入查詢儀表板「最近 audit 事件」加入「使用者」篩選，操作方式與既有統計 / 檢核曲線儀表板的使用者多選篩選一致，並重用共用 `SraAuditTools` multi-filter helper。
- 主要修改：使用者匯入確認流程會把匯入者寫入 audit row payload 的 `audit_actor`；dashboard 後端支援 `username_filter` 複選查詢，從 `audit_actor` / legacy `actor` 萃取可選使用者；前端最近 audit 篩選新增使用者搜尋、多選、勾選目前篩選、清除目前篩選與清除全部。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/file_processor.py data_ingestion/excel_to_sql/user_import_runner.py data_ingestion/excel_to_sql/dashboard.py api/routers/excel_to_sql.py` 通過；`node --check api/static/excel_to_sql_dashboard.js` 通過；`pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py -q` 通過（16 passed）；`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_audit.py -q` 通過（23 passed）。

## 2026-06-18 Excel audit 最近事件使用者欄位

- 目的：釐清並補強 Excel→SQL 匯入查詢儀表板最近 audit 事件的使用者可見性；使用者篩選來源是 audit `row_payload` 內的 `audit_actor` / `actor`，既有 UI 未在最近事件表格直接顯示使用者。
- 主要修改：最近 audit 事件查詢回傳 `username` 欄位，來源與使用者篩選一致；最近 audit 事件表格新增「使用者」欄，讓每筆列級 audit 可直接看到匯入使用者。若舊資料或 CLI 匯入未寫入 actor，該欄會是空白，使用者篩選也不會產生可選項。
- 驗證：`pytest tests/test_dashboard_filters.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（16 passed）；`node --check api/static/excel_to_sql_dashboard.js` 通過。

## 2026-06-18 Excel audit 欄寬與匯入者確認

- 目的：回覆並補強 Excel→SQL 使用者匯入的每列 audit 使用者紀錄，以及調整最近 audit 事件表格欄寬，讓 payload 取得更多顯示空間。
- 主要修改：確認匯入流程會將匯入記錄的 `username` 傳入處理設定 `_audit_actor`，後續每列 audit payload 會寫入 `audit_actor`；最近 audit 表格將檔案欄設為窄欄、固定最近事件表格版面，並提高 payload 欄寬。
- 驗證：`pytest tests/test_dashboard_filters.py tests/test_excel_to_sql_dashboard_static.py tests/test_excel_to_sql_user_imports.py -q` 通過（22 passed）；`node --check api/static/excel_to_sql_dashboard.js` 通過；`python -m playwright --version` 仍因未安裝 Playwright 無法截圖。

## 2026-06-18 最近 audit 事件表欄寬調整

- 目的：修正 Excel→SQL 監控儀表板「最近 audit 事件」表格中檔案欄換行與鄰欄擠壓、時間欄過窄，以及 payload 欄未使用寬螢幕空間導致過早換行的問題。
- 主要修改：監控儀表板主內容不再限制 1400px；最近 audit 表格改為 100% 使用可用寬度並提高最小表寬；時間欄新增固定欄位 class 與較寬 min-width；檔案欄改用 normal word-break + anywhere overflow wrap，避免長檔名壓到旁邊欄；payload JSON 移除不必要 min-width 並允許在 payload 欄內換行。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（7 passed）；`node --check api/static/excel_to_sql_dashboard.js` 通過；嘗試 `python -m playwright --version` 失敗（No module named playwright），本環境仍無法做瀏覽器截圖。

## 2026-06-18 Excel→SQL audit 事件表欄寬修正

- 目的：依使用者回饋，縮減最近 audit 事件表時間欄寬、修正部分欄位文字溢出與欄位對不齊，並讓下方表格與 payload 欄更充分使用水平寬度。
- 主要修改：最近 audit 事件表加入 `colgroup` 固定欄位對應；時間欄由 15% 調整為 10%（約三分之二）並降低最小寬度；整體表格最小寬度提高至 1700px；payload 欄提高至 40% / 680px；所有欄位套用 `box-sizing` 與 `overflow-wrap:anywhere` 以避免文字跑出格子。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（7 passed）；`node --check api/static/excel_to_sql_dashboard.js` 通過；截圖驗證因環境缺少 Playwright 無法執行，已以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-18 Excel audit username 實體欄位

- 目的：修正 Excel→SQL 最近 audit 事件「使用者」顯示未讀到使用者資訊，並讓 SQL audit 表以一般欄位保存 username，避免只依賴 `row_payload` JSON 解析。
- 主要修改：`ExcelImportAudit` 建表與既有表升級流程新增 nullable `username NVARCHAR(255)`；audit insert 會由 `row_payload.audit_actor` / `audit_user` / `actor` 擷取 username 寫入實體欄位；dashboard 查詢優先讀 `username` 欄，並保留 JSON fallback 以相容舊資料或刪除 audit。
- 驗證：`pytest tests/test_audit.py tests/test_dashboard_filters.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（21 passed）；`python -m py_compile data_ingestion/excel_to_sql/audit.py data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/dashboard_sql.py` 通過。

## 2026-06-22 Excel→SQL 最近 audit 表欄寬微調

- 目的：依使用者回饋，縮窄 Excel→SQL 匯入查詢儀表板「最近 audit 事件」表格中的「狀態」與「使用者」欄，節省橫向版面。
- 主要修改：將 recent audit table 的狀態欄寬由 7% 調整為 5%、使用者欄寬由 8% 調整為 6%，釋出的寬度補到 payload 欄（40% → 44%）；同步更新靜態 UI 測試檢查欄寬設定。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（7 passed）；`node --check api/static/excel_to_sql_dashboard.js` 通過；`python -m playwright --version` 因目前環境缺少 Playwright module 無法截圖，沿用靜態 UI 測試與 JS 語法檢查作為替代驗證。

## 2026-06-22 Vercel Mock Runtime

- 目的：讓部署在 Vercel 這類唯讀 / 無法連內網 ES 的環境時，可自動切換到可檢閱的測試 mock 資料集，減少手動從 GitHub 下載後搬到開發環境才能實測的成本。
- 主要修改：新增 `SRA_VERCEL_MOCK_MODE` 控制的 runtime 偵測；在 Vercel / 唯讀環境優先嘗試正式 ES ping，失敗才啟用 in-memory mock Elasticsearch。Excel 匯入記錄在 mock runtime 改用 in-memory registry，預掃描與確認匯入回傳清楚標示 `mock_mode` 的測試結果，不寫入磁碟或 SQL Server。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_mock_runtime.py -q` 通過（2 passed）；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_vercel_mock_runtime.py -q` 通過（7 passed）；`PYTHONPATH=. python -m py_compile api/services/vercel_mock_runtime.py agent/es/mock_es_client.py agent/es/es_client.py data_ingestion/excel_to_sql/user_import_storage.py data_ingestion/excel_to_sql/user_import_preview.py data_ingestion/excel_to_sql/user_import_runner.py` 通過。

## 2026-06-22 Vercel Mock SQL Dashboard

- 目的：回應 Excel 匯入會牽連目的地 SQL Server 與 audit dashboard 的問題，補齊前次僅 mock upload / preview / confirm 流程但未提供 dashboard SQL audit mock 的缺口。
- 主要修改：新增 `data_ingestion/excel_to_sql/mock_sql.py`，提供 Vercel mock SQL audit rows、dashboard payload 與 delete-row mock response；`dashboard_payload()` / `delete_imported_sql_row()` 在 mock runtime 不連 SQL Server，改回傳 `mock_mode: true` 與 warning。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_mock_runtime.py -q` 通過（3 passed）；`PYTHONPATH=. pytest tests/test_dashboard_filters.py tests/test_excel_to_sql_user_imports.py tests/test_vercel_mock_runtime.py -q` 通過（18 passed）；`PYTHONPATH=. pytest tests -q` 通過（100 passed，7 個既有 warning）。

## 2026-06-22 Vercel Deployment Config

- 目的：補齊部署到 Vercel 所需的入口與設定檔，避免只有 mock runtime 實作但缺少 Vercel 可辨識的 FastAPI entrypoint / route config。
- 主要修改：新增根目錄 `app.py` re-export `api.main.app`；新增 `vercel.json`，將所有路由 rewrite 到 `/app.py`，設定 function maxDuration 與非機密 mock preview 預設環境變數；新增 `docs/vercel_deploy.md` 說明 Vercel mock / real-data 環境變數與部署注意事項；新增靜態測試驗證 Vercel 設定檔。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py -q` 通過（3 passed）；`PYTHONPATH=. python -m py_compile app.py api/services/vercel_mock_runtime.py agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py` 通過；`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_mock_runtime.py -q` 通過（6 passed）。
- 補充：`.env.example` 也新增 Vercel Preview / Mock Runtime 區塊，列出 `SRA_VERCEL_MOCK_MODE=auto` 與 `API_STORE_ENABLED=0`。

## 2026-06-22 Vercel static filename conflict fix

- 目的：修正 Vercel 部署時對同目錄「去除副檔名後檔名不可重複」的限制，避免 `api/static/excel_to_sql_dashboard.js` 與 `api/static/excel_to_sql_dashboard.html` 產生路徑衝突。
- 主要修改：將 Excel→SQL dashboard JS 改名為 `excel_to_sql_dashboard_app.js` 並同步更新 HTML、router 靜態資產白名單與測試；同時移除 `api/static` 其他已知同 stem 靜態檔衝突（`editor`、`index`、`swagger-ui`）。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py tests/test_excel_to_sql_user_imports.py tests/test_editor_auth_ui_static.py -q` 通過（30 passed，3 個既有 warning）；`node --check api/static/excel_to_sql_dashboard_app.js` 通過；自訂 Python 檢查確認 `api/static` 無同 stem 檔名衝突。

## 2026-06-22 Vercel static conflict scope reduction

- 目的：回應落地部署相容性疑慮，將上一版為了預防 Vercel 同 stem 衝突而做的 `editor`、`index`、`swagger-ui` 靜態檔改名復原，避免影響既有落地部署或外部快取 / 文件引用。
- 主要修改：僅保留實際造成 Vercel 錯誤的 Excel→SQL dashboard JS 改名（`excel_to_sql_dashboard_app.js`）；其餘既有靜態檔名維持原狀。
- 驗證：執行 Excel dashboard 與 Editor 靜態測試、dashboard JS 語法檢查；另用限定檢查確認 `excel_to_sql_dashboard.html` / `excel_to_sql_dashboard_app.js` 不再同 stem。

## 2026-06-22 Excel dashboard JS legacy static alias

- 目的：降低 `excel_to_sql_dashboard.js` 改名為 `excel_to_sql_dashboard_app.js` 對落地部署、舊快取 HTML 或外部固定 URL 的相容性風險。
- 主要修改：保留新實體檔名以避開 Vercel 同 stem 限制，但在 FastAPI `/static/{filename}` route 中新增舊檔名 alias，讓 `/static/excel_to_sql_dashboard.js` 仍回傳新版 JS 內容；不在檔案系統恢復舊檔，避免 Vercel 再次衝突。
- 驗證：新增靜態 route 測試確認舊 URL 與新 URL 回傳相同內容；執行相關 pytest 與 JS 語法檢查。

## 2026-06-22 Vercel Swagger UI static conflict exclusion

- 目的：修正 Vercel 回報 `api/static/swagger-ui.js` 與 `api/static/swagger-ui.css` 去副檔名後同 stem 衝突，同時避免改動落地部署檔名。
- 主要修改：新增 `.vercelignore`，只在 Vercel 部署時排除未被 `api/static/index.html` 引用的 `swagger-ui.js` 與其 source map；保留 `swagger-ui.css`、`swagger-ui-bundle.js` 與 `swagger-ui-standalone-preset.js` 等實際 Swagger UI 頁面使用的資產。
- 驗證：新增 Vercel 靜態衝突測試確認被排除的是未引用的 ESM bundle，且必要 Swagger UI 資產未被排除。

## 2026-06-22 Vercel function entrypoint moved under api

- 目的：修正 Vercel 回報 `functions` 中的 `app.py` pattern 不符合 `/api` 目錄內 Serverless Functions 的錯誤。
- 主要修改：將 Vercel entrypoint 從根目錄 `app.py` 改為 `api/app.py`，由該檔 re-export `api.main.app`；`vercel.json` 的 rewrite 與 `functions` maxDuration pattern 同步改為 `/api/app.py` / `api/app.py`。
- 驗證：更新 Vercel config 測試與部署文件，並執行 Vercel config 相關 pytest 與 py_compile。

## 2026-06-22 Vercel functions pattern 修正

- 目的：處理 Vercel build failed：`The pattern "api/app.py" defined in functions doesn't match any Serverless Functions inside the api directory.`
- 主要修改：移除 `vercel.json` 的 `functions` override / `maxDuration` 設定，保留 rewrite 到 `api/app.py`，讓 Vercel Python framework preset 自行 discovery FastAPI ASGI app，避免手動 function pattern 在 build discovery 階段失配。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_static_conflicts.py -q` 通過；`PYTHONPATH=. python -m py_compile api/app.py` 通過。

## 2026-06-22 Vercel bundle size 修正

- 目的：處理 Vercel build failed：bundle size 433.35 MB 超過預設 245 MB limit。
- 主要修改：擴充 `.vercelignore`，排除 Vercel preview runtime 不需要的本地語料、技術文件、logs、runtime state、sample、docs、tests 與 `.codex` 記憶檔；保留 `api/`、`agent/`、`config/`、`data_ingestion/` 與 `portable_auth_pack/` runtime source。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_static_conflicts.py tests/test_vercel_deploy_config.py -q` 通過；以 `du -sh` 確認被排除的本地資料目錄包含 `data/` 362 MB、`technical_documents/` 256 MB、`logs/` 34 MB、`.api_state/` 19 MB。

## 2026-06-22 Vercel Hobby function count 修正

- 目的：處理 Vercel Hobby plan build failed：`No more than 12 Serverless Functions can be added to a Deployment`。
- 主要修改：恢復根目錄 `app.py` 作為唯一 Vercel Python build entrypoint，刪除 `api/app.py`，並將 `vercel.json` 改為 explicit `version: 2` / `builds: [{src: "app.py", use: "@vercel/python"}]` / routes 到 `app.py`。此設定避免 Vercel 把既有 `api/` 應用套件底下多個 `.py` 模組當成多個 serverless functions。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_static_conflicts.py -q` 通過；`PYTHONPATH=. python -m py_compile app.py api/services/vercel_mock_runtime.py agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py` 通過。

## 2026-06-22 Vercel function invocation crash 修正

- 目的：處理 Vercel runtime `FUNCTION_INVOCATION_FAILED` 500 crash，前一版使用 legacy `builds` / `routes` 強制 `@vercel/python` build 可能繞過 FastAPI framework preset。
- 主要修改：保留根目錄 `app.py` re-export `api.main.app`，但移除 `vercel.json` 的 `version` / `builds` / `routes`，只保留非機密 env defaults；讓 Vercel zero-config Python FastAPI preset discovery root `app.py` 作為單一 ASGI app。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_static_conflicts.py -q` 通過；`VERCEL=1 VERCEL_ENV=production APP_ENV=production PYTHONPATH=. python - <<'PY' ... import app ... PY` 可成功 import app；`PYTHONPATH=. python -m py_compile app.py api/services/vercel_mock_runtime.py agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py` 通過。

## 2026-06-22 Vercel api package relocation

- 目的：處理 Vercel Hobby plan 仍將 top-level `api/` 目錄內多個 Python 檔視為多個 Serverless Functions 的問題。
- 主要修改：將實際 FastAPI source tree 從 top-level `api/` 移至 `sra_api/`；保留 top-level `api/__init__.py` compatibility package，將 `api.*` import path 指向 `sra_api/`，因此 `from api.main import app` 與既有程式 import 可繼續運作，但 Vercel 只會看到 `api/__init__.py`，不再看到 49 個 `api/**/*.py` functions。
- 驗證：`find api -type f -name '*.py' | wc -l` 確認 top-level `api/` 僅 1 個 Python shim；`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_static_conflicts.py tests/test_editor_auth_ui_static.py tests/test_excel_to_sql_dashboard_static.py tests/test_excel_to_sql_user_imports.py -q` 通過；`PYTHONPATH=. python -m py_compile app.py api/__init__.py sra_api/services/vercel_mock_runtime.py sra_api/routers/editor.py sra_api/routers/excel_to_sql.py` 通過。

## 2026-06-22 Vercel api/index entrypoint 修正

- 目的：處理 Vercel build 成功但連線仍 `FUNCTION_INVOCATION_FAILED` 的情況；推定 root `app.py` zero-config 在此部署未被 Vercel Python runtime 正確作為 FastAPI function 服務。
- 主要修改：新增 `api/index.py` 作為 Vercel-routed Python function entrypoint，並在 `vercel.json` 將所有 request rewrite 到 `/api/index.py`；top-level `api/` 仍只有 `__init__.py` shim 與 `index.py` 單一 entrypoint，不再包含完整 source tree，因此符合 Hobby plan function 數量限制。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_vercel_static_conflicts.py -q` 通過；`PYTHONPATH=. python -m py_compile app.py api/__init__.py api/index.py sra_api/services/vercel_mock_runtime.py sra_api/routers/editor.py sra_api/routers/excel_to_sql.py` 通過；`find api -type f -name '*.py' | wc -l` 輸出 2。

## 2026-06-22 Vercel auth storage read-only 修正

- 目的：處理 Vercel runtime crash：`OSError: [Errno 30] Read-only file system: '/var/task/.sra_users.login_audit.json.d'`。
- 主要修改：`auth_support._auth_file()` 在偵測到 Vercel 環境且未顯式設定 `SRA_AUTH_USERS_FILE` 時，改用 `/tmp/sra-auth/.sra_users.json` 作為 process-local auth state；login audit 預設隨 auth file 派生到 `/tmp`，避免 import `AUTH_STORE` 時嘗試在 read-only `/var/task` 建立 audit shard 目錄。
- 驗證：新增 Vercel config test 確認 Vercel 預設 auth / login audit 路徑都在 `tempfile.gettempdir()`；`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_auth_store_security.py -q` 通過；Vercel-like subprocess 使用 `/healthz` 驗證 app import 與路由可用。

## 2026-06-22 Vercel root editor redirect

- 目的：處理使用者連到 Vercel deployment root `/` 時看到 `{"detail":"Not Found"}`；目前主要入口是資料庫 Editor 頁 `/editor`。
- 主要修改：在 FastAPI app 新增 root route `GET /`，以 redirect response 導向 `/editor`，讓直接開部署網址會進入現有 Editor 入口。
- 驗證：新增 Vercel-like subprocess test 確認 `/` 回 307/308 且 `Location: /editor`；`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py -q` 通過。

## 2026-06-22 Vercel mock preview login

- 目的：讓 Vercel preview deployment 在無法預先設定落地端 admin 帳號時，仍可登入 Editor 測試 mock 資料流程。
- 主要修改：新增僅在 `should_prefer_mock_runtime()` 啟用時可用的 mock preview login API，會在 `/tmp` auth store 建立 process-local `vercel_mock_reader` data_reader 並發 token；Editor 登入區會偵測可用性後顯示「Vercel mock 閱讀者登入」按鈕。此帳號不使用固定密碼，且 mock mode 關閉時 API 回 404。
- 驗證：新增 Vercel-like tests 覆蓋 enabled endpoint、mock preview login token 與一般環境 404；靜態 UI 測試確認按鈕與 JS handler 存在。

## 2026-06-22 Vercel mock preview reader role

- 目的：降低 Vercel mock preview 登入風險，避免公開 preview 預設取得 superuser 權限。
- 主要修改：mock preview login 改為建立 process-local `vercel_mock_reader`，role 為 `data_reader`；Editor 按鈕文案改為「Vercel mock 閱讀者登入」。此帳號可用於 mock 查詢預覽，不提供 superuser 管理權限。
- 驗證：更新 Vercel mock preview login test，確認 token user role 為 `data_reader`；靜態 UI 測試確認新按鈕文案。

## 2026-06-22 Vercel editor audit writable path

- 目的：修正 Vercel mock reader 登入時，`append_audit_event()` 嘗試建立 `/var/task/logs` 而觸發 read-only filesystem，導致 `/v1/auth/vercel-preview-login` 500。
- 主要修改：`api.services.editor_audit.audit_log_path()` 未設定 `SRA_EDITOR_AUDIT_LOG` 且偵測到 Vercel/NOW 環境時，預設改寫入 `/tmp/sra-auth/editor_audit.jsonl`；本地 / 落地部署仍預設使用 repo `logs/editor_audit.jsonl`。
- 驗證：新增 Vercel 預設 editor audit path 測試，並在 Vercel-like mock preview login subprocess 中確認登入後 audit log 寫入 `/tmp` 且含 `vercel_mock_preview` 事件。

## 2026-06-22 Portable auth pack Vercel mock preview login

- 目的：將主系統 Vercel mock preview reader 帳號機制同步到 `portable_auth_pack` 範例包，讓範例頁在 Vercel preview 上也能不建立正式 admin 即測試登入流程。
- 主要修改：portable auth pack 新增 `AUTH_VERCEL_MOCK_MODE`、`/v1/auth/vercel-preview-login-enabled`、`/v1/auth/vercel-preview-login`、`AuthStore.ensure_mock_preview_user()` 與範例 UI「Vercel mock 閱讀者登入」按鈕；mock 帳號為 process-local `portable_mock_reader`，role 為 `data_reader`，無固定密碼。Vercel/NOW 環境未設定 `AUTH_USERS_FILE` 時，預設 runtime state 改放 `/tmp/portable-auth-pack/`。
- 驗證：新增 `tests/test_portable_auth_pack_vercel_mock.py` 覆蓋 enabled / login / disabled 端點；更新 portable static UI 測試；執行 portable auth pack verify script 通過。

## 2026-06-22 GitHub PR conflict mitigation for legacy api paths

- 目的：處理 GitHub PR 顯示 `.codex/memory.md`、`api/routers/editor.py`、`api/static/excel_to_sql_dashboard.html` 衝突且網頁 editor 無法解決的狀況。
- 主要修改：曾短暫恢復 legacy `api/routers/editor.py` 與 `api/static/excel_to_sql_dashboard.html` 為 conflict-resolution mirror，避免與 base branch 對舊路徑的修改形成 delete/modify conflict；`api.__path__` 改為優先搜尋 `sra_api/`，確保 runtime imports 使用 relocated source；`.gitattributes` 對 `.codex/memory.md` 使用 union merge，降低 append-only project memory 的 GitHub merge conflict。
- 驗證：更新 Vercel config/static conflict tests，確認 Vercel 仍保留 `api/index.py` 入口但忽略 legacy dirs，且 `api.routers.editor` import 實際解析到 `sra_api/routers/editor.py`。


## 2026-06-23 Remove legacy api mirror files after conflict mitigation

- 目的：依使用者要求，在 GitHub 上傳 / merge 衝突緩解後移除多餘 legacy mirror files，避免它們再次影響 Vercel upload / function discovery 或造成 source-of-truth 混淆。
- 主要修改：刪除 `api/routers/editor.py`、`api/static/excel_to_sql_dashboard.html`、`api/static/excel_to_sql_dashboard_app.js`，移除 `.vercelignore` 中 legacy mirror 排除項；`api/` 目前只剩 `__init__.py` shim 與 `index.py` entrypoint，runtime source 維持 `sra_api/`。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_static_conflicts.py tests/test_vercel_deploy_config.py -q` 通過；`PYTHONPATH=. python -m py_compile app.py api/__init__.py api/index.py sra_api/routers/editor.py` 通過；`find api -maxdepth 3 -type f | sort` 確認 top-level `api/` 只保留 shim 與 entrypoint。

## 2026-06-23 Editor array add buttons on Vercel

- 目的：回應 Vercel 上 ES 編修界面「新增證據片段 / 新增 Timeline」按鈕點擊無反應的回饋；此行為不正常，按鈕應新增一個可輸入的 array item 格子。
- 主要修改：`editor_form.js` 將 array 新增 / 刪除按鈕明確設為 `type="button"`，事件綁定改用 `getAttribute()` 讀取完整路徑，並新增 `ensureArrayAtPath()` 與錯誤 status，避免既有文件中該 path 暫時不是 array 時點擊靜默失敗。
- 驗證：`node --check sra_api/static/editor_form.js` 通過；`pytest tests/test_editor_auth_ui_static.py -q` 通過（21 passed，3 個既有 warning）。

## 2026-06-23 Vercel mock preview login hardening

- 目的：降低 Vercel demo 用 mock preview reader login 被誤帶到 production 或被公開濫用的風險。
- 主要修改：主系統與 portable auth pack 的 mock preview login 在 `auto` 模式下遇到 production-like 環境（`APP_ENV` / `ENV` / `PY_ENV` 或 `VERCEL_ENV` 為 production）會停用；新增可選 `SRA_VERCEL_PREVIEW_LOGIN_SECRET` / `AUTH_VERCEL_PREVIEW_LOGIN_SECRET` header secret；preview login 加入 per-client-host process-local throttle；mock preview token / user response 標記 `mock_preview: true`；主系統 Editor ES 讀取 endpoint 會拒絕 mock preview token 讀取非 mock ES 資料。
- 文件更新：`.env.example`、`docs/vercel_deploy.md`、`portable_auth_pack/README.md` 與 portable env example 已說明 production fail-safe、preview secret 與正式部署應關閉 mock preview login。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_portable_auth_pack_vercel_mock.py tests/test_vercel_mock_runtime.py -q` 通過（22 passed）；`node --check sra_api/static/editor_auth_nav.js`、`node --check portable_auth_pack/static/login_admin_auth.js` 與相關 Python `py_compile` 通過；`PYTHONPATH=. python portable_auth_pack/scripts/verify_auth_pack.py` 通過（有既有 StarletteDeprecationWarning 與預期 auth.login.failed 測試 log）。

## 2026-06-23 Vercel mock mode env reliance clarification

- 目的：回應使用者疑慮「在 Vercel 上不一定能用環境變數設定 mock mode」，避免 production 安全邊界依賴手動設定 `SRA_VERCEL_MOCK_MODE`。
- 主要修改：移除 `vercel.json` 內的 `SRA_VERCEL_MOCK_MODE=auto`；mock mode 仍由程式預設 `auto` 與 Vercel 內建 `VERCEL_ENV` 判斷，production-like 環境自動停用 mock preview login，不需使用者在 Vercel 手動設定此變數。`vercel.json` 僅保留非機密 `API_STORE_ENABLED=0`。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py tests/test_portable_auth_pack_vercel_mock.py tests/test_vercel_mock_runtime.py -q` 通過；`python -m json.tool vercel.json` 通過。

## 2026-06-23 Restore Vercel mock mode env in vercel.json

- 目的：依使用者更正，Vercel 可透過 `vercel.json` 控制環境變數，因此恢復將 `SRA_VERCEL_MOCK_MODE=auto` 放在 `vercel.json` 作為 preview-friendly 非機密預設值。
- 主要修改：`vercel.json` 重新加入 `SRA_VERCEL_MOCK_MODE=auto`；文件改回說明 Vercel 支援此設定，但 production 安全仍由程式讀取內建 `VERCEL_ENV=production` 後自動停用 mock preview login，而不是單靠手動設定。
- 驗證：更新 `tests/test_vercel_deploy_config.py` 檢查 `vercel.json` 包含 `SRA_VERCEL_MOCK_MODE=auto` 與文件說明。

## 2026-06-23 Preview login secret example placeholders

- 目的：依使用者要求，替 `AUTH_VERCEL_PREVIEW_LOGIN_SECRET` 補上可直接參考的範例套用方式，同步補主系統 `SRA_VERCEL_PREVIEW_LOGIN_SECRET` 範例。
- 主要修改：`.env.example` 使用 `SRA_VERCEL_PREVIEW_LOGIN_SECRET=replace-with-random-preview-secret`；`portable_auth_pack/examples/env.example` 使用 `AUTH_VERCEL_PREVIEW_LOGIN_SECRET=replace-with-random-portable-preview-secret`；文件明確標註這些是 placeholder，公開部署需在 Vercel Project Settings 換成隨機值，不可當真 secret。
- 驗證：更新測試檢查主系統與 portable env example 皆包含 placeholder。

## 2026-06-23 Portable auth preview secret header rename

- 目的：回應 `portable_auth_pack` 範例包不應暴露主系統專用 `SRA` 字樣的疑慮，降低複製到其他專案時的命名干擾。
- 主要修改：portable preview login 對外文件、前端與測試改用通用 `X-Auth-Preview-Login-Secret`；後端保留 `X-SRA-Preview-Login-Secret` 作為相容 fallback，避免既有 preview 環境立即失效。
- 驗證：`PYTHONPATH=. pytest tests/test_portable_auth_pack_vercel_mock.py -q` 通過（5 passed）；`python -m py_compile portable_auth_pack/fastapi_auth_pack/auth_routes.py` 通過；`node --check portable_auth_pack/static/login_admin_auth.js` 通過；`rg "X-SRA-Preview-Login-Secret|X-Auth-Preview-Login-Secret|x_sra_preview_login_secret|x_auth_preview_login_secret" portable_auth_pack tests/test_portable_auth_pack_vercel_mock.py` 確認 portable 對外文件 / 前端 / 測試使用通用 header，legacy SRA header 僅保留在 route 相容 fallback。

## 2026-06-23 Portable auth SRA naming cleanup follow-up

- 目的：依 review 回饋，`portable_auth_pack` 範例包不需保留主系統 `SRA` header 相容分支，避免複製到其他專案時仍看到專有命名。
- 主要修改：移除 portable preview login route 的 `X-SRA-Preview-Login-Secret` / `x_sra_preview_login_secret` fallback，只接受通用 `X-Auth-Preview-Login-Secret`；另以 `rg` 檢查 portable auth pack 與相關測試已無 `SRA` / `sra` / `X-SRA` 等主系統專有字樣。
- 驗證：`PYTHONPATH=. pytest tests/test_portable_auth_pack_vercel_mock.py -q` 通過（5 passed）；`python -m py_compile portable_auth_pack/fastapi_auth_pack/auth_routes.py` 通過；`node --check portable_auth_pack/static/login_admin_auth.js` 通過；`rg -n "SRA|sra|X-SRA|\\.sra|SRA_" portable_auth_pack tests/test_portable_auth_pack_vercel_mock.py || true` 無輸出。

## 2026-06-23 Auth password verification refactor

- 目的：檢查密碼驗證相關程式碼是否集中在過大的單檔；發現主系統與 portable auth pack 的 auth store / support 同時承擔密碼 hash、verify、變更與 reset-password 流程，導致 `auth_store.py` 超過 400 行。
- 主要修改：主系統與 portable auth pack 各新增 `auth_passwords.py` 承接 PBKDF2 hash / verify / password validation / dummy hash；新增 `auth_password_flows.py` 承接 change-password、superuser reset、request reset token、recover password 流程；`AuthStore` 改以 mixin 保留原 public methods，讓 route / tests 呼叫介面不變。
- 驗證：`PYTHONPATH=. pytest tests/test_auth_store_security.py tests/test_portable_auth_pack_vercel_mock.py -q` 通過（25 passed，1 個既有 StarletteDeprecationWarning）；`PYTHONPATH=. python portable_auth_pack/scripts/verify_auth_pack.py` 通過（含既有預期 auth.login.failed log）；`python -m py_compile sra_api/services/auth_passwords.py sra_api/services/auth_password_flows.py sra_api/services/auth_support.py sra_api/services/auth_store.py portable_auth_pack/fastapi_auth_pack/auth_passwords.py portable_auth_pack/fastapi_auth_pack/auth_password_flows.py portable_auth_pack/fastapi_auth_pack/auth_support.py portable_auth_pack/fastapi_auth_pack/auth_store.py` 通過。
