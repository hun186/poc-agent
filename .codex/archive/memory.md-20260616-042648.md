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

## 2026-06-12 使用統計分頁工具相容性修正

- 目的：修正 Editor 使用統計 / audit 分頁在瀏覽器載入舊版 `audit_tools.js` 時出現 `SraAuditTools.paginateRows is not a function` 的前端錯誤。
- 主要修改：`api/static/editor.html` 與 `portable_auth_pack/static/login_admin_minimal.html` 的共用工具 script 加入版本 query 以避開舊快取；分頁呼叫改經由 `paginateAuditRows()`，當共享 `SraAuditTools.paginateRows` 尚未載入或為舊版缺少函式時，回退到同 shape 的本地 `localPaginateRows()`。
- 驗證：執行 `pytest tests/test_editor_auth_ui_static.py tests/test_excel_to_sql_dashboard_static.py` 通過 18 項；執行 `pytest tests` 通過 64 項，僅保留既有 Starlette / SyntaxWarning / datetime.utcnow deprecation warnings。
- 結論：使用統計曲線與 audit 條目分頁仍優先使用共用工具；舊瀏覽器快取或部署期間短暫資產不同步時不會再因 `paginateRows` 缺失中斷頁面操作。

## 2026-06-12 前端分頁加入首頁、末頁與跳頁

- 目的：改善 audit / 使用統計 / 帳號清單前端分頁，避免頁數很多時只能反覆點「下一頁」才能到目標頁。
- 主要修改：`api/static/editor.html` 的文件異動、帳號操作、登入稽核與使用統計 audit 事件分頁，以及 `portable_auth_pack/static/login_admin_minimal.html` 的帳號清單與登入稽核分頁，皆加入「首頁」、「末頁」、頁碼輸入與「跳至頁數」；Enter 也可從頁碼輸入框直接跳頁。分頁更新時會同步禁用不可用的首頁 / 上一頁 / 下一頁 / 末頁按鈕，並將輸入框 max/value 更新為目前頁資訊。
- 驗證：執行 `pytest tests/test_editor_auth_ui_static.py` 通過 14 項；執行 `pytest tests` 通過 64 項，僅有既有 warning。
- 截圖限制：本次為可視 UI 變更，但 `python -m playwright --version` 顯示環境未安裝 Playwright，無法補互動式截圖；已以靜態 UI 測試驗證新增控制元件與綁定邏輯。


## 2026-06-12 移除主系統重複登入稽核區塊

- 目的：系統管理的帳號操作紀錄查詢已可透過帳號動作篩選 `auth.login` 等帳號事件，因此移除同頁下方重複的「登入稽核」查詢 UI，避免使用者在兩個區塊查同類紀錄。
- 主要修改：`api/static/editor.html` 移除登入稽核標題、limit input、查詢按鈕、結果列表、分頁與相關前端狀態 / render / API 呼叫；保留帳號操作紀錄查詢作為主系統帳號事件入口。`tests/test_editor_auth_ui_static.py` 改驗證主系統不再出現重複登入稽核控制，且帳號操作動作篩選仍包含登入。
- 驗證：執行 `pytest tests/test_editor_auth_ui_static.py` 通過；執行 `pytest tests` 通過（64 passed，僅既有 warnings）；執行 `node --check /tmp/editor.html.js` 通過（由 `api/static/editor.html` script block 抽出後檢查語法）；嘗試 `python -m playwright --version` 確認目前環境未安裝 Playwright，無法補瀏覽器截圖，已記錄於 known issues。
- 結論：主系統帳號相關查詢集中在帳號操作紀錄查詢；portable_auth_pack 的獨立登入稽核頁面未變更。

## 2026-06-14 本地時間顯示與紀錄查詢導覽調整

- 目的：將紀錄 / 統計的時間呈現改為瀏覽器本地時間，並整理重複的「系統管理 → 紀錄查詢」導覽。
- 主要修改：`api/static/editor.html` 將 ES 資料庫導覽改為「文件異動紀錄 → 使用統計」，移除系統管理下的「紀錄查詢」入口；帳號安全下新增帳號操作紀錄、我的使用統計與 superuser 專屬全體使用統計入口。使用統計頁標題改為「統計與檢核曲線儀表板」，並以本地時間顯示事件時間。
- 後端契約：`GET /v1/editor/usage-stats` 接受 `timezone_offset_minutes`，統計曲線分桶可依用戶端本地時區偏移計算；一般使用者仍限定自己的紀錄，superuser 可看全體統計。
- 驗證：`node --check /tmp/editor.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（19 passed，2 個既有 SyntaxWarning）；`pytest tests` 通過（65 passed，既有 Starlette / datetime.utcnow warnings）。
- 截圖限制：本次為可視 UI 導覽與文字調整，但目前環境仍缺少 Playwright / browser runtime，未執行截圖驗證；以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-14 一般使用者自己的帳號操作紀錄

- 目的：回覆並修正「一般使用者是否能看自己的帳號操作紀錄」的權限落差。
- 主要修改：`GET /v1/editor/audit-logs` 改為 active user 可呼叫；非 superuser 僅允許查詢 `auth.` 帳號操作紀錄，且後端強制 `username` 為目前登入者，無法透過 query 讀取他人或文件異動紀錄。superuser 維持原本可查全體紀錄。
- 前端調整：`帳號安全` 導覽下的帳號操作入口改為「我的帳號操作紀錄」並開放一般使用者；「全體使用統計」仍保留 `data-superuser-only`。
- 驗證：`node --check /tmp/editor.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（21 passed，2 個既有 SyntaxWarning）；`pytest tests` 通過（67 passed，既有 Starlette / datetime.utcnow warnings）。

## 2026-06-14 portable_auth_pack 帳號稽核同步

- 目的：同步主系統帳號操作自助查詢與本地時間顯示，避免 `portable_auth_pack` 作為其他專案參考時仍保留「登入稽核僅 superuser 可查」或 UTC 顯示的舊示範。
- 主要修改：`portable_auth_pack/fastapi_auth_pack/router.py` 的 `GET /v1/auth/login-audit` 改為 active user 可查；一般使用者固定只能查自己的 login audit，superuser 可查全體或用 `username` 篩選。`portable_auth_pack/static/login_admin_minimal.html` 改為「我的登入稽核」，登入稽核時間以瀏覽器本地時間顯示，帳號統計示範也帶 `timezone_offset_minutes`。
- 文件 / 驗證：更新 `portable_auth_pack/README.md` 與 `CODEX_IMPORT_GUIDE.md`；`portable_auth_pack/scripts/verify_auth_pack.py` 新增一般使用者自查登入稽核驗證。
- 驗證：`pytest tests/test_editor_auth_ui_static.py` 通過；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過（僅既有 Starlette/httpx warning）；`node --check /tmp/login_admin_minimal.html.js && node --check /tmp/editor.html.js` 通過；`pytest tests` 通過（67 passed，既有 warnings）。


## 2026-06-14 帳號操作記錄導航與統計儀表板分流

- 目的：整理帳號安全導航，移除導覽層級中的「我的使用統計 / 全體使用統計」重複入口，讓帳號操作記錄保留為單一入口，並由頁面內按鈕切換我的 / 全體統計。
- 主要修改：`api/static/editor.html` 的帳號安全 → 密碼與登入只保留「變更密碼」與「帳號操作記錄」；帳號操作記錄查詢新增起始 / 結束日期篩選與「統計與檢核曲線儀表板」頁內入口。統計儀表板依導覽來源限制統計類別：帳號來源只顯示帳號操作記錄使用統計並隱藏 Index；ES 文件來源只顯示 ES 文件異動紀錄使用統計，移除全部操作使用統計。
- `api/static/editor.html` 與 `portable_auth_pack/static/login_admin_minimal.html` 的第二層選單面板會依目前第一層按鈕位置設定 `--nav-panel-left`，不再固定於同一位置。
- `portable_auth_pack/static/login_admin_minimal.html` 同步將密碼管理導覽中的「我的登入稽核 / 帳號統計」整理為「帳號操作記錄」，並保留統計區頁內篩選按鈕。
- 驗證：`node --check api/static/audit_tools.js`、`node --check /tmp/editor.html.js`、`node --check /tmp/login_admin_minimal.html.js`、`pytest tests/test_editor_auth_ui_static.py`、`pytest tests` 通過；可視截圖仍受 Playwright 未安裝限制。

## 2026-06-14 帳號操作紀錄儀表板與 portable_auth_pack 同步

- 目的：比照 ES 文件異動紀錄查詢，讓帳號操作紀錄查詢可進入統計與檢核曲線儀表板，並用頁面內「我的帳號操作紀錄」與「全體帳號操作紀錄」切換統計範圍；一般使用者不得查看全體帳號操作紀錄。
- 主要修改：`api/static/editor.html` 的使用統計儀表板依來源切換按鈕文字，帳號來源會固定統計類別為 `account`，切到「我的」時強制以目前登入帳號作為 username query；「全體」仍只對 superuser 顯示 / 生效。
- `portable_auth_pack` 同步新增帳號操作統計切換按鈕與 `/v1/editor/usage-stats` 相容 endpoint，統計來源為 login audit，且一般使用者一律限制自己的紀錄，superuser 才可查全體或指定帳號。
- 驗證：`node --check /tmp/editor.js && node --check /tmp/portable.js && python -m py_compile portable_auth_pack/fastapi_auth_pack/router.py` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（21 passed）；`pytest tests` 通過（67 passed，既有 5 warnings）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過（僅既有 StarletteDeprecationWarning）。

## 2026-06-14 統計儀表板使用者清單篩選

- 目的：將「統計與檢核曲線儀表板」的使用者篩選由單一關鍵字輸入改為清單勾選，避免 A 帳號 ID 是 B 帳號 ID 子字串時，被部分比對一起帶入。
- 主要修改：`api/static/editor.html` 新增使用者多選清單、關鍵字篩選、勾選目前篩選、清除目前篩選與清除全部；`portable_auth_pack/static/login_admin_minimal.html` 同步帳號操作統計的帳號多選清單；`api/services/editor_audit_queries.py` 將 username filter 改為 exact match，並支援逗號分隔多帳號。
- 驗證：`node --check /tmp/editor.js`、`node --check /tmp/portable.js` 通過；`pytest tests/test_editor_audit_queries.py tests/test_editor_auth_ui_static.py` 通過（22 passed）；`pytest tests` 通過（68 passed，既有 warnings）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過。
- 截圖限制：本次屬可視 UI 變更；環境執行 `python -m playwright --version` 仍回報 `No module named playwright`，因此未提供瀏覽器截圖，沿用既有 known issue 與靜態測試替代。

## 2026-06-14 統計使用者關鍵字篩選清單修正

- 目的：修正主系統「統計與檢核曲線儀表板」與 `portable_auth_pack` 帳號操作統計的使用者 / 帳號關鍵字篩選清單顯示「沒有符合關鍵字」或「找不到使用者」的問題。
- 主要修改：主系統 superuser 重新整理帳號清單時同步呼叫 `setUsageStatsUserOptions()`，讓統計儀表板的使用者多選清單以真實帳號清單建立；`portable_auth_pack` 在更新目前登入者時重新 seed 帳號統計選項，確保至少包含目前使用者，後續 superuser 重新整理帳號後仍會納入全體帳號清單。
- 驗證：`node --check /tmp/editor.html.js && node --check /tmp/login_admin_minimal.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py -q` 通過（23 passed，2 個既有 SyntaxWarning）；`pytest tests -q` 通過（69 passed，5 個既有 warning）。
- 結論：統計曲線儀表板的關鍵字篩選不再因使用者選項未初始化而顯示找不到使用者；清單會從帳號資料或目前登入者補齊。

## 2026-06-14 使用者多選窗格外點擊收合

- 目的：改善主系統「統計與檢核曲線儀表板」與 `portable_auth_pack` 帳號操作統計的使用者 / 帳號多選窗格互動；點擊窗格外部時自動收合，但保留已勾選狀態與 hidden username 值，避免誤點造成篩選狀態遺失。
- 主要修改：新增 `bindMultiFilterOutsideDismiss()`，只在 click target 不屬於目前 `<details>` picker 且 picker 已開啟時移除 `open`；主系統綁定 `usageStatsUsernamePicker`，portable auth pack 綁定 `accountStatsUsernamePicker`。
- 驗證：`node --check /tmp/editor.html.js && node --check /tmp/login_admin_minimal.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py -q` 通過（23 passed，2 個既有 SyntaxWarning）；`pytest tests -q` 通過（69 passed，5 個既有 warning）。
- 截圖限制：本次為可視 UI 互動改善；目前環境仍未安裝 Playwright（`python -m playwright --version` 回報 `No module named playwright`），因此以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-14 統計儀表板個人紀錄使用者篩選提示

- 目的：避免統計與檢核曲線儀表板在「我的使用統計」模式仍可展開使用者多選清單，造成使用者誤以為勾選其他帳號會生效。
- 主要修改：`api/static/editor.html` 在個人記錄模式改顯示固定的「目前顯示個人記錄」提示與問號說明按鈕；使用者多選清單預設隱藏，只有 superuser 切到全體記錄模式時才顯示並可勾選其他使用者或全部列出。統計查詢參數仍維持個人模式強制帶目前登入者、全體模式才套用多選使用者。
- 驗證：`node --check /tmp/editor.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（23 passed，2 個既有 SyntaxWarning）；`pytest tests` 通過（69 passed，5 個既有 warning）。
- 截圖限制：本次為可視 UI 調整，但 `python -m playwright --version` 仍回報 `No module named playwright`，因此未提供瀏覽器截圖；以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-14 portable_auth_pack 個人帳號統計篩選提示同步

- 目的：依回饋將主系統統計儀表板個人記錄提示行為同步到 `portable_auth_pack`，避免範例包的帳號操作統計仍在個人模式展開帳號多選清單。
- 主要修改：`portable_auth_pack/static/login_admin_minimal.html` 在「我的帳號操作紀錄」模式顯示固定的個人帳號操作紀錄提示與問號說明按鈕；帳號多選清單預設隱藏，只有 superuser 切到「全體帳號操作紀錄」時才顯示並套用選取帳號。
- 驗證：`node --check /tmp/editor.html.js && node --check /tmp/login_admin_minimal.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py -q` 通過（23 passed，2 個既有 SyntaxWarning）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過（既有 Starlette/httpx warning）；`pytest tests -q` 通過（69 passed，5 個既有 warning）。
- 截圖限制：可視 UI 變更仍受目前環境未安裝 Playwright 影響，`python -m playwright --version` 回報 `No module named playwright`，已以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-14 個人範圍問號說明改為 focus-stable tooltip

- 目的：修正個人紀錄 / 個人帳號操作紀錄模式的問號說明若使用者移到 `?` 上點擊，原生 `title` tooltip 可能消失，造成新手看不到提示。
- 主要修改：`api/static/editor.html` 與 `portable_auth_pack/static/login_admin_minimal.html` 將 `title` 改為頁面內 `role="tooltip"` 說明泡泡，透過 `.scope-help:hover` 與 `.scope-help:focus-within` 顯示；點擊 `?` 後按鈕取得 focus，說明仍可停留顯示。
- 驗證：`node --check /tmp/editor.html.js && node --check /tmp/login_admin_minimal.html.js` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py -q` 通過（23 passed，2 個既有 SyntaxWarning）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過（既有 Starlette/httpx warning）；`pytest tests -q` 通過（69 passed，5 個既有 warning）。
- 截圖限制：本次為 hover / focus 可視 UI 互動改善；目前環境仍未安裝 Playwright（`python -m playwright --version` 回報 `No module named playwright`），以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-14 Editor 靜態頁拆檔重構

- 目的：盤點肥大單檔並優先拆分 `api/static/editor.html`，降低單一 HTML 檔案維護成本。
- 主要修改：將原本內嵌於 `api/static/editor.html` 的 CSS / JavaScript 分別抽出到 `api/static/editor.css` 與 `api/static/editor.js`；HTML shell 保留 DOM 與載入外部 assets。`tests/test_editor_auth_ui_static.py` 改以 HTML + split assets 組合內容做既有靜態斷言，並新增 asset 載入檢查。
- 驗證：執行 `node --check api/static/editor.js` 通過；執行 `pytest tests/test_editor_auth_ui_static.py` 通過（16 passed）；執行 `pytest tests` 通過（70 passed，僅既有 warnings）。
- 結論：`api/static/editor.html` 從約 1398 行降為約 275 行；行為不變，CSS / JS 可獨立維護與語法檢查。

## 2026-06-14 portable_auth_pack 靜態頁同步拆檔

- 目的：回應前次 Editor 拆檔後，`portable_auth_pack/static/login_admin_minimal.html` 仍有對應的內嵌 CSS / JS 單檔膨脹問題。
- 主要修改：將 `portable_auth_pack/static/login_admin_minimal.html` 的內嵌 CSS / JavaScript 分別抽出到 `login_admin_minimal.css` 與 `login_admin_minimal.js`；HTML shell 保留 DOM 與載入外部 assets。`tests/test_editor_auth_ui_static.py` 新增 portable shell asset 載入檢查，並改以 shell + split assets 做既有 portable 靜態斷言。
- 驗證：執行 `node --check api/static/editor.js && node --check portable_auth_pack/static/login_admin_minimal.js` 通過；執行 `pytest tests/test_editor_auth_ui_static.py` 通過（17 passed）；執行 `python portable_auth_pack/scripts/verify_auth_pack.py` 通過（僅既有 Starlette/httpx warning）；執行 `pytest tests` 通過（71 passed，僅既有 warnings）。
- 結論：主系統 Editor 與 portable auth pack 的靜態頁現在採一致的 shell + CSS + JS 拆檔模式。


## 2026-06-14 Editor JS 責任導向再拆分

- 目的：回應 `api/static/editor.js` 仍有 1007 行、只是從 HTML 搬到另一個大型單檔的問題。
- 主要修改：移除單一 `editor.js`，改拆為 `editor_core.js`、`editor_form.js`、`editor_auth_nav.js`、`editor_stats.js`、`editor_audit.js`、`editor_documents.js`、`editor_bootstrap.js`；`api/static/editor.html` 依序載入上述 classic scripts。`tests/test_editor_auth_ui_static.py` 新增 `EDITOR_SCRIPT_FILES`，驗證 shell 不再載入 `editor.js` 且每個 Editor JS 檔低於 350 行。
- 驗證：執行 `for f in api/static/editor_*.js portable_auth_pack/static/login_admin_minimal.js; do node --check "$f" || exit 1; done` 通過；執行 `pytest tests/test_editor_auth_ui_static.py` 通過（17 passed）。
- 結論：Editor JavaScript 從 1007 行單檔改為最大約 292 行的責任導向小檔，仍不導入 build pipeline。

## 2026-06-14 portable_auth_pack JS 責任導向再拆分

- 目的：回應 Editor JS 再拆分後，`portable_auth_pack` 也應有對應責任導向拆檔，而不是保留單一 `login_admin_minimal.js`。
- 主要修改：移除單一 `login_admin_minimal.js`，改拆為 `login_admin_core.js`、`login_admin_auth.js`、`login_admin_audit.js`、`login_admin_stats.js`、`login_admin_admin.js`、`login_admin_bootstrap.js`；`login_admin_minimal.html` 依序載入上述 classic scripts。`tests/test_editor_auth_ui_static.py` 新增 `PORTABLE_AUTH_PACK_SCRIPT_FILES`，驗證 shell 不再載入 `login_admin_minimal.js` 且每個 portable JS 檔低於 200 行。
- 驗證：執行 `for f in api/static/editor_*.js portable_auth_pack/static/login_admin_*.js; do node --check "$f" || exit 1; done` 通過；執行 `pytest tests/test_editor_auth_ui_static.py` 通過（17 passed）。
- 結論：主系統 Editor 與 portable auth pack 的 JS 都已從單一行為檔改為責任導向小檔，且仍不導入 build pipeline。

## 2026-06-14 Editor split assets 404 修正

- 目的：修正拆檔後 Editor 頁面載入 `/static/editor.css` 與 `/static/editor_*.js` 時回 404，導致 UI 樣式與互動消失。
- 主要修改：`api/routers/editor.py` 新增 `EDITOR_STATIC_ASSETS` 白名單與 `/static/{filename}` route，允許服務 `editor.css`、`audit_tools.js` 與所有拆分後的 Editor JS；未知檔名仍回 404。`tests/test_editor_auth_ui_static.py` 新增 TestClient 驗證拆分 assets 可由 router 取得。
- 驗證：執行 `pytest tests/test_editor_auth_ui_static.py` 通過（18 passed，僅既有 warnings）。
- 結論：拆分後的 Editor CSS / JS 不只存在於檔案系統，也會透過既有 FastAPI router 正確對外提供，避免瀏覽器 404。

## 2026-06-14 Editor router auth / usage 拆檔

- 目的：檢查肥大單檔並優先拆分目前最大的可維護 Python route 檔 `api/routers/editor.py`。
- 主要修改：將 `/v1/auth/*` 帳號與登入相關 route 移至 `api/routers/editor_auth.py`，將 `/v1/editor/usage-stats` 與 `/v1/editor/audit-logs` 移至 `api/routers/editor_usage.py`；`api/routers/editor.py` 保留 Editor shell/static/documents routes 並 include 子 router。
- 相容性：`api.routers.editor` 保留 `usage_stats()`、`list_audit_logs()` 與 `load_audit_records` wrapper / alias，支援既有測試或腳本直接 import route handler。
- 驗證：`python -m py_compile api/routers/editor.py api/routers/editor_auth.py api/routers/editor_usage.py` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（26 passed，1 個既有 Starlette warning）；`pytest tests` 通過（72 passed，5 個既有 warnings）。
- 結論：`api/routers/editor.py` 由 663 行降至約 365 行，新增 auth / usage 子 router 分攤職責，API path 與 response contract 不變。

## 2026-06-14 portable_auth_pack router 對應拆檔

- 目的：回應主系統 Editor router 拆檔後，確認 `portable_auth_pack` 是否有對應需要同步的 router 組織調整。
- 主要修改：將 `portable_auth_pack/fastapi_auth_pack/router.py` 改為聚合 router；新增 `auth_routes.py` 承載 `/v1/auth/*` 與 login-audit route，新增 `usage_routes.py` 承載 portable 的 `/v1/editor/usage-stats` 帳號操作統計相容 endpoint。
- 文件同步：更新 `portable_auth_pack/README.md` 與 `CODEX_IMPORT_GUIDE.md`，補上 `auth_routes.py` / `usage_routes.py` 的目錄與導入說明。
- 驗證：`python -m py_compile portable_auth_pack/fastapi_auth_pack/router.py portable_auth_pack/fastapi_auth_pack/auth_routes.py portable_auth_pack/fastapi_auth_pack/usage_routes.py` 通過；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（26 passed）；`pytest tests` 通過（72 passed，既有 warnings）。
- 結論：portable auth pack 與主系統後端 router 拆檔方向同步，外部仍可 `from fastapi_auth_pack import router` 並維持 API contract 不變。

## 2026-06-14 Auth 註冊防列舉、IP 稽核與頻率限制

- 目的：帳號操作紀錄補上來源 IP / client host；避免註冊 API 以「帳號已存在」暴露帳號存在性；對註冊申請加入 per-IP process-local 頻率限制；並同步 `portable_auth_pack`。
- 主要修改：主系統 `POST /v1/auth/register` 對成功申請與 duplicate username 回相同泛用 200 訊息，duplicate 只寫入 `auth.user_registered` audit reason；帳號操作 audit event 補 `client_host`；註冊申請以 `scope=register` + `client_host` 復用既有 in-memory throttle。`portable_auth_pack` 同步泛用註冊回應、註冊節流與 login audit `client_host` / reason 記錄。
- 驗證：`pytest tests/test_auth_store_security.py -q` 通過（13 passed，既有 warnings）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過（僅既有 StarletteDeprecationWarning）。
- 結論：公開註冊 API 不再直接提供帳號存在性 oracle，帳號資安檢核可從 audit 中追蹤 client host；正式多副本環境仍建議改集中式 rate limiting。

## 2026-06-14 帳號操作 client_host 顯示與統計

- 目的：修正帳號操作記錄管理頁面已記錄 client_host 但未顯示來源 IP，且帳號操作統計儀表板未呈現 client_host 統計的問題；同步保持 portable_auth_pack 相容 endpoint 的統計欄位。
- 主要修改：`api/static/editor_audit.js` 的帳號操作紀錄卡片顯示 `IP：client_host` 與可用的 User-Agent；`api/services/editor_audit_queries.py` 的 `build_usage_stats()` 新增 `by_client_host`；`api/static/editor_stats.js` 在摘要卡新增 IP 數，並於既有統計區塊列出「依 client_host IP」。`portable_auth_pack/fastapi_auth_pack/usage_routes.py` 與 `portable_auth_pack/static/login_admin_stats.js` 同步 `by_client_host` 與 IP 數卡片。
- 驗證：`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（27 passed，3 個既有 warnings）；`python -m py_compile api/services/editor_audit_queries.py api/routers/editor_usage.py portable_auth_pack/fastapi_auth_pack/usage_routes.py` 通過；`node --check api/static/editor_audit.js && node --check api/static/editor_stats.js && node --check portable_auth_pack/static/login_admin_stats.js` 通過。
- 記憶維護：因 `.codex/decisions.md` 超過 400 行，已先歸檔至 `.codex/archive/decisions.md-20260614-125305.md`，再濃縮為 current summary / recent changes / archived history。

## 2026-06-14 帳號操作統計儀表板 IP 多選篩選

- 目的：依使用者回饋，帳號操作記錄儀表板除了使用者多選，也要能以相同互動方式多選 IP / client_host 篩選。
- 主要修改：`api/static/audit_tools.js` 與 `portable_auth_pack/static/audit_tools.js` 新增共用 multi-filter helper；主系統 `api/static/editor.html` / `editor_stats.js` 與 `portable_auth_pack/static/login_admin_minimal.html` / `login_admin_stats.js` 新增 IP / client_host 多選清單、搜尋、勾選目前篩選、清除目前篩選與清除全部。`GET /v1/editor/usage-stats` 與 `GET /v1/editor/audit-logs` 支援 `client_host` query，portable usage-stats 相容 endpoint 也同步支援。
- 驗證：`for f in api/static/audit_tools.js api/static/editor_*.js portable_auth_pack/static/audit_tools.js portable_auth_pack/static/login_admin_*.js; do node --check "$f" || exit 1; done` 通過；`pytest tests/test_editor_auth_ui_static.py tests/test_editor_audit_queries.py` 通過（29 passed，1 個既有 warning）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests` 通過（77 passed，5 個既有 warnings）。
- 截圖限制：本次為可視 UI 變更，但 `python -m playwright --version` 回報 `No module named playwright`，目前仍無法提供瀏覽器截圖；已以靜態 UI 測試與 JS 語法檢查替代。

## 2026-06-15 report_agent 拆檔重構

- 目的：檢查專案中單檔過肥問題，優先處理主要可執行模組中超過 600 行的 `agent/report_agent.py`。
- 主要修改：將報告 LLM 系統提示詞移至 `agent/report_prompt.py`，將報告模型 / timeout 環境設定移至 `agent/report_config.py`，將統計壓縮 helper 移至 `agent/report_stats.py`；`agent/report_agent.py` 保留報告流程 orchestration，行數由 621 行降至 367 行。
- 驗證：`python -m py_compile agent/report_agent.py agent/report_prompt.py agent/report_config.py agent/report_stats.py` 通過；`pytest tests/test_chat_api.py tests/test_export_word.py` 因指定測試檔不存在而未執行（collected 0）；改以 `pytest tests` 完整測試通過（77 passed，僅既有 warnings）。
- 結論：本次拆檔未變更 API contract 或報告資料流程，只降低單檔負擔並讓 prompt / config / stats helper 有明確模組邊界。

## 2026-06-15 Agent router 單檔拆分

- 目的：檢查大型檔案並進行低風險拆檔重構；排除資料、輸出、技術文件與備份檔後，優先處理 `agent/agent.py` 這類核心 orchestration 檔案。
- 主要修改：新增 `agent/routing.py` 承載 router prompt、topic/index helper 與 LLM 任務分類流程；`agent/agent.py` 改為只負責 session、context 組裝、路由結果分派與統一輸出，行數由 610 行降至 392 行。
- 驗證：`python -m compileall agent/agent.py agent/routing.py` 通過；`python - <<'PY' ... import agent.agent ...` 通過；`pytest tests` 通過（77 passed，僅既有 StarletteDeprecationWarning、SyntaxWarning 與 datetime.utcnow deprecation warnings）。
- 結論：`answer_with_routing()` 外部入口與主要 response contract 不變；router helper 後續集中維護於 `agent/routing.py`。

## 2026-06-15 Auth Store 肥大檔案拆檔

- 目的：盤點單檔程式碼行數，優先處理非備份、仍在使用且超過約 600 行的 Auth Store 模組。
- 主要修改：`api/services/auth_store.py` 與 `portable_auth_pack/fastapi_auth_pack/auth_store.py` 保留 `AuthStore` 與既有 public import path；角色 / 密碼雜湊 / token secret / bootstrap / throttle helper 拆至各自 package 的 `auth_support.py`；JWT create / parse 實作拆至 `auth_tokens.py`，原 `auth_store.create_token()` / `parse_token()` 維持相容。
- 驗證：`pytest tests/test_auth_store_security.py tests/test_editor_audit_queries.py` 通過（24 passed，僅既有 StarletteDeprecationWarning）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`python -m py_compile api/services/auth_store.py api/services/auth_support.py api/services/auth_tokens.py portable_auth_pack/fastapi_auth_pack/auth_store.py portable_auth_pack/fastapi_auth_pack/auth_support.py portable_auth_pack/fastapi_auth_pack/auth_tokens.py` 通過。
- 結論：主系統與 portable auth pack 的 auth store 從約 611 / 616 行降至各 400 行，helper 與 token 邏輯各自獨立，既有 API / route contract 未變更。
- 補充驗證：`pytest tests` 通過（77 passed，5 warnings；warnings 為既有 Starlette/httpx 與 `datetime.utcnow()` deprecation）。

## 2026-06-15 登入失敗即時警示記錄

- 目的：使用者指出登入失敗不容易即時發現，需讓有人嘗試偷試密碼時可透過記錄快速察覺，且主系統與 `portable_auth_pack` 同步。
- 主要修改：主系統 `POST /v1/auth/login` 在 `rate_limited`、`invalid_credentials`、`inactive_account` 三種失敗路徑保留既有 login audit / editor audit，並新增 `auth.login.failed` warning log；log 包含 username、reason、client_host、user_agent、role/status（若有），不寫入密碼。`portable_auth_pack` 同步在相同登入失敗路徑新增 warning log，且持續寫入 login audit。
- 驗證：執行 `pytest tests/test_auth_store_security.py` 通過（14 passed，僅既有 Starlette / SyntaxWarning warnings）；執行 `python portable_auth_pack/scripts/verify_auth_pack.py` 通過並可看到 `auth.login.failed ...` warning log。
- 結論：登入失敗現在同時具備持久 audit 查詢與應用程式 warning log，可供日誌監控 / alerting 更即時偵測暴力嘗試。

## 2026-06-15 登入失敗記錄拆檔修正

- 目的：回應 review 意見，避免為新增 `auth.login.failed` warning log 讓 `api/routers/editor_auth.py` 與 `portable_auth_pack/fastapi_auth_pack/auth_routes.py` 變得更肥大，並移除上一版因格式化造成的大量無關 diff。
- 主要修改：主系統新增 `api/routers/editor_auth_logging.py`，portable auth pack 新增 `portable_auth_pack/fastapi_auth_pack/auth_logging.py`，集中保存 password-free failed-login warning log helper；兩個 route 檔只保留登入流程呼叫點。`api/routers/editor_auth.py` 回到約 288 行，`portable_auth_pack/fastapi_auth_pack/auth_routes.py` 回到約 231 行，新增 logging helper 檔各低於 30 行。
- 驗證：`python -m py_compile api/routers/editor_auth.py api/routers/editor_auth_logging.py portable_auth_pack/fastapi_auth_pack/auth_routes.py portable_auth_pack/fastapi_auth_pack/auth_logging.py tests/test_auth_store_security.py portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests/test_auth_store_security.py` 通過（14 passed，既有 warnings）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過。
- 結論：保留登入失敗即時警示與 audit 行為，但將共用記錄責任從 route orchestration 檔拆出，降低肥大與無關格式化 diff。

## 2026-06-15 Excel→SQL Dashboard 拆檔重構

- 目的：檢查單檔程式碼行數，避開備份檔後選定目前仍在使用且超過 600 行的 `data_ingestion/excel_to_sql/dashboard.py` 進行小範圍拆檔。
- 主要修改：將 dashboard 的 chart bucket、JSON-safe conversion、SQL cursor row conversion、audit table / table exists、time window、filter normalization、payload parsing 與 dashboard config helper 抽至 `data_ingestion/excel_to_sql/dashboard_support.py`；`dashboard.py` 保留 public entry points `discover_dashboard_tasks()`、`dashboard_payload()`、`delete_imported_sql_row()`，以維持既有 monkeypatch 測試與呼叫相容性。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/dashboard_support.py` 通過；Excel→SQL dashboard 相關 pytest 通過（29 passed，僅既有 `datetime.utcnow()` warnings）；完整 `pytest tests` 通過（78 passed，7 warnings：既有 StarletteDeprecationWarning、SyntaxWarning、datetime.utcnow deprecation）。
- 結論：`dashboard.py` 由 611 行降至 419 行，新增 helper module 217 行；未改變 API response shape、SQL 查詢語意或 dashboard public function names。

## 2026-06-15 Excel→SQL Dashboard helper 功能面向再拆分

- 目的：回應 review，避免新抽出的 `dashboard_support.py` 變成另一個籠統 support 檔，改依功能面向拆成更小模組。
- 主要修改：移除 `data_ingestion/excel_to_sql/dashboard_support.py`；新增 `dashboard_config.py`（dashboard enable/name helper）、`dashboard_filters.py`（chart bucket、時間窗、WHERE/filter normalization、payload parsing）、`dashboard_sql.py`（JSON-safe conversion、row conversion、SQL connection、audit table/table exists/fetch helper）；`dashboard.py` 改為直接從這些功能模組匯入 helper，public entry points 不變。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/dashboard_config.py data_ingestion/excel_to_sql/dashboard_filters.py data_ingestion/excel_to_sql/dashboard_sql.py` 通過；Excel→SQL dashboard 相關 pytest 通過（29 passed，既有 `datetime.utcnow()` warnings）；完整 `pytest tests` 通過（78 passed，7 warnings）。
- 結論：dashboard helper 不再集中於單一 support 檔；目前各拆分模組皆小於 150 行，dashboard public API 與 SQL 查詢語意維持不變。

## 2026-06-15 Excel→SQL 使用者匯入操作界面

- 目的：新增 Excel→SQL 使用者操作界面，支援上傳 Excel、選擇匯入規格、預掃描確認、實際匯入、匯入記錄查詢、條件篩選與批次刪除。
- 主要修改：新增 `data_ingestion/excel_to_sql/user_imports.py` 管理使用者上傳檔、`data/excel_to_sql_user_imports/records.json` 記錄、預掃描、確認匯入與刪除移藏；`api/routers/excel_to_sql.py` 新增 import-records API；`api/static/excel_to_sql_dashboard.html` 加入操作 UI 與記錄管理表格。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_excel_to_sql_user_imports.py` 通過（24 passed；既有 datetime.utcnow warnings）；`node --check /tmp/excel_dashboard.js` 通過；`python - <<'PY' ... import api.routers.excel_to_sql ...` 通過（僅既有 SyntaxWarning / 設定載入輸出）；`python -m playwright --version` 仍顯示環境未安裝 Playwright。
- 結論：使用者匯入流程不以 mock data 宣稱完成；預掃描會實際讀 Excel 並連 SQL 檢查 hash 去重，確認後重用既有 `process_excel_file()` 進行真實匯入。

## 2026-06-15 Excel→SQL 使用者匯入拆檔

- 目的：依 review 要求，檢查 Excel→SQL 功能新增後是否有太肥大的程式檔，並將前次新增的使用者匯入流程拆成更小的責任模組。
- 主要修改：`data_ingestion/excel_to_sql/user_imports.py` 改為 facade；新增 `user_import_storage.py`（registry / active-deleted storage / list-save-delete）、`user_import_preview.py`（Excel 預掃描與 hash 去重估算）、`user_import_runner.py`（確認後重用 `process_excel_file()` 實際匯入）。前端新增的匯入記錄操作 JS 從 dashboard HTML 拆到 `api/static/excel_to_sql_import_records.js`，並加入靜態資產白名單。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py tests/test_excel_to_sql_user_imports.py` 通過；`node --check /tmp/excel_dashboard_inline.js` 與 `node --check api/static/excel_to_sql_import_records.js` 通過。
- 結論：使用者匯入相關 Python 檔目前分散為 34 / 61 / 157 / 166 行的小模組，保留既有 public import path 與 API contract。

## 2026-06-15 Excel→SQL 肥大檔案二次拆分

- 目的：再次檢查 Excel→SQL 功能是否仍有太肥大的程式或 HTML 檔，並對超過約 400 行或接近上限的檔案進一步拆分。
- 主要修改：`api/static/excel_to_sql_dashboard.html` 的 dashboard inline JS 拆到 `api/static/excel_to_sql_dashboard.js`；`data_ingestion/excel_to_sql/workbook.py` 的欄位 mapping、hash 與 row iteration 拆到 `workbook_rows.py` 並由原模組 re-export；`data_ingestion/excel_to_sql/dashboard.py` 的人工刪除 SQL row 流程拆到 `dashboard_delete.py`，原 public function 保留 wrapper 以維持 monkeypatch 相容性。
- 驗證：`pytest tests/test_excel_to_sql_dashboard_static.py tests/test_excel_to_sql_user_imports.py tests/test_workbook_sheets.py tests/test_dashboard_filters.py` 通過（20 passed）；`node --check api/static/excel_to_sql_dashboard.js && node --check api/static/excel_to_sql_import_records.js` 通過；`python -m py_compile ...` 通過。
- 結論：Excel→SQL 相關 Python / HTML / JS 檔目前最大者約 399 行，已無超過 400 行的 Excel→SQL 功能檔。

## 2026-06-15 Excel 匯入作業中心拆頁與日期篩選修正

- 目的：將使用者 Excel 上傳 / 預掃描 / 確認匯入 SQL / 匯入記錄管理從 SQL audit 監控儀表板拆出，並修正監控儀表板起迄時間因自動延展結束時間導致歷史日期區間看似無效的問題。
- 主要修改：新增 `/excel-to-sql-import-center` 靜態頁作為「Excel 匯入作業中心」；原 `/excel-to-sql-dashboard` 僅保留 SQL audit 監控並提供導覽按鈕。匯入記錄 JS 改為可獨立啟動，記錄篩選起迄改用本機 datetime-local 後送 UTC ISO，並在 imported_with_errors / preview 結果顯示 failure_summary 與失敗樣本。監控儀表板「回看天數」改為起迄皆空時才生效，不再於重新整理 / 套用篩選時自動把結束時間推到現在；另提供「填入近14天起迄」按鈕。
- 使用者案例分析：本次未連線到使用者 SQL Server，也未寫入使用者提供的 DB 密碼；針對 imported_with_errors，UI 現在會顯示實際匯入或預掃描回傳的錯誤摘要，方便判斷是日期格式、必填欄位、SQL 寫入或其他資料列問題。
- 驗證：`node --check api/static/excel_to_sql_dashboard.js`、`node --check api/static/excel_to_sql_import_records.js` 通過；`pytest tests/test_excel_to_sql_dashboard_static.py tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py tests/test_ingest_insert_fallback.py tests/test_workbook_sheets.py` 通過（26 passed，既有 datetime.utcnow deprecation warnings）。

## 2026-06-15 Excel 匯入導航、監控 UI 與預掃描建表修正

- 目的：修正 Editor 第一層「ES 資料庫」未選取時仍呈藍色、整理 Excel→SQL 導航層級、移除監控 dashboard 上方回看天數按鈕與匯入作業中心說明區塊，並修正 SQL 目的表被刪除後使用者匯入預掃描因 table missing 失敗。
- 主要修改：Editor 第一層導航按鈕預設改為灰色，只有 active root 使用藍色；「匯入流程」改為「匯入管理 → Excel 匯入流程管理」，提供「監控 Dashboard」與「Excel 匯入作業中心」兩個入口。監控 dashboard 保留 header 作業中心入口，但移除內容區說明卡與「使用回看天數」按鈕。使用者匯入預掃描在 `destination.auto_create_table` 啟用時會先依 mappings / hash field 確保目的表存在，再查詢既有 hash，避免 table 被刪除後直接拋出 42S02。
- 驗證：`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py` 通過（25 passed）；`pytest tests` 通過（81 passed，僅既有 Starlette / datetime.utcnow warnings）；`node --check api/static/editor_bootstrap.js && node --check api/static/excel_to_sql_dashboard.js` 通過；`python -m playwright --version` 仍因環境未安裝 Playwright 無法截圖。
- 結論：Excel 匯入操作與監控入口層級更清楚，監控 dashboard 不再混入作業中心說明；目的 SQL table 被刪除後，預掃描可在自動建表設定開啟時重建 table 並繼續估算新增 / 重複 / 錯誤列數。

## 2026-06-15 Excel 匯入記錄管理表格響應式版面修正

- 目的：改善「Excel 匯入作業中心」的匯入記錄管理表格；在大型桌機螢幕避免操作按鈕被擠到水平捲軸右側，在手機螢幕改成較容易檢閱與操作的卡片式列表。
- 主要修改：`api/static/excel_to_sql_import_center.html` 將匯入記錄表改為 fixed table layout、加入 colgroup 欄寬、縮小操作按鈕排列並保留可換行文字；手機寬度下隱藏表頭、每筆記錄以卡片呈現，欄位用 `data-label` 顯示標籤，操作按鈕改為單欄滿寬。`api/static/excel_to_sql_import_records.js` 為每個儲存格輸出 `data-label` 與勾選 checkbox aria-label，提升手機版可讀性與可操作性。
- 驗證：`node --check api/static/excel_to_sql_import_records.js` 通過；`pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py` 通過（7 passed）；`pytest tests` 通過（81 passed，既有 Starlette / SyntaxWarning / datetime.utcnow warnings）。`python -m playwright --version` 仍因環境未安裝 Playwright 無法提供截圖。
- 結論：桌機版應更能在 1500px 內容寬度內呈現完整操作欄；手機版不再依賴水平捲動檢閱欄位與操作按鈕。

## 2026-06-15 Excel 匯入確認時自動建立 audit table 與移除刪除記錄 UI

- 目的：修正 Excel 匯入作業中心確認匯入 SQL 時，若 `dbo.ExcelImportAudit` 尚未存在會因 `42S02 無效的物件名稱` 寫入 audit 失敗；並依需求移除「Excel 匯入記錄管理」的刪除記錄操作入口。
- 主要修改：`data_ingestion/excel_to_sql/user_import_runner.py` 在使用者確認匯入前，依 `audit.enabled` / `audit.table` 呼叫 `ensure_audit_table()` 並 commit，讓使用者匯入流程與既有批次匯入流程一致。`api/static/excel_to_sql_import_center.html` 與 `api/static/excel_to_sql_import_records.js` 移除批次刪除按鈕、單筆「刪除記錄」按鈕、刪除用 checkbox 與前端 DELETE 呼叫。
- 驗證：`node --check api/static/excel_to_sql_import_records.js` 通過；`pytest tests/test_excel_to_sql_user_imports.py tests/test_audit.py -q` 通過（6 passed）；`pytest tests -q` 通過（82 passed，7 warnings：既有 StarletteDeprecationWarning、SyntaxWarning、datetime.utcnow DeprecationWarning）。
- 截圖限制：本次包含可視 UI 操作移除，但 `python -m playwright --version` 回報 `No module named playwright`，因此以靜態測試與 JS 語法檢查替代。

## 2026-06-15 匯入記錄刪除後端移除與記錄儲存拆分

- 目的：回應 review，完整移除 Excel 匯入記錄管理的批次刪除 / 單筆刪除能力，並避免單一 `records.json` 隨記錄數與 preview/import payload 長期膨脹。
- 主要修改：移除 `DELETE /v1/excel-to-sql/import-records` route、`DeleteImportRecordsPayload`、`user_imports.delete_records` export 與 storage 內 `delete_records()` 後端函式。`records.json` 改為 compact `record_ids` index，完整記錄改寫入 `data/excel_to_sql_user_imports/records/<id>.json`；讀取舊版 `{"records": [...]}` 時會 lazy migrate 成新格式。
- 驗證：`node --check api/static/excel_to_sql_import_records.js` 通過；`pytest tests/test_excel_to_sql_user_imports.py tests/test_audit.py -q` 通過；`pytest tests -q` 通過（82 passed，既有 warnings）。

## 2026-06-16 Auth JSON 儲存防肥大與壞檔還原

- 目的：回應 `.sra_users.json` 同時存帳號與 `login_audit` 會隨登入紀錄成長而增加壞檔 / 不穩風險的疑慮，並同步主系統與 `portable_auth_pack`。
- 主要修改：主系統登入稽核改由 `SRA_LOGIN_AUDIT_FILE` 指定的獨立 JSON 檔保存；未設定時使用 `SRA_AUTH_USERS_FILE` 同目錄、同前綴的 `.login_audit.json`。`portable_auth_pack` 同步新增 `AUTH_LOGIN_AUDIT_FILE` 與同等預設行為。
- 防壞檔機制：帳號檔與登入稽核檔每次寫入前保留 `.bak` 備份，讀取遇到 JSON decode 失敗時優先從 `.bak` 還原；既有舊版 `login_audit` 會在首次啟動時複製到新 audit 檔，後續帳號檔正規化時不再保存 `login_audit`。
- 安全結論：不採用「第一個註冊者自動 approve 為 superuser」；仍以 bootstrap superusers 檔案或環境變數建立初始管理者，避免公開部署時被搶註冊取得最高權限。
- 驗證：`python -m py_compile api/services/auth_store.py api/services/auth_support.py portable_auth_pack/fastapi_auth_pack/auth_store.py portable_auth_pack/fastapi_auth_pack/auth_support.py` 通過；`pytest tests/test_auth_store_security.py -q` 通過（17 passed，1 個既有 StarletteDeprecationWarning）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過（含既有測試 warning / 預期登入失敗 log）；`pytest tests -q` 通過（86 passed，5 個既有 warning）。

## 2026-06-16 Login Audit 月份分片

- 目的：修正前次只把 `login_audit` 從帳號檔拆到 `SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE`，但 audit 仍可能成為單一肥大 JSON 的問題。
- 主要修改：主系統與 `portable_auth_pack` 的 login audit 改成 manifest + 月份 shard 架構；設定的 audit file 只保存 `storage: sharded` 與 shard 目錄資訊，實際事件依 `ts` 寫入 `login_audit-YYYYMM.json`。
- 相容性：若發現舊版單檔 audit JSON 中仍有 `events`，啟動時會搬入月份 shard 後把設定檔改寫為 sharded manifest；帳號檔內舊 `login_audit` 仍會遷移到 shard。
- 驗證：`python -m py_compile api/services/auth_store.py api/services/auth_support.py portable_auth_pack/fastapi_auth_pack/auth_store.py portable_auth_pack/fastapi_auth_pack/auth_support.py` 通過；`pytest tests/test_auth_store_security.py -q` 通過（18 passed，1 個既有 warning）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests -q` 通過（87 passed，5 個既有 warning）。

## 2026-06-16 Auth Store 拆檔重構

- 目的：回應 `api/services/auth_store.py` 與 `portable_auth_pack/fastapi_auth_pack/auth_store.py` 因 JSON IO、login audit sharding 與帳號流程集中而變肥大的問題。
- 主要修改：新增主系統與 portable 版 `auth_json_store.py` 管理 atomic JSON write / `.bak` recovery；新增 `auth_login_audit_store.py` 管理 sharded login audit manifest、月份 shard、legacy audit migration 與查詢合併；`auth_store.py` 回到帳號、密碼、token 與 throttle orchestration。
- 驗證：`python -m py_compile api/services/auth_store.py api/services/auth_json_store.py api/services/auth_login_audit_store.py api/services/auth_support.py portable_auth_pack/fastapi_auth_pack/auth_store.py portable_auth_pack/fastapi_auth_pack/auth_json_store.py portable_auth_pack/fastapi_auth_pack/auth_login_audit_store.py portable_auth_pack/fastapi_auth_pack/auth_support.py` 通過；`pytest tests/test_auth_store_security.py -q` 通過（18 passed）；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests -q` 通過（87 passed，5 個既有 warning）。

## 2026-06-16 JSON Store 多版本備份

- 目的：回應單一 `.bak` 只能保存上一版，若最新備份也壞掉仍可能無法還原的疑慮。
- 主要修改：`JsonFileStore` 改為保留最新 `.bak` 加預設 10 個 `.bak.<timestamp>` 歷史版本；讀取正式檔 JSON decode 失敗時會依序嘗試最新 `.bak` 與歷史備份，找到最新可解析 dict 後複製回正式檔。
- 驗證：`pytest tests/test_auth_store_security.py -q` 通過（19 passed）；`python -m py_compile api/services/auth_json_store.py portable_auth_pack/fastapi_auth_pack/auth_json_store.py` 通過；`python portable_auth_pack/scripts/verify_auth_pack.py` 通過；`pytest tests -q` 通過（88 passed，5 個既有 warning）。
