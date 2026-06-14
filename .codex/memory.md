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
