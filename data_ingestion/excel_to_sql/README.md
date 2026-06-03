# Excel → SQL Server 匯入模組

此模組處理「使用者提供 Excel，系統先導入 SQL Server，再由既有 SQL→Elasticsearch 流程匯入 ES」的前置資料整理工作。

## 入口

```bash
python -m data_ingestion.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json
```

## 主要能力

- 讀取單一 Excel 或來源目錄中的多個 Excel。
- 依 JSON 設定檔將 Excel 欄位對應到 SQL Server field。
- 透過 `python-dateutil` 將常見西元/民國年日期字串正規化成 SQL 可接收的日期物件。
- 支援單一設定檔匯入同一 Excel 內多個工作表，並支援工作表名稱智慧比對。
- 支援欄名浮動比對：`exact`、`smart`、`normalized`、`prefix`、`contains`、`aliases`；`smart` 也會在前綴比對後嘗試唯一包含比對，例如「敘述」可比對到「作業敘述」。
- 以來源欄名與內容計算 SHA-256，寫入 `hash_value` 避免重複導入。
- 目的資料表不存在時可依設定檔 mapping 自動建立 table、欄位與去重索引。
- 每列處理結果寫入 SQL audit table。
- 可自動偵測本機已安裝的 SQL Server ODBC Driver 18/17，降低不同環境 driver 名稱差異造成的連線失敗。
- 支援檔案匯入失敗後依設定間隔重試，達到上限後才搬到 failed archive。
- 成功/失敗檔案搬移到 archive 目錄。
- 提供 API 與 `/excel-to-sql-dashboard` 儀表板監控 audit table。
- 可由儀表板用既有帳號權限刪除已匯入 SQL 的錯誤列，操作會寫回 audit table。

## 工作表設定與 `sheet_match`

`source.sheet` 可以是單一工作表名稱，也可以是工作表名稱陣列；如果要一次匯入同一個 Excel 裡的多個工作表，請使用陣列，不要在 JSON 中重複寫兩個 `sheet` key。也可使用同義設定 `source.sheets` / `source.sheet_names`，並用 `source.sheet_aliases` 補充別名。

```json
"source": {
  "directory": "./data/excel_inbox",
  "file_pattern": "*.xlsx",
  "sheet": ["漁業活動紀錄", "漁業活動資料"],
  "sheet_match": "smart",
  "header_row": 1,
  "start_row": 2,
  "end_row": 0
}
```

`source.sheet_match` 控制設定名稱與 Excel 實際工作表名稱的比對方式，預設是 `smart`：

| 模式 | 說明 |
| --- | --- |
| `exact` | 只接受完全相同名稱。 |
| `normalized` | 忽略大小寫與名稱中的空白後比對。 |
| `prefix` | 設定名稱與實際工作表名稱互為前綴即可，例如 `漁業活動資料` 可比對到 `漁業活動資料_A`。 |
| `contains` | 設定名稱與實際工作表名稱互相包含即可，比 `prefix` 更寬鬆。 |
| `smart` | 依序做 `exact`、`normalized`、`prefix`，並接受明顯共同前綴；例如設定 `漁業活動紀錄` 可比對到實際工作表 `漁業活動資料`。 |

若同一個 Excel 內有多個工作表符合比對條件，系統會全部依 Excel 原本工作表順序匯入。非精準比對會記錄 `sheet_smart_match` audit/log，方便確認智慧比對結果。

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
- `file_processor.py`：單一 Excel 檔的工作表解析、欄位比對、去重、SQL 寫入與 audit/log 寫入。

## 檔案分工

- `ingest.py`：CLI、整批匯入 orchestration、重試、truncate 與 archive。
- `file_processor.py`：單檔 Excel 匯入流程，包含 Excel 讀取、欄位比對、去重、SQL 寫入與 audit 寫入。
- `models.py` / `utils.py` / `date_utils.py` / `sql_utils.py` / `audit.py`：匯入流程共用工具模組。
- `dashboard.py`：掃描可監控任務、查詢 audit table、彙整監控資料。
- `api/routers/excel_to_sql.py`：提供儀表板頁面與 JSON API。
- `api/static/excel_to_sql_dashboard.html`：瀏覽器儀表板。
