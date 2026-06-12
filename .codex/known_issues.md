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
