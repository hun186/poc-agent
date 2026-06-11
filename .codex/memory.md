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

