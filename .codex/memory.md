# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；API 與 HTTP endpoint 主要在 `api/`，agent / retrieval / evidence 在 `agent/`，資料匯入與 ETL 在 `data_ingestion/`，設定在 `config/`，測試在 `tests/`。
- Auth 目前採四層階層式 role：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 會正規化為 `data_editor`。新註冊帳號預設 `data_reader` + `pending`，superuser 透過下拉選單核准 / 更新層級。
- 主系統與 `portable_auth_pack` 的 Auth 安全行為需同步：dummy password hash timing balance、登入 / reset-password process-local throttle、production secret fail-fast、generic login failure response。
- Editor / portable auth pack 標題列多層選單採 Word 式方向：上一層向下列出，下一層以右側為展開基準，展開面板內的選項仍固定向下排列；小螢幕保留垂直 fallback。
- Excel→SQL dashboard 標題列會顯示目前登入人員；Editor 使用統計頁除了曲線，也顯示套用相同篩選條件的 audit event 條目。
- 目前環境缺少 Playwright / browser runtime；可視 UI 變更若無法截圖，需以靜態 UI 測試替代，並於 `.codex/known_issues.md` 記錄限制。

## Recent Changes

### 2026-06-12 帳號拒絕操作文案釐清

- 依使用者確認，保留帳號審核 reject 能力，但將 UI / 文件說明改為「拒絕申請／停權」。
- `api/static/editor.html`：帳號審核按鈕、帳號操作篩選與 audit label 改為「拒絕申請／停權」，按鈕 title 說明 pending 帳號會被拒絕申請、active 帳號會被停權且既有 token 失效。
- `portable_auth_pack/static/login_admin_minimal.html` 與 `portable_auth_pack/README.md`：同步按鈕與文件說明。
- `.codex/api_contract.md`：記錄 reject route shape 不變，僅釐清語意。
- Validation：`pytest tests/test_editor_auth_ui_static.py` 通過（11 passed）；`python - <<'PY' ... import playwright ...` 顯示 `No module named 'playwright'`。

### 2026-06-12 多層選單子選項固定垂直排列

- `api/static/editor.html`：桌機版 `.nav-actions` 從 auto-fit 多欄 grid 改為單欄 grid，保留右側 absolute 展開定位。
- `portable_auth_pack/static/login_admin_minimal.html`：`.nav-actions` 改為 `flex-direction: column` 且 `flex-wrap: nowrap`。
- `tests/test_editor_auth_ui_static.py`：補強主系統與 portable auth pack 靜態 UI 斷言。
- Validation：`pytest tests/test_editor_auth_ui_static.py` 通過（11 passed）。

### 2026-06-12 Dashboard 登入人員與使用統計 audit 條目

- `api/static/excel_to_sql_dashboard.html` 標題列新增 `whoami` 顯示目前登入者。
- `GET /v1/editor/usage-stats` 新增 `events_limit` query 與 `filtered.events` / `events_total` / `events_limit` response。
- `api/static/editor.html` 使用統計區新增最近 audit 事件條目。
- Validation：相關 dashboard / editor audit tests 通過，完整 `pytest tests` 曾通過（61 passed，既有 warnings）。

### 2026-06-12 Auth 四層身份分級擴充

- 主系統與 `portable_auth_pack` 從 `user` / `superuser` 擴充為 `data_reader`、`data_editor`、`db_operator`、`superuser`。
- Editor 文件寫入 / 刪除需 `data_editor` 以上；Excel→SQL delete-row 需 `db_operator` 以上；帳號管理維持 `superuser`。
- `GET /v1/auth/me` 與 `GET /v1/auth/users` 回傳 `role_options`；帳號審核 UI 使用 role dropdown。
- Validation：完整 `pytest tests` 曾通過（59 passed，既有 warnings）；`python portable_auth_pack/scripts/verify_auth_pack.py` 曾通過。

### 2026-06-12 Auth 資安補強與 portable_auth_pack 同步

- 主系統與 portable auth pack 同步 dummy hash timing 防護、登入 / reset-password throttle、generic login failure response 與 production secret requirement。
- 文件提醒多 worker / 多 instance 部署需改集中式 rate limiting。
- Validation：Auth security tests、portable verify script 與完整測試曾通過。

### 2026-06-11 Editor 導航、帳號稽核與共用 audit tools

- Editor 標題列改為多層導航，帳號操作紀錄與文件異動紀錄分流。
- 新增 / 同步 `audit_tools.js`，支援共用統計圖、桌機 hover navigation 與觸控 click navigation。
- Backlog 仍保留：日後可抽出共用導航設定、建立正式 static assets 同步機制，並在具備 browser runtime 時補 E2E / screenshot。

## Archived History

- `.codex/archive/memory.md-20260612-032146.md`：歸檔 2026-06-12 03:21 UTC 前的完整 memory 歷史，涵蓋 2026-06-11 至 2026-06-12 的 Editor navigation、Auth security、role hierarchy、dashboard / usage stats 與拒絕操作文案調整細節。

## Compaction Record

- 2026-06-12：因 `.codex/memory.md` 超過 400 行，已將完整內容歸檔至 `.codex/archive/memory.md-20260612-032146.md`，並重寫 active memory 為目前仍有效摘要、最近變更與歸檔索引。
- Validation：`wc -l .codex/memory.md` 確認濃縮後低於 200 行；本次功能驗證仍以 `pytest tests/test_editor_auth_ui_static.py` 為準。
