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


---

## 2026-06-11 Editor 功能頁面以導航狀態做單一工作區切換

Decision:

- 保留既有靜態 HTML / vanilla JS 架構，不引入前端框架；由 `switchMainTab()` 統一控制左側功能卡與右側 ES 編輯器是否顯示。
- 只有文件搜尋 / 編修頁顯示 ES 編輯器；其餘功能以單欄工作區呈現。
- 文件異動與帳號操作共用既有 audit log API，但前端依 action prefix 分成 `editor.*` 與 `auth.*` 兩個頁面。

Reason:

- 使用者已具備標題列導航，因此內容區應專注於當下功能，不應在帳號管理時混放 ES 文件編修。
- 文件異動與帳號操作在實務上屬於不同稽核語境，分頁與命名可降低誤解。
- 沿用既有 API 可降低後端 contract 變更與相容性風險。

Implementation:

- `#workspaceGrid.single-pane` 將工作區改成單欄；`#editorCard` 由 `switchMainTab()` 在非文件頁隱藏。
- `#auditCard` 查詢並顯示 `editor.*`；`#accountAuditCard` 查詢並顯示 `auth.*`。
- 帳號管理變更補寫入 `auth.user_*` audit event，避免帳號核准 / 拒絕 / 刪除沒有可查紀錄。

Rejected Alternatives:

- 新增獨立 account audit API：目前既有 audit log 已能承載事件，短期沒有必要增加 API contract。
- 在同一「修改紀錄」頁用篩選下拉混合文件與帳號動作：不符合使用者希望分開處理的需求。

Long-term Consideration:

- 若 audit event 數量大幅增加，可在後端為 `/v1/editor/audit-logs` 增加 category / action_prefix 篩選，避免前端取 500 筆後再分流。

---

## 2026-06-11 共用 audit chart module 與漸進式導航互動

Decision:

- 新增 `api/static/audit_tools.js` 作為輕量 vanilla JS 共用模組，不導入前端框架。
- 導航互動採桌機 hover、觸控 click 的雙模式：只有 `matchMedia('(hover: hover) and (pointer: fine)')` 且 pointerType 為 mouse 時才啟用移入展開 / 移出收合。
- Editor 使用統計、Excel→SQL audit chart、portable auth pack 帳號操作統計共用同一個 SVG chart renderer。

Reason:

- 使用者明確期待一般文件工具常見的 hover 展開體驗，但手機沒有穩定 hover 語意，必須保留點按模式。
- Audit / usage 統計曲線至少出現在三處，抽成共用模組可降低重複與長期分岔。
- 保持單檔靜態頁 + vanilla JS 可延續現有架構，避免過度引入建置流程。

Implementation:

- `bindProgressiveNav()` 同時綁定 click、pointerenter、pointerleave；touch / pen 不觸發 hover 展開邏輯。
- `/v1/editor/usage-stats` 回傳 filtered stats 與 time series，前端只負責呈現與篩選參數組裝。
- Excel dashboard 原 chart function 改為轉呼叫 `SraAuditTools.renderTimeSeriesChart()`。

Rejected Alternatives:

- 純 hover 導航：手機與觸控裝置體驗不可靠。
- 將 chart renderer 分別複製在三個頁面：短期可行但會產生重複維護。
- 立即導入前端框架或 build pipeline：與目前靜態頁架構不一致，超出本次需求。

Long-term Consideration:

- 若共用前端模組持續增加，可再建立正式 `/static/` 掛載或 asset pipeline，並將 portable auth pack 的共用檔納入打包同步流程。

---

## 2026-06-11 長期記憶採 active summary + archive 濃縮模式

Decision:

- 長期記憶平時維持 append-only；當 active memory 超過指定門檻或內容明顯過時、重複時，允許以「先全文歸檔、再重寫 active memory 摘要」作為唯一覆寫例外。
- `.codex/archive/` 不列入例行專案上下文載入，只有追溯歷史或 active memory 指向特定歸檔時才讀取。

Reason:

- 原本要求每次讀取所有長期記憶且只能追加，會讓多次任務後的記憶檔持續膨脹，增加 token 消耗並提高讀到過時資訊的機率。
- active summary 可保留當前有效知識；archive 可保留追溯能力，兼顧效率與可稽核性。

Implementation:

- 在 `AGENTS.md` 新增記憶濃縮觸發條件、歸檔流程、active memory 建議結構與濃縮後載入規則。
- 濃縮前需保存原文到 `.codex/archive/<原檔名>-YYYYMMDD-HHMMSS.md`，並在 active memory 中留下 archived history 索引。

Rejected Alternatives:

- 永久只追加、不濃縮：可追溯性最高，但長期 token 成本會越來越高。
- 直接刪除舊記錄：token 成本最低，但失去追溯與稽核能力。

Long-term Consideration:

- 若記憶檔持續增加，可再建立自動化檢查腳本，在任務結束時提醒哪些 active memory 已超過濃縮門檻。

---

## 2026-06-12 Auth 防 timing 與暴力嘗試節流

Decision:

- 在帳號不存在時仍執行固定 dummy PBKDF2 password verification，避免登入流程因跳過 KDF 產生明顯 timing 差異。
- 登入與 reset-password 採 process-local in-memory throttle，達 5 次失敗後封鎖 5 分鐘，回 HTTP 429 與 `Retry-After`。
- 對外收斂登入失敗訊息：無效帳密與 inactive / pending / rejected 帳號都回泛用 401；內部 audit 保留詳細 reason。
- production 環境要求明確設定至少 32 bytes 的 token secret，禁止使用 development fallback。

Reason:

- 原本 digest 比對已使用 constant-time compare，但帳號不存在時直接返回，仍可能被用於 account enumeration。
- 僅靠 audit 無法阻擋暴力嘗試；輕量 throttle 可在不引入外部依賴的前提下降低風險。
- 對外錯誤訊息收斂可降低帳號狀態列舉；保留 audit reason 則維持管理與調查能力。
- 固定 development secret 適合本機，但 production 若未設定 secret 會讓 token 簽章安全性不足。

Implementation:

- `DUMMY_PASSWORD_HASH` 使用固定 salt 產生，僅用於不存在帳號的驗證時間平衡，不代表任何真實帳號。
- `AuthStore.record_auth_failure()` / `throttle_retry_after()` / `clear_auth_failures()` 管理登入與 reset-password 的失敗狀態。
- Router 在達 throttle 時丟出 HTTP 429，並在成功登入 / 成功重設密碼後清除相同 scope 的失敗狀態。

Rejected Alternatives:

- 引入 Redis / database-backed distributed rate limiter：較適合多 instance production，但超出本次小範圍後端補強；目前先採 process-local 節流。
- 對 inactive account 維持 403 與明確狀態訊息：UX 較清楚，但會暴露帳號存在與狀態。

Long-term Consideration:

- 若部署為多 worker / 多 instance，應將 throttle state 移到 Redis、database 或 API gateway / WAF rate limiting，避免每個 process 獨立計數。
- 可進一步加入 superuser MFA、管理員高風險操作 re-authentication、CSP 與 localStorage token XSS 風險降低措施。

---

## 2026-06-12 portable_auth_pack 同步主系統 Auth 資安行為

Decision:

- 將主系統 Auth 的 dummy hash timing 防護、登入 / reset-password throttle、generic login failure response 與 production secret fail-fast 同步到 `portable_auth_pack`。
- 外帶包保留 process-local throttle，並在 README / Codex import guide 明確提醒多 worker / 多副本正式部署需改集中式 rate limiting。

Reason:

- portable auth pack 是未來導入其他專案的參考素材；若保留舊行為，會把已知 timing / account enumeration 風險複製到新專案。
- 外帶包需保持低依賴與可複製性，因此不直接引入 Redis / DB rate limiter，但需把限制寫入文件。

Implementation:

- `verify_auth_pack.py` 同時驗證功能流程與新增安全行為，包含 pending user 泛用 401、login/reset-password 429 與 production secret requirement。

Long-term Consideration:

- 若 portable auth pack 日後成為正式可安裝套件，應提供可插拔 throttle backend 介面，而不是只內建 process-local memory。
