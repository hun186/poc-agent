# Excel → SQL Server 匯入模組

此模組處理「使用者提供 Excel，系統先導入 SQL Server，再由既有 SQL→Elasticsearch 流程匯入 ES」的前置資料整理工作。

## 入口

```bash
python -m agent.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json
```

## 主要能力

- 讀取單一 Excel 或來源目錄中的多個 Excel。
- 依 JSON 設定檔將 Excel 欄位對應到 SQL Server field。
- 支援欄名浮動比對：`exact`、`smart`、`normalized`、`prefix`、`contains`、`aliases`。
- 以來源欄名與內容計算 SHA-256，寫入 `hash_value` 避免重複導入。
- 每列處理結果寫入 SQL audit table。
- 成功/失敗檔案搬移到 archive 目錄。
- 提供 API 與 `/excel-to-sql-dashboard` 儀表板監控 audit table。
- 可由儀表板用既有帳號權限刪除已匯入 SQL 的錯誤列，操作會寫回 audit table。

## 儀表板任務顯示規則

儀表板不會顯示所有 JSON 設定檔；只會掃描 `config/excel_to_sql/*.json` 中明確開啟：

```json
"dashboard": {
  "enabled": true,
  "name": "船舶活動 Excel 匯入監控"
}
```

的設定檔。`name` 會作為儀表板下拉選單顯示名稱；若未填，會退回使用 `destination.table` 或檔名。

## 檔案分工

- `ingest.py`：CLI、Excel 讀取、欄位比對、去重、SQL 寫入、archive、audit 寫入。
- `dashboard.py`：掃描可監控任務、查詢 audit table、彙整監控資料。
- `api/routers/excel_to_sql.py`：提供儀表板頁面與 JSON API。
- `api/static/excel_to_sql_dashboard.html`：瀏覽器儀表板。
