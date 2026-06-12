# 專案記憶（Project Memory）

## 專案概述

### 專案目標

-

### 主要功能

-

### 技術架構

- 前端：
- 後端：
- 資料庫：
- 部署方式：

### 重要規範

-

---

## YYYY-MM-DD <工作項目名稱>

### 任務目的

-

### 主要修改內容

-

### 驗證結果

-

### 相關檔案

-

### 重要結論

-

---

## 2026-06-11 Editor reset token 複製與頂端收合導航

### 任務目的

- 改善 superuser 產生一次性 reset token 後只能在 alert 中觀看、無法便利複製的問題。
- 將 Editor 功能導航改為頂端且可收合，降低側欄佔用空間。
- 同步更新 `portable_auth_pack` 外帶複製參考包中的最小登入管理頁。

### 主要修改內容

- `api/static/editor.html`：新增 reset token 複製對話框、複製按鈕與 Clipboard API / `execCommand` fallback；移除原本顯示 token 的 `alert`。
- `api/static/editor.html`：將功能導航搬到 app 頂端，以 sticky top nav 與 `<details>` 提供可展開/收合行為，點擊導航後自動收合。
- `portable_auth_pack/static/login_admin_minimal.html`：同步新增可複製 reset token 對話框，讓外帶 auth pack 參考實作一致。
- `tests/test_editor_auth_ui_static.py`：補上靜態測試，確認 editor 與 portable auth pack 都有可複製 token UI，並確認頂端收合導航相關標記存在。

### 驗證結果

- `pytest tests/test_editor_auth_ui_static.py` 通過（5 passed）。
- `pytest tests` 通過（42 passed, 4 warnings）。

### 相關檔案

- `api/static/editor.html`
- `portable_auth_pack/static/login_admin_minimal.html`
- `tests/test_editor_auth_ui_static.py`

### 重要結論

- reset token 改由可選取、可複製的對話框呈現，避免管理者手動抄寫長 token。
- 導航改為頂端 sticky + details 收合，不變更後端 API response shape。

---

---

## 2026-06-11 標題列多層導航更新

### 任務目的

- 將專案系統的主要導航功能放入標題列，讓第一層功能區以大型按鈕呈現。
- 將各功能區的子功能改為可逐層展開與自動收合的選單。
- 同步更新 `portable_auth_pack` 的最小管理頁，保持外帶 auth pack 參考 UI 與專案系統一致。

### 主要修改內容

- `api/static/editor.html`：移除登入後內容區的 card 式 top nav，改為 header 內的多層導航；第一層包含 ES 資料庫、匯入流程、系統管理、帳號安全；第二層使用 `details` 呈現區塊子功能並在選取功能、點擊外部或按 Escape 時自動收合。
- `portable_auth_pack/static/login_admin_minimal.html`：新增 header 內多層導航；第一層包含登入身分、密碼補救、帳號審核；第二層可進入對應表單或觸發既有操作，並支援自動收合。
- `tests/test_editor_auth_ui_static.py`：更新並新增靜態 UI 測試，驗證專案系統與 portable auth pack 的 header 多層導航、ARIA 展開狀態與自動收合函式存在。

### 驗證結果

- `pytest tests/test_editor_auth_ui_static.py` 通過（6 passed）。
- `pytest tests` 通過（43 passed, 4 warnings）。
- 嘗試檢查截圖工具時，環境未安裝 Playwright，因此未執行瀏覽器截圖；已以靜態 UI 測試作為替代驗證。

### 相關檔案

- `api/static/editor.html`
- `portable_auth_pack/static/login_admin_minimal.html`
- `tests/test_editor_auth_ui_static.py`

### 重要結論

- 導航的第一層已固定在標題列內；第二層和後續區塊選單由同一組既有功能事件驅動，未改動後端 API response shape。
- `portable_auth_pack` 與專案系統的 auth/admin 參考頁維持一致的標題列多層導航互動。


---

## 2026-06-11 Editor 導航與功能頁面分離優化

### 任務目的

- 讓標題列導航更接近 Word / 一般文件工具的逐層展開、收合操作感。
- 將 ES 文件異動與帳號操作紀錄分開呈現，避免都以「修改」稱呼造成混淆。
- 導航進入特定功能後，主工作區只顯示當下功能，避免帳號管理頁同時出現 ES 文件編修欄位。

### 主要修改內容

- `api/static/editor.html`：導航第二層選單加入展開箭頭與「展開 / 收合」提示；系統管理選單拆分「文件異動紀錄」與「帳號操作紀錄」。
- `api/static/editor.html`：新增 `workspaceGrid` / `editorCard` 單一工作區切換邏輯；只有搜尋與文件編輯頁顯示 ES 編輯器，其餘帳號、稽核、統計頁改為單欄專注顯示。
- `api/static/editor.html`：新增帳號操作紀錄卡片，將 `auth.*` audit event 與 `editor.*` 文件異動紀錄分流顯示。
- `api/routers/editor.py`：帳號註冊、核准、拒絕、刪除動作補寫入 editor audit log，讓帳號操作紀錄可追蹤實際帳號管理變更。
- `portable_auth_pack/static/login_admin_minimal.html`：同步更新 header 多層導航的展開箭頭與收合文案。
- `tests/test_editor_auth_ui_static.py`：補上靜態測試，驗證工作區分離、帳號 / 文件紀錄分流、帳號管理 audit 寫入點與導航 aria 標記。

### 驗證結果

- `pytest tests/test_editor_auth_ui_static.py` 通過（8 passed）。
- `pytest tests` 通過（45 passed, 4 warnings）。
- 檢查 Playwright 截圖工具時，環境仍未安裝 `playwright`，因此未執行瀏覽器截圖；以靜態 UI 測試與完整 pytest 作為替代驗證。

### 相關檔案

- `api/static/editor.html`
- `api/routers/editor.py`
- `portable_auth_pack/static/login_admin_minimal.html`
- `tests/test_editor_auth_ui_static.py`

### 重要結論

- Editor 目前以導航狀態決定工作區內容：文件搜尋 / 編輯才顯示 ES 編修面板；帳號管理、帳號安全、稽核與統計功能不再混放 ES 文件編修內容。
- 文件異動紀錄限定 `editor.*` 動作；帳號操作紀錄限定 `auth.*` 動作，名稱與實務情境更一致。

---

## 2026-06-11 Editor 導航 hover/touch 與共用稽核統計模組

### 任務目的

- 回應使用者對「像 Word / 一般文件工具」操作感的追問：桌機游標移入可自動展開、移出可自動收合；手機 / 觸控裝置維持點按展開收合，避免 hover 模式在觸控上失效。
- 將文件使用統計、帳號操作統計與 Excel→SQL dashboard 的 audit 曲線圖抽出共用前端模組，避免三處重複實作。
- 讓 Editor 與 portable auth pack 都能以篩選條件查詢統計並顯示統計曲線。

### 主要修改內容

- `api/static/audit_tools.js`：新增共用前端模組，提供 `renderTimeSeriesChart()`、`renderSummaryCards()`、`bindProgressiveNav()` 等函式。
- `api/static/editor.html`：導入共用模組；導航改由 `bindProgressiveNav()` 控制桌機 hover 展開 / 移出收合與觸控點按；使用統計新增類別、使用者、動作、index、起迄時間與曲線區間篩選，並以共用 chart renderer 繪圖。
- `api/static/excel_to_sql_dashboard.html`：改用共用 `SraAuditTools.renderTimeSeriesChart()` 繪製既有 filtered audit 曲線。
- `portable_auth_pack/static/login_admin_minimal.html` 與 `portable_auth_pack/static/audit_tools.js`：範例包也納入共用統計模組，新增帳號操作統計區塊與曲線圖。
- `api/services/editor_audit_queries.py`：新增 `action_prefix` 篩選、chart bucket 正規化與 audit time series 統計。
- `api/routers/editor.py`：提供 `/static/audit_tools.js`；`/v1/editor/usage-stats` 新增統計篩選與曲線資料；`/v1/editor/audit-logs` 新增 `action_prefix` query。
- `tests/test_editor_auth_ui_static.py`、`tests/test_excel_to_sql_dashboard_static.py`、`tests/test_editor_audit_queries.py`：補上共用模組、hover/touch 導航、統計篩選、portable auth pack 與 audit query helper 測試。

### 驗證結果

- `pytest tests/test_editor_auth_ui_static.py tests/test_excel_to_sql_dashboard_static.py tests/test_editor_audit_queries.py` 通過（16 passed）。
- `pytest tests` 通過（50 passed, 4 warnings）。
- 再次檢查 Playwright，環境仍未安裝 `playwright`，無法執行截圖；以靜態 UI 測試與完整 pytest 取代。

### 相關檔案

- `api/static/audit_tools.js`
- `api/static/editor.html`
- `api/static/excel_to_sql_dashboard.html`
- `api/services/editor_audit_queries.py`
- `api/routers/editor.py`
- `portable_auth_pack/static/login_admin_minimal.html`
- `portable_auth_pack/static/audit_tools.js`
- `tests/test_editor_auth_ui_static.py`
- `tests/test_excel_to_sql_dashboard_static.py`
- `tests/test_editor_audit_queries.py`

### 重要結論

- 桌機滑鼠環境會使用 hover progressive nav；手機 / 觸控環境不依賴 hover，而是保留 click / details 原生點按展開收合。
- Audit 統計曲線前端渲染已由 Editor、Excel→SQL dashboard、portable auth pack 共用同一模組。

---

## 2026-06-11 Editor 導航第二層選單修復

Task Purpose:
- 修復電腦版 Editor 標題列可看到第一層功能，但點擊 / hover 後無法叫出第二層子選項的問題。

Main Changes:
- 修正 `api/static/editor.html` 的 `bindHeaderNav()`，將 `SraAuditTools.bindProgressiveNav()` 的 `setActiveRoot` callback 正確綁到既有 `setActiveNavRoot()`，避免瀏覽器執行到未定義變數 `setActiveRoot` 後導致導航事件沒有完成初始化。
- 更新 `tests/test_editor_auth_ui_static.py`，加入防回歸檢查，確認 Editor 靜態頁不再使用未定義的 shorthand callback。

Verification:
- `pytest tests/test_editor_auth_ui_static.py` 通過，10 passed。

Conclusion:
- Editor 導航第二層選單失效原因是前端 callback 名稱錯誤，不涉及後端 API contract 或資料模型變更。

---

## 2026-06-11 專案記憶濃縮機制文件化

### 任務目的

- 回應長期記憶隨多次編修持續膨脹、導致後續 Agent 必須讀取過時冗長內容並浪費 token 的問題。
- 在 `AGENTS.md` 中建立明確的記憶濃縮觸發條件、歸檔流程與濃縮後載入規則。

### 主要修改內容

- `AGENTS.md`：將「僅追加 / 不得覆蓋」調整為一般任務規則，明確允許記憶濃縮作為唯一例外。
- `AGENTS.md`：新增「記憶濃縮機制（Memory Compaction）」章節，定義行數、大小、區塊數、過時內容與重複內容等觸發條件。
- `AGENTS.md`：規範濃縮前全文需保存到 `.codex/archive/`，active memory 重寫為 current summary、recent changes、archived history 等精簡結構。
- `AGENTS.md`：規範一般任務不需讀取 `.codex/archive/`，只有追溯歷史或 active memory 指向特定歸檔時才讀取，以降低 token 消耗。

### 驗證結果

- `git diff --check` 通過。
- 使用 Python 檢查 `AGENTS.md` 已包含記憶濃縮章節與 `.codex/archive/` 歸檔規則。

### 相關檔案

- `AGENTS.md`
- `.codex/memory.md`

### 重要結論

- 專案記憶現在具備可追溯的濃縮例外：一般更新仍採追加；超過門檻或內容過時時，可先歸檔全文再重寫 active memory，避免後續任務重複讀取低價值歷史細節。

---

## 2026-06-12 密碼驗證資安補強

Task:

- 依資安檢視結果補強 Auth 密碼驗證、登入失敗防護、reset token 嘗試限制與 production secret 設定防呆。

Changes:

- `api/services/auth_store.py`：新增固定 dummy PBKDF2 password hash，讓不存在帳號登入也會執行 `_verify_password()`，降低帳號存在與否造成的 timing 差異。
- `api/services/auth_store.py`：新增 in-memory auth failure throttle，依 scope + username + client host 記錄登入 / reset-password 失敗，達 5 次後封鎖 5 分鐘並可清除成功登入後的失敗狀態。
- `api/services/auth_store.py`：production 環境若未設定 `SRA_AUTH_SECRET` / `SECRET_KEY`，或 secret 少於 32 bytes，建立 / 驗證 token 時會 fail fast。
- `api/routers/editor.py`：登入 endpoint 會先檢查 throttle；無效帳密與未啟用帳號都回覆相同泛用 401 訊息；登入與 reset-password 達限制時回 429 並帶 `Retry-After`。
- `api/routers/editor.py`：reset-password endpoint 對失敗 token 嘗試套用相同 throttle，成功後清除該 scope 的失敗狀態，並在 audit event 補上 success / reason。
- `tests/test_auth_store_security.py`：新增 dummy hash timing regression、throttle、production secret、login 429 與 inactive generic response 測試。

Validation:

- `pytest tests/test_auth_store_security.py` 通過（8 passed，3 warnings：既有 TestClient / invalid escape warnings）。
- `pytest tests` 通過（55 passed，5 warnings：既有 TestClient deprecation 與 excel import datetime.utcnow warnings）。

Conclusion:

- 密碼 digest 比對原本已使用 `hmac.compare_digest()`；本次補齊登入流程外層不存在帳號快速返回的 timing 風險，並加入暴力嘗試節流與 production secret 防呆。

---

## 2026-06-12 portable_auth_pack 密碼資安補強

Task:

- 將主系統 Auth 密碼資安補強同步到 `portable_auth_pack` 外帶範例包，避免範例包長期保留舊的 timing / account enumeration 與暴力嘗試風險。

Changes:

- `portable_auth_pack/fastapi_auth_pack/auth_store.py`：新增固定 dummy PBKDF2 hash、production secret fail-fast 與 in-memory auth throttle。
- `portable_auth_pack/fastapi_auth_pack/router.py`：登入與 reset-password 套用 throttle；無效帳密與 pending / inactive 帳號統一回泛用 401；達限制時回 429 與 `Retry-After`。
- `portable_auth_pack/scripts/verify_auth_pack.py`：補驗 dummy hash、production secret、pending 泛用 401、login 429 與 reset-password 429。
- `portable_auth_pack/README.md`、`CODEX_IMPORT_GUIDE.md`、`examples/env.example`：更新外帶導入文件，說明正式環境 secret 要求、dummy hash timing 防護、process-local throttle 與多副本部署注意事項。

Validation:

- `python portable_auth_pack/scripts/verify_auth_pack.py` 通過（顯示 portable_auth_pack verification passed；warning 為既有 FastAPI TestClient / Starlette deprecation）。
- `pytest tests/test_editor_auth_ui_static.py tests/test_auth_store_security.py` 通過（18 passed，3 warnings：既有 TestClient 與 invalid escape warnings）。
- `pytest tests` 通過（55 passed，5 warnings：既有 TestClient deprecation 與 excel import datetime.utcnow warnings）。

Conclusion:

- 外帶 FastAPI Auth Pack 現已與主系統 Auth 安全行為一致：不存在帳號仍走 KDF 驗證、登入 / reset token 暴力嘗試有節流、production secret 有 fail-fast，且外部登入失敗訊息不再洩漏帳號狀態。

## 2026-06-12 Auth 四層身份分級擴充

Task:

- 將主系統與 `portable_auth_pack` 從 `user` / `superuser` 二級身份擴充為四層：`superuser`、`db_operator`、`data_editor`、`data_reader`。
- 帳號審核 UI 改用下拉式選單設定帳號層級，避免每個層級各一顆按鈕。

Changes:

- `api/services/auth_store.py` 與 `portable_auth_pack/fastapi_auth_pack/auth_store.py` 新增 role hierarchy、role 正規化、role options，註冊預設 `data_reader`；legacy `user` alias 正規化為 `data_editor`。
- `api/routers/editor_dependencies.py` 與 portable dependencies 新增 `require_data_editor`、`require_db_operator`、`require_superuser` 階層式權限檢查。
- 主系統 Editor 文件寫入 / 刪除需 `data_editor` 以上；Excel→SQL delete-row 需 `db_operator` 以上；帳號維管維持 `superuser`。
- `GET /v1/auth/me` 與 `GET /v1/auth/users` 回傳 `role_options`；主系統與 portable auth pack 管理 UI 使用下拉選單送出 approve role。
- 更新 portable auth pack README、導入指南、example app 與 verify script；新增測試涵蓋 role hierarchy、legacy role alias、dependency 邊界與下拉 UI 靜態檢查。

Validation:

- `pytest tests`：59 passed，5 warnings（既有 StarletteDeprecationWarning 與 datetime.utcnow deprecation warnings）。
- `python portable_auth_pack/scripts/verify_auth_pack.py`：passed，出現既有 FastAPI TestClient / StarletteDeprecationWarning。
- `python - <<'PY' ... import playwright ...`：輸出 `playwright-not-installed`；因此未做瀏覽器截圖，改以靜態 UI 測試驗證下拉選單。

## 2026-06-12 多層選單右側展開調整

Task:

- 依使用者回饋，將標題列多層選單改成類似 Word：上一層選項仍向下排列，下一層內容在右側展開，避免展開 / 收合時推動上一層選項造成視覺跳動。

Changes:

- `api/static/editor.html`：調整 Editor 標題列選單 CSS，第二層 `.nav-level` 固定在左欄向下排列，第三層 `.nav-actions` 改為 absolute 定位於右側；關閉狀態不佔版面，桌機展開不再改變上一層項目位置。
- `api/static/editor.html`：保留窄螢幕 fallback，720px 以下改回垂直展開，避免右側面板超出可視範圍。
- `portable_auth_pack/static/login_admin_minimal.html`：同步 Auth Pack 外帶頁的多層選單右側展開樣式，維持兩份靜態 UI 行為一致。
- `tests/test_editor_auth_ui_static.py`：新增靜態斷言，驗證主系統與 portable auth pack 都使用左右欄、多層右側 absolute 展開、關閉不顯示內容與窄螢幕 fallback。

Validation:

- `pytest tests/test_editor_auth_ui_static.py` 通過（11 passed）。
- `python - <<'PY' ... import playwright ...` 顯示 `No module named 'playwright'`；目前環境仍無法提供瀏覽器截圖，已用靜態 UI 測試驗證 CSS 與 DOM 行為標記。

Conclusion:

- 桌機多層選單現在採「上一層向下列出、下一層向右展開」的 Word 式視覺模式，展開 / 收合下一層不會改變上一層選項位置；小螢幕仍維持可用的垂直展開。


## 2026-06-12 Dashboard 登入人員與使用統計 audit 條目

Task:

- Excel→SQL 匯入 SQL 監控儀表板標題列需比照入口 / Editor 標題列顯示目前登入人員。
- ES 文件修改統計頁面除了曲線圖，也需在下方顯示套用相同篩選條件的 audit 事件條目，方便直接查看實際修改事件。

Changes:

- `api/static/excel_to_sql_dashboard.html`：標題列新增 `whoami` 顯示區，啟動時使用既有 `sra_editor_token` 呼叫 `/v1/auth/me` 顯示 `username (role)`，失效時顯示登入已失效；並移除重複的 `closeDestinationTableDropdown()` 覆寫，保留可套用 pending 篩選的版本。
- `api/routers/editor.py`：`GET /v1/editor/usage-stats` 新增 `events_limit` query，於 `filtered` 回傳 `events`、`events_total`、`events_limit`，且沿用既有權限規則：非 superuser 只看自己的 audit events。
- `api/static/editor.html`：使用統計區新增 audit 事件筆數輸入與「最近 audit 事件」區塊，曲線圖下方會列出同一篩選條件的事件條目。
- `tests/test_excel_to_sql_dashboard_static.py`、`tests/test_editor_auth_ui_static.py`、`tests/test_editor_audit_queries.py`：補上儀表板登入人員、使用統計事件 UI 與 usage-stats response events 的驗證。
- `.codex/api_contract.md`：記錄 `/v1/editor/usage-stats` 新增 query / response contract。

Validation:

- `pytest tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（19 passed）。
- `pytest tests` 通過（61 passed，5 warnings：既有 FastAPI TestClient / datetime.utcnow deprecation warnings）。
- `python - <<'PY' ... import playwright ...` 顯示 `No module named 'playwright'`；本次可視 UI 變更無法截圖，已同步記錄於 `.codex/known_issues.md` 並以靜態 UI 測試替代。

Conclusion:

- Excel→SQL dashboard 現在可直接在標題列辨識目前登入人員；ES 文件 / 使用統計曲線下方也能看到對應 audit 條目，不必切到另一個紀錄查詢頁才能確認實際修改事件。

## 2026-06-12 多層選單子選項固定垂直排列

Task:

- 依使用者回饋，主系統與 `portable_auth_pack` 的標題列多層選單需維持 Word 式方向：下一層面板以右側為展開基準，但該層內部選項仍固定向下排列，不因第三層以上展開而變成橫向列出。

Changes:

- `api/static/editor.html`：將桌機版 `.nav-actions` 從 auto-fit 多欄 grid 改為單欄 grid，保留右側 absolute 展開定位，但子選項固定垂直向下排列。
- `portable_auth_pack/static/login_admin_minimal.html`：將 `.nav-actions` flex layout 改為 `flex-direction: column` 且不 wrap，同步外帶 auth pack 的子選項垂直排列。
- `tests/test_editor_auth_ui_static.py`：補強靜態 UI 斷言，確認主系統不再使用 nav-actions auto-fit 多欄排列，portable auth pack 使用 column / nowrap。

Validation:

- `pytest tests/test_editor_auth_ui_static.py` 通過（11 passed）。
- `python - <<'PY' ... import playwright ...` 顯示 `No module named 'playwright'`；目前環境仍無法提供瀏覽器截圖，已以靜態 UI 測試驗證 CSS 行為標記。

Conclusion:

- 標題列多層選單現在採「向右展開面板、面板內向下列出選項」的固定方向，降低三層以上選單因橫向 wrap / auto-fit 造成錯亂的風險。

## 2026-06-12 帳號拒絕操作文案釐清

Task:

- 依使用者確認，保留帳號審核的「拒絕」能力，但將功能說明改為「拒絕申請／停權」，讓 pending 申請與 active 帳號停權的語意更清楚。

Changes:

- `api/static/editor.html`：帳號審核按鈕、帳號操作篩選與 audit label 改為「拒絕申請／停權」，並在按鈕 title 說明 pending 帳號會被拒絕申請、active 帳號會被停權且既有 token 失效。
- `portable_auth_pack/static/login_admin_minimal.html` 與 `portable_auth_pack/README.md`：同步外帶頁按鈕與文件說明。
- `.codex/api_contract.md`：記錄 reject route shape 不變，僅釐清語意。

Validation:

- `pytest tests/test_editor_auth_ui_static.py` 通過（11 passed）。
- `python - <<'PY' ... import playwright ...` 仍顯示 `No module named 'playwright'`；本次為文字 UI 調整，沿用靜態 UI 測試替代瀏覽器截圖。
