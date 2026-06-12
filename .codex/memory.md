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

---

## 2026-06-12 導航 hover 容錯與 audit/client-side 分頁

Task:

- 改善主系統 Editor 與 portable_auth_pack 的多層導航 hover 操作，避免游標通過層級間空白時子選單過早收合。
- 為主系統 audit 相關清單與 portable_auth_pack 帳號 / 登入稽核清單加入前端分頁，採「先由既有查詢篩選、再依時間或帳號排序、最後分頁顯示」。

Changes:

- `api/static/audit_tools.js` / `portable_auth_pack/static/audit_tools.js`：延長導航離開容錯時間、加入每個 details 子層級的延遲收合 timer，並新增共用 `paginateRows()`。
- `api/static/editor.html`：第二層導航加入 hover bridge；文件異動、帳號操作、登入稽核、使用統計 audit 事件加入分頁控制與時間排序。
- `portable_auth_pack/static/login_admin_minimal.html`：第二層導航加入 hover bridge；帳號清單先依 username 排序後分頁；登入稽核先依時間排序後分頁並以清單呈現。
- `tests/test_editor_auth_ui_static.py`：補上導航容錯、主系統 audit 分頁、portable_auth_pack 分頁的靜態驗證。

Verification:

- PASS: `node --check api/static/audit_tools.js`
- PASS: `node --check /tmp/editor.html.js && node --check /tmp/login_admin_minimal.html.js`（由 HTML script block 抽出後檢查語法）
- PASS: `pytest tests/test_editor_auth_ui_static.py tests/test_excel_to_sql_dashboard_static.py`
- PASS: `pytest tests`（64 passed；僅既有 warning：Starlette/httpx deprecation、Python 3.14 invalid escape sequence warnings、`datetime.utcnow()` deprecation）

Conclusion:

- 主系統與 portable_auth_pack 的 hover 子選單現在對游標移動較寬容，不需刻意快速移動到下一層。
- 大量 audit / 帳號清單可在前端分頁瀏覽；既有後端查詢負責篩選，前端再排序與切頁。
