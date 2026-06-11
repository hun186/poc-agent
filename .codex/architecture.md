# architecture


---

## 2026-06-11 前端標題列多層導航

- `api/static/editor.html` 是 Editor / 管理系統的靜態前端入口；登入後的主要功能導航位於 `<header>` 內的 `#mainNav`。
- `#mainNav` 的第一層功能區使用 `data-nav-root` 大型按鈕切換，包括 ES 資料庫、匯入流程、系統管理與帳號安全。
- `#navSubPanel` 依 `data-nav-menu` 顯示對應第二層選單；各第二層區塊使用 `<details class="nav-level">` 逐層展開子功能，選取功能後呼叫既有 `switchMainTab()` / `newDoc()` / dashboard 導向邏輯。
- `portable_auth_pack/static/login_admin_minimal.html` 保留單檔最小 Auth 管理頁定位，並同步採用 header 內 `#authPackNav`、`data-nav-root`、`data-nav-menu` 的多層導航結構。

