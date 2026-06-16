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
