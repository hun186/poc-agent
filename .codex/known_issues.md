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

