# 已知問題（Known Issues）

## <問題名稱>

首次發現：

問題：

影響：

暫時解法：

根本原因：

狀態：
Open

負責人：

---

## 測試期間 datetime.utcnow DeprecationWarning

首次發現：2026-06-11

問題：

- 執行 `pytest tests` 時，`data_ingestion/excel_to_sql/file_ops.py` 會出現 `datetime.datetime.utcnow()` deprecation warnings。

影響：

- 不影響本次功能測試結果，測試仍全數通過；但未來 Python 版本可能需要改用 timezone-aware datetime。

暫時解法：

- 目前可忽略 warning；後續安排技術債修正。

根本原因：

- 程式使用 naive UTC datetime API。

狀態：
Open

負責人：

-

---

---

## Playwright 未安裝導致無法截圖驗證

首次發現：2026-06-11

問題：

- 本次調整靜態 web UI 後，嘗試檢查瀏覽器截圖工具時，Python 環境未安裝 `playwright` 模組。

影響：

- 無法在目前環境直接執行 Playwright 截圖驗證；不影響靜態 UI 測試與後端測試。

暫時解法：

- 以 `pytest tests/test_editor_auth_ui_static.py` 驗證導航 DOM、CSS class、ARIA 展開狀態與自動收合函式。
- 需要視覺截圖時，於具備 Playwright / browser runtime 的環境執行手動或自動化截圖。

根本原因：

- 測試環境缺少瀏覽器自動化套件。

狀態：
Open

負責人：

-


---

## 2026-06-11 本次 UI 調整仍無法截圖驗證

首次發現：2026-06-11

問題：

- 本次調整 Editor 靜態 UI 後，再次以 Python 檢查 `playwright` 模組，環境仍回報 `No module named 'playwright'`。

影響：

- 無法在目前環境提供瀏覽器截圖驗證；不影響靜態 DOM / JS 字串測試與完整 pytest 結果。

暫時解法：

- 使用 `pytest tests/test_editor_auth_ui_static.py` 驗證導航、工作區分離與紀錄分流標記。
- 使用 `pytest tests` 驗證完整既有測試。

根本原因：

- 測試環境缺少 Playwright / browser runtime。

狀態：
Open

負責人：

-

---

## 2026-06-11 共用統計 UI 仍無法截圖驗證

首次發現：2026-06-11

問題：

- 本次新增共用 audit chart 與 hover/touch 導航後，再次檢查 Python `playwright` 模組，仍顯示 `No module named 'playwright'`。

影響：

- 無法在目前環境提供桌機 hover 展開、手機點按展開或統計曲線的瀏覽器截圖 / E2E 證據。

暫時解法：

- 使用靜態 UI 測試驗證 `SraAuditTools.bindProgressiveNav()`、`matchMedia('(hover: hover) and (pointer: fine)')`、pointerType 判斷、統計篩選 DOM 與共用 chart module 引用。
- 使用 `tests/test_editor_audit_queries.py` 驗證後端 action_prefix 與 chart bucket 統計。

根本原因：

- 測試環境缺少 Playwright / browser runtime。

狀態：
Open

負責人：

-

## 2026-06-12 FastAPI TestClient StarletteDeprecationWarning

- 執行 `pytest tests` 或 `python portable_auth_pack/scripts/verify_auth_pack.py` 時，`fastapi/testclient.py` 會出現 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`。
- 目前測試仍全部通過；此為相依套件版本相容性警告，非本次 Auth role 變更造成的功能失敗。

## 2026-06-12 Screenshot 驗證限制

- 本次帳號審核 UI 已改為角色下拉選單，但環境未安裝 Playwright（`python - <<'PY' ... import playwright ...` 輸出 `playwright-not-installed`），因此未執行瀏覽器截圖驗證。
- 已改以靜態 UI 測試檢查主系統與 portable auth pack 皆包含 `roleOptionsHtml`、`data-role-select` 與四層 role values。

## 2026-06-12 Dashboard / 使用統計 UI 截圖限制

- 本次調整 Excel→SQL dashboard 標題列與 Editor 使用統計 audit 條目區塊，屬可視 UI 變更；環境再次檢查 `playwright` 時仍輸出 `No module named 'playwright'`。
- 因目前環境缺少 Playwright / browser runtime，未能提供瀏覽器截圖驗證。
- 替代驗證：使用 `pytest tests` 完整測試（61 passed）與靜態 UI 測試確認 DOM、API query 參數與渲染函式存在。

狀態：Open

## 2026-06-12 多層選單方向調整截圖限制

- 本次調整主系統與 `portable_auth_pack` 標題列多層選單方向，屬可視 UI 變更；再次檢查 Python `playwright` 模組時輸出 `No module named 'playwright'`。
- 因目前環境缺少 Playwright / browser runtime，未能提供瀏覽器截圖驗證。
- 替代驗證：使用 `pytest tests/test_editor_auth_ui_static.py` 驗證主系統 nav-actions 為單欄 grid，portable auth pack nav-actions 為 column / nowrap，並保留右側展開定位。

狀態：Open

## 2026-06-12 帳號拒絕文案截圖限制

- 本次將帳號審核「拒絕」文案改為「拒絕申請／停權」，屬可視 UI 文字調整；再次檢查 Python `playwright` 模組時輸出 `No module named 'playwright'`。
- 因目前環境缺少 Playwright / browser runtime，未能提供瀏覽器截圖驗證。
- 替代驗證：使用 `pytest tests/test_editor_auth_ui_static.py` 驗證主系統與 portable auth pack 都含有「拒絕申請／停權」，且不再顯示舊的「拒絕」按鈕文案。

狀態：Open

## 2026-06-12 分頁導航 UI 截圖限制

- 本次新增首頁、末頁與直接輸入頁數等可視 UI 控制；環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法進行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查 Editor / portable auth pack 分頁控制元件、跳頁 Enter 綁定與末頁跳轉邏輯，並執行完整 `pytest tests`。

## 2026-06-12 主系統登入稽核區塊移除截圖限制

- 本次移除主系統重複登入稽核區塊屬於可視 UI 變更；環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法提供瀏覽器截圖驗證。
- 替代驗證：以 `pytest tests/test_editor_auth_ui_static.py` 驗證 DOM / JS 不再包含主系統登入稽核控制，並以 `node --check /tmp/editor.html.js` 驗證抽出的前端 script 語法。

## 2026-06-14 導覽與本地時間 UI 調整截圖限制

- 本次調整 Editor 導覽文字、入口位置與紀錄時間顯示，屬可視 UI 變更。
- 目前環境缺少 Playwright / browser runtime，未執行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查導覽入口、權限標記、本地時間格式化函式與 timezone offset query；以 `node --check /tmp/editor.html.js` 檢查抽出的前端 script 語法。

狀態：Open

## 2026-06-14 portable_auth_pack UI 截圖限制

- 本次同步 `portable_auth_pack/static/login_admin_minimal.html` 的可視文字與本地時間顯示；目前環境缺少 Playwright / browser runtime，未執行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查 portable auth pack UI 標記，以 `node --check /tmp/login_admin_minimal.html.js` 檢查抽出的前端 script 語法，並執行 `python portable_auth_pack/scripts/verify_auth_pack.py` 驗證 API 行為。

狀態：Open


## 2026-06-14 帳號導航與統計儀表板 UI 截圖限制

- 本次調整帳號操作記錄導航、統計儀表板來源分流與第二層選單動態定位，屬可視 UI 變更。
- 目前環境缺少 Playwright / browser runtime，未執行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查導航入口、統計類別限制、帳號日期篩選、Index 隱藏邏輯與 portable auth pack 導航同步；以 `node --check` 檢查抽出的前端 script 語法。

狀態：Open

## 2026-06-14 帳號操作儀表板 UI 截圖限制

- 本次調整主系統與 `portable_auth_pack` 的帳號操作紀錄儀表板切換按鈕與統計 UI，屬可視 UI 變更。
- 目前環境仍缺少 Playwright / browser runtime，未執行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查「我的帳號操作紀錄」/「全體帳號操作紀錄」按鈕、一般使用者自我範圍限制與 portable auth pack 同步標記；以 `node --check` 驗證抽出的前端 script 語法，並以 `pytest tests` 與 portable verify script 驗證行為。

狀態：Open

## 2026-06-14 統計使用者多選 UI 截圖限制

- 本次將主系統統計儀表板與 `portable_auth_pack` 帳號操作統計的帳號篩選改為可搜尋多選清單，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，未能執行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 檢查多選清單、關鍵字搜尋、勾選 / 清除目前篩選的 DOM 與 JS 標記；以 `node --check` 驗證抽出的前端 script 語法；以 `pytest tests` 與 `portable_auth_pack/scripts/verify_auth_pack.py` 驗證功能行為。

狀態：Open

## 2026-06-14 多選窗格外點擊收合截圖限制

- 本次調整主系統與 `portable_auth_pack` 使用者 / 帳號多選窗格的外部點擊收合行為，屬可視 UI 互動改善。
- 目前環境仍缺少 Playwright / browser runtime，`python -m playwright --version` 回報 `No module named playwright`，因此未執行瀏覽器截圖或互動式 E2E 驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查 outside dismiss 綁定、窗格內點擊不收合、外部點擊只移除 `open` 而不清除選取狀態；以 `node --check` 驗證抽出的前端 script 語法。

狀態：Open

## 2026-06-14 統計儀表板個人紀錄提示 UI 截圖限制

- 本次將統計與檢核曲線儀表板的個人記錄模式改為固定提示與問號說明，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查提示文案、問號說明、個人模式隱藏使用者多選窗格與切換邏輯；以 `node --check /tmp/editor.html.js` 檢查抽出的前端 script 語法，並執行完整 `pytest tests`。

狀態：Open

## 2026-06-14 portable_auth_pack 個人帳號統計提示 UI 截圖限制

- 本次同步 `portable_auth_pack` 帳號操作統計的個人模式固定提示與問號說明，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供 portable auth pack 瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查 portable auth pack 的提示文案、問號說明、個人模式隱藏帳號多選窗格與切換邏輯；以 `node --check /tmp/login_admin_minimal.html.js` 檢查抽出的前端 script 語法，並執行 `python portable_auth_pack/scripts/verify_auth_pack.py`。

狀態：Open

## 2026-06-14 個人範圍問號 tooltip 截圖限制

- 本次將主系統與 `portable_auth_pack` 的個人範圍問號說明改為 hover / focus 皆會顯示的頁面內 tooltip，屬可視互動 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供 tooltip hover / click 截圖或 E2E 驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查 `role="tooltip"`、`aria-describedby`、`:focus-within` 顯示規則與移除原生 `title`；以 `node --check` 驗證抽出的前端 script 語法。

狀態：Open

## 2026-06-14 IP 多選篩選 UI 截圖限制

- 本次新增帳號操作統計儀表板的 IP / client_host 多選篩選，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法進行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_editor_auth_ui_static.py` 靜態檢查主系統與 portable auth pack 的 IP 多選 DOM、共用 multi-filter helper 與 `client_host` query 組裝；以 `node --check` 驗證相關 JS 語法。

狀態：Open

## 2026-06-15 Excel→SQL 使用者匯入 UI 截圖限制

- 本次新增 Excel→SQL 使用者上傳、預掃描、匯入確認與記錄批次刪除 UI，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 仍回傳 `No module named playwright`，無法執行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_user_imports.py` 靜態檢查 UI 控制與後端 registry 行為，以 `node --check /tmp/excel_dashboard.js` 驗證抽出的前端 script 語法，並執行 Excel→SQL 相關 pytest。

狀態：Open

## 2026-06-15 Excel 匯入作業中心 UI 截圖限制

- 本次新增「Excel 匯入作業中心」並調整 SQL 監控儀表板日期控制，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法提供瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_dashboard_static.py` 與 `tests/test_excel_to_sql_user_imports.py` 靜態檢查頁面導覽、拆頁、日期篩選文案與錯誤診斷 DOM / JS，並以 `node --check` 驗證相關 JS 語法。

狀態：Open

## 2026-06-15 Excel 匯入記錄管理 UI 截圖限制

- 本次移除 Excel 匯入記錄管理的刪除記錄操作入口，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_user_imports.py` 靜態檢查刪除按鈕、批次刪除入口、刪除 JS 函式與選取 checkbox 已移除，並以 `node --check api/static/excel_to_sql_import_records.js` 檢查前端語法。

狀態：Open

## 2026-06-15 匯入記錄刪除功能移除後 UI 截圖限制

- 本次再次調整 Excel 匯入記錄管理 UI，移除批次刪除與後端刪除能力相關入口。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_user_imports.py` 靜態檢查批次刪除按鈕、單筆刪除按鈕、選取 checkbox、刪除 JS 函式、刪除 route 與後端 `delete_records()` 均已移除；並以 `node --check api/static/excel_to_sql_import_records.js` 檢查前端語法。

狀態：Open

## 2026-06-16 Excel 匯入記錄 UI 截圖限制

- 本次新增 Excel 匯入作業中心「導入檔名」欄位與「查詢已匯入條目」快速按鈕，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法進行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_user_imports.py` / `tests/test_excel_to_sql_dashboard_static.py` 靜態檢查 DOM、欄寬、deep-link query 與按鈕邏輯；以 `node --check` 驗證相關 JS 語法；並執行完整 `pytest tests -q`。

狀態：Open


## 2026-06-18 Excel 匯入操作欄按鈕等寬 UI 截圖限制

- 本次調整 Excel 匯入作業中心匯入記錄操作欄三個按鈕等寬併列，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_user_imports.py` 靜態檢查三欄等寬 grid 與移除第二顆按鈕跨欄規則；以 `node --check api/static/excel_to_sql_import_records.js` 檢查前端 JS 語法。

狀態：Open


## 2026-06-18 Excel 匯入操作欄窄版直排 UI 截圖限制

- 本次將 Excel 匯入作業中心匯入記錄操作欄由電腦版同列改為窄版直排，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法提供瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_user_imports.py` 靜態檢查操作欄使用單欄 grid、縮小 actions 欄寬並移除三欄 grid；以 `node --check api/static/excel_to_sql_import_records.js` 檢查前端 JS 語法。

狀態：Open

## 2026-06-18 Excel 匯入作業中心 UI 截圖限制

- 本次調整錯誤診斷欄開合、匯入任務文案與匯入查詢儀表板標題，屬可視 UI 變更。
- 環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法提供瀏覽器截圖驗證。
- 替代驗證：以 `pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 靜態檢查 DOM / 文案 / JS 標記，並以 `node --check api/static/excel_to_sql_import_records.js` 驗證前端 JS 語法。

狀態：Open

## 2026-06-18 Excel audit 使用者篩選 UI 截圖限制

- 本次在 Excel→SQL 匯入查詢儀表板「最近 audit 事件」新增使用者多選篩選，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回報 `No module named playwright`，無法進行瀏覽器截圖驗證。
- 替代驗證：以 `tests/test_excel_to_sql_dashboard_static.py` 靜態檢查使用者多選 DOM、共用 `SraAuditTools` helper 與 `username_filter` query 組裝；以 `node --check api/static/excel_to_sql_dashboard.js` 驗證前端 JS 語法；並執行 Excel→SQL dashboard 相關 pytest。

狀態：Open

## 2026-06-18 Excel→SQL audit 表格 UI 截圖限制

- 本次調整 Excel→SQL 監控儀表板「最近 audit 事件」表格欄寬與換行，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法提供瀏覽器截圖驗證。
- 替代驗證：以 `pytest tests/test_excel_to_sql_dashboard_static.py -q` 檢查 DOM / CSS / render template；以 `node --check api/static/excel_to_sql_dashboard.js` 檢查前端 JS 語法。

狀態：Open

## 2026-06-18 Excel→SQL audit 表格截圖限制

- 本次調整 SQL 監控儀表板最近 audit 事件表欄寬與換行，屬可視 UI 變更。
- 目前環境執行 `python -m playwright --version` 回傳 `No module named playwright`，因此無法提供瀏覽器截圖驗證。
- 替代驗證：以 `pytest tests/test_excel_to_sql_dashboard_static.py -q` 檢查欄寬 CSS、`colgroup` 與表格欄位 class；以 `node --check api/static/excel_to_sql_dashboard.js` 檢查 dashboard JS 語法。

狀態：Open

## 2026-06-22 Excel→SQL audit 表欄寬調整截圖限制

- 本次調整 Excel→SQL 匯入查詢儀表板最近 audit 表格欄寬，屬可視 UI 變更。
- 執行 `python -m playwright --version` 回傳 `No module named playwright`，因此目前環境無法提供瀏覽器截圖驗證。
- 替代驗證：以 `pytest tests/test_excel_to_sql_dashboard_static.py -q` 靜態檢查欄寬 CSS，並以 `node --check api/static/excel_to_sql_dashboard.js` 確認 dashboard JS 語法。

狀態：Open

## 2026-06-22 Vercel mock preview login editor audit read-only filesystem

- 現象：Vercel 點擊「Vercel mock 閱讀者登入」後，`append_audit_event()` 預設寫入 `/var/task/logs/editor_audit.jsonl`，在 Vercel read-only filesystem 上建立 `/var/task/logs` 時觸發 `OSError: [Errno 30] Read-only file system`，導致 500。
- 狀態：Resolved。
- 修正：Vercel/NOW 環境未設定 `SRA_EDITOR_AUDIT_LOG` 時，Editor audit log 預設改寫入 `/tmp/sra-auth/editor_audit.jsonl`；落地部署預設路徑維持 `logs/editor_audit.jsonl`。
- 驗證：`PYTHONPATH=. pytest tests/test_vercel_deploy_config.py -q` 通過，且 mock preview login 測試確認 audit 寫入 `/tmp`。

## 2026-06-22 GitHub PR conflict too complex for web editor

- 現象：GitHub PR merge 曾顯示 `.codex/memory.md`、`api/routers/editor.py`、`api/static/excel_to_sql_dashboard.html` 衝突，且因衝突過於複雜無法用 web editor 解。
- 狀態：Resolved。
- 修正：衝突緩解後移除 legacy `api/routers/` 與 `api/static/` mirror files；runtime source 維持 `sra_api/`，top-level `api/` 只保留 shim 與 Vercel entrypoint；`.codex/memory.md` 保留 union merge。

## 2026-06-25 pip index 403 retry

- 現象：在目前執行環境跑 `python -m pip install --upgrade pip` 時，pip 嘗試連線套件索引出現 `Tunnel connection failed: 403 Forbidden` retry。
- 影響：本次所需套件已安裝，`python -m pip install -r requirements.txt` 顯示 requirements satisfied，pytest 可執行；但未來若需要下載新套件，可能受網路 / proxy 限制影響。
- 替代驗證：使用既有已安裝相依套件執行 py_compile、pytest 與 node 靜態檢查。

## 2026-06-25 Editor mapping metadata UI 截圖限制

首次發現：2026-06-25

問題：

- 本次讓 Editor form-config 依 ES mapping metadata 推導部分欄位 input type，屬可能影響表單呈現的 UI 行為；目前環境再次檢查 Playwright 時仍回報 `No module named 'playwright'`。

影響：

- 無法在目前環境提供瀏覽器截圖驗證 mapping metadata 合併後的表單呈現。

暫時解法：

- 使用 `tests/test_editor_form_config_mapping.py` 驗證 form-config response 已合併 mapping metadata，並用既有靜態 UI 測試與 JS syntax check 驗證前端 assets。

根本原因：

- 測試環境缺少 Playwright / browser runtime。

狀態：
Open

負責人：

-
