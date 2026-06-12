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
- 稽核 UI 分成 `#auditCard`（文件異動紀錄，前端只呈現 `editor.*` actions）與 `#accountAuditCard`（帳號操作紀錄，前端只呈現 `auth.*` actions，並保留登入稽核查詢）。
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
