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
