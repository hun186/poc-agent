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
