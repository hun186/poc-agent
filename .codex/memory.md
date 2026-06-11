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
