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

## 2026-06-12 Auth 採四層階層式 Role

Decision:

- 將原本 `user` / `superuser` 二分擴充為 `data_reader`、`data_editor`、`db_operator`、`superuser` 四層階層式 role。
- 新註冊帳號預設為 `data_reader` pending；superuser 核准時透過下拉選單指定 role。
- 舊 `user` role 僅作為相容輸入與既有資料 alias，正規化為 `data_editor`，以保留原本普通 user 可編修資料的行為。

Reason:

- 使用者需求明確要求一般場景有「全能者、資料庫操作者、資料修改者、資料閱讀者」四層權限。
- 階層式比較可重用於 endpoint dependency，避免每個 endpoint 寫死 role list。
- 保留 legacy `user` alias 可降低既有 `.sra_users.json` 或外帶範例包使用者資料的升級風險。

Implementation:

- 主系統與 portable auth pack 各自加入 role constants、`normalize_role()`、`has_role_at_least()`、`public_role_options()`。
- Editor dependencies 新增 `require_data_editor` / `require_db_operator` / `require_superuser`；portable pack 同步輸出對應 dependencies。
- 文件寫入 / 刪除改需 `data_editor` 以上；Excel→SQL delete-row 改需 `db_operator` 以上；帳號管理仍需 `superuser`。
- 帳號審核 UI 改以 role dropdown + 單一「核准 / 更新層級」按鈕送出。

---

## 2026-06-12 多層導航 hover grace 與前端分頁

Decision:

- 多層導航採 CSS hover bridge 搭配 JS 延遲收合，而非立即在 `pointerleave` 關閉 details 子選單。
- audit / 帳號清單在現有 API 回傳範圍內加入前端分頁；流程為後端既有條件篩選 → 前端依時間或帳號排序 → 前端分頁顯示。

Reason:

- 使用者從目前層級移往右側下一層時會經過一小段空白；立即收合導致需要快速移動滑鼠，操作不友善。
- 既有 API 已提供 limit / prefix / filter 能力；本次需求重點是 UI 在大量資料時不要一次渲染過長清單，因此先採低風險 client-side pagination。

Implementation:

- `SraAuditTools.bindProgressiveNav()` 保留 hover-only 行為，但預設 close delay 改為 360ms，並針對每個 `.nav-level` 以 WeakMap 管理延遲收合 timer。
- `.nav-level[open]::after` 補上層級間的透明 hover bridge；手機版停用 bridge，維持原本垂直展開操作。
- `SraAuditTools.paginateRows()` 提供主系統與 portable_auth_pack 共用的分頁資料切片與頁碼資訊。

Long-term Consideration:

- 若 audit 總量超過單次 API limit 仍需要完整跨頁，可進一步把 Editor audit API 擴充成 server-side total/page/page_size，與 Excel→SQL dashboard 的 `recent_paging` 模式一致。

## 2026-06-14 Editor HTML 拆分為 shell + static assets

Decision:

- 將肥大的 `api/static/editor.html` 拆成 HTML shell、`api/static/editor.css` 與多個依責任切分的 Editor JS（`editor_core.js`、`editor_form.js`、`editor_auth_nav.js`、`editor_stats.js`、`editor_audit.js`、`editor_documents.js`、`editor_bootstrap.js`），但維持既有 vanilla HTML / CSS / JS 架構與 API contract 不變。

Reason:

- 原單檔接近 1400 行，混合 DOM、樣式與行為，後續修改容易產生大範圍衝突且不利於獨立語法檢查。
- 專案目前沒有前端 build pipeline；直接拆成 FastAPI static assets 是最小風險重構。

Implementation:

- HTML shell 以 cache-busting query 載入 `/static/editor.css?v=20260614-split` 與多個 `/static/editor_*.js?v=20260614-split` script；script 以 classic script 順序載入，避免引入 build step。
- 靜態 UI 測試 helper 將 HTML、CSS、JS 合併後執行既有字串斷言，並新增 shell asset reference 測試。

Rejected Alternatives:

- 導入 bundler 或前端框架：超出本次拆檔重構需求，且與現有靜態頁架構不一致。
- 僅整理同一 HTML 檔內區塊：無法實質降低單檔大小。

Long-term Consideration:

- 若 portable auth pack 與主系統靜態頁持續膨脹，可比照此模式逐步拆出 CSS / JS，並建立簡易 asset 同步或檢查腳本。

## 2026-06-14 portable_auth_pack 同步採用 shell + static assets

Decision:

- 在拆分主系統 Editor 靜態頁後，同步將 `portable_auth_pack/static/login_admin_minimal.html` 拆成 HTML shell、`login_admin_minimal.css` 與 `login_admin_minimal.js`。

Reason:

- portable auth pack 與主系統 Editor 有相同的靜態頁膨脹與長期分岔風險；只拆主系統會讓兩邊維護模式不一致。
- portable pack 不應引入 build pipeline；相對路徑 static assets 可維持可攜式部署方式。

Implementation:

- portable HTML shell 以相對路徑載入 `login_admin_minimal.css?v=20260614-split` 與 `login_admin_minimal.js?v=20260614-split`。
- 靜態 UI 測試新增 `_portable_auth_pack_html()` helper，將 portable shell、CSS、JS 合併後驗證既有行為字串，並新增 shell asset reference 測試。

Rejected Alternatives:

- 保留 portable auth pack 單檔：會與 Editor 拆檔決策不一致，且無法獨立檢查 portable JS。
- 改用與主系統共用同一個 CSS / JS 檔：portable pack 需保持可獨立搬移，直接共用主系統 asset 會降低可攜性。

Long-term Consideration:

- 後續若兩邊 navigation / pagination helper 繼續重複，可評估抽出可同步的共用 source，再由簡單腳本複製到 portable pack。


## 2026-06-14 Editor JS 再拆分為責任導向小檔

Decision:

- 不保留 1007 行的單一 `api/static/editor.js`；改依功能切分為 `editor_core.js`、`editor_form.js`、`editor_auth_nav.js`、`editor_stats.js`、`editor_audit.js`、`editor_documents.js`、`editor_bootstrap.js`，並由 HTML shell 依相依順序載入。

Reason:

- 只把 inline JS 移到單一 `editor.js` 雖可獨立語法檢查，但仍是大型單檔，未充分降低維護與 review 成本。
- 專案仍維持無 build pipeline；多個 classic script 是目前最小變更且瀏覽器相容的拆分方式。

Implementation:

- `editor_core.js` 提供 shared state / helpers / API wrapper；`editor_form.js` 管表單 schema/render/collect；`editor_auth_nav.js` 管 auth、header nav 與 boot；`editor_stats.js` 管 usage stats、多選與 pager；`editor_audit.js` 管 audit logs；`editor_documents.js` 管搜尋、文件 CRUD、帳號管理與檔案抽文；`editor_bootstrap.js` 管 DOM event binding。
- `tests/test_editor_auth_ui_static.py` 驗證 HTML shell 載入所有 `EDITOR_SCRIPT_FILES`，確認不再載入 `editor.js`，並檢查每個 Editor JS 檔低於 350 行。

Rejected Alternatives:

- 直接導入 ES modules：需調整全域函式互相引用方式與可能的載入語意，超出本次小範圍拆檔。
- 使用 bundler：目前沒有前端建置流程，導入成本高於收益。

Long-term Consideration:

- 若後續需要更嚴格邊界，可再把 classic scripts 漸進轉成 ES modules，並新增瀏覽器層級 smoke test 驗證載入順序。

## 2026-06-14 portable_auth_pack JS 同步責任導向拆分

Decision:

- 不保留單一 `portable_auth_pack/static/login_admin_minimal.js`；改依功能切分為 `login_admin_core.js`、`login_admin_auth.js`、`login_admin_audit.js`、`login_admin_stats.js`、`login_admin_admin.js`、`login_admin_bootstrap.js`，並由 portable HTML shell 依相依順序載入。

Reason:

- Editor JS 已從單一大型檔改為責任導向小檔；portable auth pack 若仍保留單一行為檔，兩邊維護模式會再次分岔。
- portable pack 仍需保持可直接搬移與無 build pipeline，因此採相對路徑 classic scripts。

Implementation:

- `login_admin_core.js` 提供 state、navigation、API wrapper 與 payload helpers；`login_admin_auth.js` 管登入 / 註冊 / 密碼流程；`login_admin_audit.js` 管 login audit 與 pager；`login_admin_stats.js` 管帳號統計與使用者多選；`login_admin_admin.js` 管帳號管理、角色下拉與 reset token modal；`login_admin_bootstrap.js` 管 DOM event binding。
- `tests/test_editor_auth_ui_static.py` 新增 `PORTABLE_AUTH_PACK_SCRIPT_FILES`，驗證 shell 載入所有 portable JS 檔、確認不再載入 `login_admin_minimal.js`，並檢查每個 portable JS 檔低於 200 行。

Rejected Alternatives:

- 保留 `login_admin_minimal.js`：雖然目前行數不如 Editor 大，但與新拆分模式不一致。
- 導入 ES modules 或 bundler：會增加 portable pack 移植成本。

Long-term Consideration:

- 後續可評估將 Editor / portable 的共用 pager、multi-filter、navigation helper 以 source-of-truth + copy script 管理，減少兩邊手動同步。

## 2026-06-14 註冊防帳號列舉與 IP 節流

Decision:

- `POST /v1/auth/register` 對外不再回「帳號已存在」，改以成功與重複帳號相同的泛用 200 訊息回應。
- 註冊申請新增 process-local per-IP 節流，並將帳號操作 audit event 補上 `client_host`。
- 主系統與 `portable_auth_pack` 同步上述安全行為。

Reason:

- 明確的「帳號已存在」可被攻擊者用於 account enumeration；泛用回應能降低公開 API 洩漏帳號存在性的風險。
- 創帳號無頻率限制會增加濫用、撞帳號名稱與資源消耗風險；輕量 per-IP 節流可先降低 PoC / 小型部署風險。
- IP / client host 是帳號操作資安檢核與事件追查的必要欄位。

Implementation:

- 主系統註冊 route 捕捉 duplicate username，寫入 `auth.user_registered` audit event 的 `reason=duplicate_username`，但 response 與成功申請一致。
- `portable_auth_pack` 註冊 route 將成功 / duplicate / invalid / rate-limited 註冊結果寫入 login audit reason，並保留 `client_host` / `user_agent`。
- 註冊節流復用現有 in-memory auth throttle state，以 `scope=register`、`username=None`、`client_host` 作為 key。

Rejected Alternatives:

- 對 duplicate username 回 HTTP 409：語意清楚但會直接暴露帳號存在性。
- 立即導入 Redis / database-backed distributed register limiter：較適合多 instance production，但超出本次小範圍補強。

Long-term Consideration:

- 多 worker / 多 instance production 仍應使用 Redis、database、API gateway 或 WAF 做集中式 rate limiting，避免各 process 計數分散。
