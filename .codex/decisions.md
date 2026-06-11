# 技術決策（Technical Decisions）

## YYYY-MM-DD <決策名稱>

Decision:

Reason:

Implementation:

Rejected Alternatives:

Long-term Consideration:

---

## 2026-06-11 Reset token 呈現改用可複製對話框

Decision:

- Superuser 產生 reset token 後，不再用瀏覽器 `alert` 呈現；改用自訂 modal，內含 readonly textarea 與複製按鈕。

Reason:

- `alert` 內容不易複製，長 token 手動輸入不實際且容易出錯。

Implementation:

- Editor 與 portable auth pack static page 皆使用 `navigator.clipboard.writeText`，並保留 textarea + `document.execCommand('copy')` fallback。

Rejected Alternatives:

- 只把 token 寫到狀態區：容易被其他輸出覆蓋，且缺少一次性顯示的明確情境。
- 繼續使用 `alert`：無法解決複製問題。

Long-term Consideration:

- 若後續導入正式通知管道，可將 modal 當作人工交付的 fallback UI。

---

## 2026-06-11 Editor 導航改為頂端 sticky 可收合

Decision:

- Editor 功能導航移到 app 頂端，使用 sticky top nav 與 `<details>` 控制展開/收合；點選導航後自動收合。

Reason:

- 側欄導航會壓縮搜尋與管理卡片空間；頂端收合可保留入口又減少佔用。

Implementation:

- `#mainNav` 加上 `top-nav` class，內容包在 `#mainNavDetails` 中；導航 click handler 呼叫 `collapseMainNav()`。

Rejected Alternatives:

- 以大型固定側欄保留原設計：不符合頂端自動收合需求。
- 使用純 hover 展開：觸控裝置體驗較差。

Long-term Consideration:

- 若導航項目持續增加，可再改為分層 dropdown 或 command palette。

---

---

## 2026-06-11 第一層導航放入標題列並以多層選單承載子功能

Decision:

- 將 Editor 與 portable auth pack 的第一層功能入口放入標題列，以大型按鈕呈現；子功能以可逐層展開的選單承載，並在選取功能、點擊外部或按 Escape 時自動收合。

Reason:

- 標題列第一層入口可讓主要系統區塊常駐且清楚；逐層選單可避免一次展開所有子功能造成版面擁擠。

Implementation:

- 使用 `data-nav-root` 管理第一層 active 狀態，使用 `data-nav-menu` 顯示對應子選單，使用 `<details class="nav-level">` 提供逐層進入與收合。
- 導航子功能仍呼叫既有前端函式與 API，不新增後端 contract。

Rejected Alternatives:

- 延續登入後內容區 card 導航：不符合「第一層大按鈕做在標題列內」需求。
- 一次性 mega menu 展開所有子功能：不符合多層逐層進入需求，且在小螢幕更擁擠。

Long-term Consideration:

- 若功能數量持續增加，可把導航結構抽成資料陣列或共用元件，降低 Editor 與 portable auth pack 的靜態 HTML 重複。

