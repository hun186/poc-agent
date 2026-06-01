# Excel → SQL Server 匯入模組

此模組處理「使用者提供 Excel，系統先導入 SQL Server，再由既有 SQL→Elasticsearch 流程匯入 ES」的前置資料整理工作。

## 入口

```bash
python -m agent.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json
```

## 主要能力

- 讀取單一 Excel 或來源目錄中的多個 Excel。
- 依 JSON 設定檔將 Excel 欄位對應到 SQL Server field。
- 透過 `python-dateutil` 將常見西元/民國年日期字串正規化成 SQL 可接收的日期物件。
- 支援欄名浮動比對：`exact`、`smart`、`normalized`、`prefix`、`contains`、`aliases`。
- 以來源欄名與內容計算 SHA-256，寫入 `hash_value` 避免重複導入。
- 目的資料表不存在時可依設定檔 mapping 自動建立 table、欄位與去重索引。
- 每列處理結果寫入 SQL audit table。
- 可自動偵測本機已安裝的 SQL Server ODBC Driver 18/17，降低不同環境 driver 名稱差異造成的連線失敗。
- 支援檔案匯入失敗後依設定間隔重試，達到上限後才搬到 failed archive。
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

## 程式分工

`ingest.py` 保留 CLI 與匯入流程 orchestration；共用邏輯已拆出：

- `models.py`：匯入結果 dataclass。
- `utils.py`：設定檔、路徑、欄名與 JSON 序列化工具。
- `date_utils.py`：Excel/字串日期正規化與 mapping 值轉換。
- `sql_utils.py`：SQL Server 連線字串、ODBC driver 偵測、SQL identifier 與 hash 欄位 DDL 工具。
- `audit.py`：audit table 建表、寫入與欄名智慧比對 audit 結果產生。

## 檔案分工

- `ingest.py`：CLI、Excel 讀取、欄位比對、去重、SQL 寫入、archive、audit 寫入。
- `models.py` / `utils.py` / `date_utils.py` / `sql_utils.py` / `audit.py`：匯入流程共用工具模組。
- `dashboard.py`：掃描可監控任務、查詢 audit table、彙整監控資料。
- `api/routers/excel_to_sql.py`：提供儀表板頁面與 JSON API。
- `api/static/excel_to_sql_dashboard.html`：瀏覽器儀表板。
