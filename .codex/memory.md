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
