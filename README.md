# SRA-Structured Retrieval Agent Project Analysis

## 專案簡介 (Project Overview)
本專案是一個基於 **FastAPI** 和 **Elasticsearch** 建構的 **RAG (Retrieval-Augmented Generation)** 代理人系統，稱為 **SRA (Structured Retrieval Agent)**。
核心設計是透過一個 **Router Agent** 分析使用者的意圖，將任務分流到不同的子代理人（Reporting, Style Transfer, Doc Follow-up），並支援基於 Topic 的動態索引檢索。同時具備完整的對話歷史 (Session Store) 與遙測 (Telemetry) 機制。

## 技術堆疊 (Tech Stack)

### Backend & API
- **Language:** Python 3.10+
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Async Web Server)
- **Server:** Uvicorn

### LLM & Agent Framework
- **Framework:** Custom Architecture (Not relying on LangChain/LlamaIndex for core loop)
- **LLM Client:** Custom Wrapper (`agent.llm_utils.ollama_client`) supporting OpenAI-compatible APIs (likely Ollama).
- **Core Pattern:** Router-Dispatcher Pattern (`SRA_REPORT`, `SRA_STYLE`, `DOC_FOLLOWUP`, `PURE_LLM`).

### Data & Retrieval
- **Vector Database / Search Engine:** [Elasticsearch](https://www.elastic.co/)
- **Retrieval Strategy:** Hybrid Search (Keyword + Vector), Aggregation (Month/Quarter stats).
- **Session Storage:** File-based Session Store (`.agent_sessions/`).

## 模組說明 (Module Descriptions)

### 1. API Layer (`api/`)
- **[main.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/api/main.py)**: 應用程式入口，初始化 FastAPI App 與 Middleware。
- **[routers/chat.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/api/routers/chat.py)**: 核心 Chat Completion 端點 (`/v1/chat/completions`)，處理 Request/Response 格式轉換、Session Context 管理與使用者意圖初步判讀。

### 2. Core Agent Layer ([agent/](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/api/routers/chat.py#165-181))
- **[agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/agent.py)**: 核心代理人邏輯。包含 [answer_with_routing](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/agent.py#256-605) (主入口) 與 [llm_route_task](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/agent.py#130-205) (任務分流器)。負責決定要呼叫哪個子代理人。
- **[report_agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/report_agent.py) (SRA_REPORT)**: 負責生成深度分析報告。流程：精煉問題 -> 數據檢索 (`data_agent`) -> 證據壓縮/篩選 -> LLM 撰寫報告 -> 表格修正。
- **[style_agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/style_agent.py) (SRA_STYLE)**: 風格模仿代理人。
- **[doc_followup_agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/doc_followup_agent.py) (DOC_FOLLOWUP)**: 針對已檢索文件的追問代理人。
- **`data_agent/`**: 負責與 Elasticsearch 互動，執行檢索與統計聚合。

### 3. Utility & Infrastructure
- **`agent/es/`**: Elasticsearch 客戶端封裝，包含 `query_body.py` (ES Query 建構) 與 `es_client.py`。
- **`config/`**: 專案設定載入（如 `bootstrap.py`）。
- **`telemetry.py`**: 遙測與日誌記錄系統。

## SQL 匯入 Elasticsearch 使用說明

本專案提供 `data_ingestion/sql_to_es/ingest_sql.py`，可依 JSON 設定檔，從遠端 SQL Server 讀取資料後 bulk 寫入 Elasticsearch。

### 1) 執行指令

在專案根目錄執行：

```bash
python -m data_ingestion.sql_to_es.ingest_sql --config config/sql_import/srp_import.json
```

### 2) JSON 設定檔結構（範例：`config/sql_import/srp_import.json`）

```json
{
  "index_name": "srp_test",
  "db": {
    "driver": "ODBC Driver 17 for SQL Server",
    "server": "192.168.0.136",
    "database": "Test_SRP",
    "trusted_connection": false,
    "user": "sa",
    "password": "your_password",
    "encrypt": false,
    "trust_server_certificate": false
  },
  "source": {
    "table": "dbo.Table_SRP",
    "columns": {
      "id": "AUTO",
      "title": "SUBJ",
      "content": "TEXT",
      "row_dt": "CrtDt"
    },
    "query": {
      "where": "",
      "order_by": "[CrtDt] DESC",
      "top": 0
    }
  },
  "import": {
    "batch_size": 500,
    "lang_code": "C",
    "user_name": "sql_importer",
    "op_type": "create",
    "dedup_by_content": false,
    "selector_name": "SQLImport",
    "raw_type_code": "05"
  }
}
```

### 3) 各欄位設定重點

- `index_name`：目標 ES index 名稱；若未填，會回退讀取 `.env` 的 `ES_INDEX`。
- `db.driver`：ODBC driver 名稱（常見為 `ODBC Driver 17 for SQL Server`）；也可設為 `auto`（或留空）讓程式依本機已安裝清單自動挑選 SQL Server ODBC driver，優先使用 `ODBC Driver 18 for SQL Server`，再依序退回 17/13、Native Client 或 `SQL Server`。若指定的 driver 未安裝，程式會嘗試改用本機可用版本。
- `db.server` / `db.database`：SQL Server 連線位址與資料庫名稱。
- `db.trusted_connection`：
  - `true`：使用整合驗證（Windows auth）。
  - `false`：需提供 `db.user`、`db.password`。
- `db.encrypt` / `db.trust_server_certificate`：TLS 連線相關設定。
- `source.table`：來源資料表（可含 schema，例如 `dbo.Table_SRP`）。
- `source.columns.content`：必填，正文欄位。
- `source.columns.id`：建議填；可用於穩定產生文件 ID。
- `source.columns.title`：可選；未提供時會由內容前段自動產生標題。
- `source.columns.row_dt`：可選；來源資料時間欄位（會映射到 `sourceSql.rowDT`）。
- `source.query.where`：可加自訂條件（會與「內容不為空」條件一起組成 WHERE）。
- `source.query.order_by`：排序條件；未提供時若有 id 欄位會用 id 排序。
- `source.query.top`：限制讀取筆數（`0` 代表不限制）。
- `import.batch_size`：每批抓取與 bulk 寫入筆數。
- `import.op_type`：
  - `create`：同 `_id` 已存在時跳過（不覆蓋）。
  - `index`：同 `_id` 已存在時覆寫。
- `import.dedup_by_content`：
  - `true`：以內容 hash 當 `_id`，相同內容會視為同一筆。
  - `false`：優先使用 id 欄位（若有）計算 `_id`。
- `import.lang_code` / `import.user_name` / `import.selector_name` / `import.raw_type_code`：寫入文件 metadata。

### 4) 匯入行為與輸出

- 腳本會自動檢查 index，不存在時建立 mappings。
- 匯入過程會逐批輸出：
  - 成功筆數
  - 已存在而跳過筆數（常見於 `op_type=create`）
  - 失敗筆數
- 最後會輸出總結統計（成功 / 跳過 / 失敗 / 空內容）。

### 5) 常見問題

- 找不到設定檔：請確認路徑是 `config/sql_import/srp_import.json`（不是 `config/srp_import.json`）。
- 連線 SQL 失敗：確認 ODBC driver、帳密、網路、防火牆與 SQL Server 權限。
- 寫入 ES 失敗：確認 `.env` 的 `ES_URL` / `ES_USERNAME` / `ES_PASSWORD` 已正確設定。



## Excel 匯入 SQL Server 使用說明

本專案將 Excel→SQL 匯入獨立成 `data_ingestion/excel_to_sql/` 小模組，並將 SQL→ES 匯入放在 `data_ingestion/sql_to_es/`，避免資料處理流程與 agent runtime 混淆；操作概念沿用 SQL 匯入工具：以 JSON 設定檔描述連線、來源與批次匯入參數。此工具可讀取單一 Excel，也可監看一個來源目錄，批次抓取目錄下的 Excel 檔，依欄位對應寫入 SQL Server 目的資料表，並提供去重、檔案歸檔、JSONL log 與 SQL audit table，方便後續做匯入監控儀表板。

### 1) 執行指令

在專案根目錄執行：

```bash
python -m data_ingestion.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json
python -m data_ingestion.excel_to_sql.ingest --config config/excel_to_sql/git_ignore/vessel_activities.json
```

### 2) JSON 設定檔結構（範例：`config/excel_to_sql/vessel_activities.example.json`）

```json
{
  "db": {
    "driver": "auto",
    "server": "192.168.0.10",
    "database": "mydatabase",
    "trusted_connection": false,
    "user": "myuser",
    "password": "mypwd",
    "encrypt": true,
    "trust_server_certificate": true
  },
  "source": {
    "directory": "./data/excel_inbox",
    "file_pattern": "*.xlsx",
    "recursive": false,
    "excel_path": "./data/source.xlsx",
    "sheet": ["漁業活動紀錄", "漁業活動資料"],
    "sheet_match": "smart",
    "header_row": 1,
    "start_row": 2,
    "end_row": 0
  },
  "destination": {
    "table": "vessel_activities",
    "auto_create_table": true,
    "auto_create_missing_fields": true,
    "default_field_type": "NVARCHAR(MAX)",
    "hash_field": "hash_value",
    "auto_create_hash_field": true,
    "hash_field_type": "CHAR(64)",
    "create_hash_index": true
  },
  "mappings": [
    { "source_column": "日期", "dest_field": "activity_date", "required": true, "value_type": "date", "dest_field_type": "DATE" },
    { "source_column": "地點", "dest_field": "location", "dest_field_type": "NVARCHAR(255)" },
    { "source_column": "數量", "dest_field": "vessel_count", "dest_field_type": "INT" },
    { "source_column": "船名", "match": "prefix", "dest_field": "vessel_names", "dest_field_type": "NVARCHAR(MAX)" },
    { "source_column": "敘述", "match": "contains", "dest_field": "activity_description", "dest_field_type": "NVARCHAR(MAX)" }
  ],
  "import": {
    "batch_size": 500,
    "skip_empty_rows": true,
    "truncate_before_load": false,
    "fast_executemany": true
  },
  "retry": {
    "max_attempts": 3,
    "interval_seconds": 60
  },
  "archive": {
    "enabled": true,
    "success_dir": "./data/excel_archive/success",
    "fail_dir": "./data/excel_archive/failed",
    "log_dir": "./logs/excel_to_sql"
  },
  "audit": {
    "enabled": true,
    "table": "dbo.ExcelImportAudit"
  },
  "dashboard": {
    "enabled": true,
    "name": "船舶活動 Excel 匯入監控"
  }
}
```

### 3) 各欄位設定重點

- `db.*`：與 SQL 匯入 Elasticsearch 工具相同，設定 SQL Server ODBC 連線。
- `db.driver`：可填明確 driver 名稱，也可填 `auto`（或留空）讓程式依本機已安裝清單自動挑選；會優先使用 `ODBC Driver 18 for SQL Server`，若未安裝則自動退回 `ODBC Driver 17 for SQL Server` 等可用 SQL Server driver。若設定檔指定的 driver 不存在，程式也會嘗試自動改用本機已安裝版本，避免不同環境安裝 18/17 造成 `IM002` 錯誤。
- `source.directory`：來源目錄；若有設定，程式會抓此目錄下符合 `source.file_pattern` 的 Excel 逐檔匯入，適合使用者定期把新增 Excel 丟到固定資料夾的情境。
- `source.file_pattern`：來源目錄檔名 pattern，預設可用 `*.xlsx`；程式會略過 Excel 暫存檔 `~$...`。
- `source.recursive`：是否遞迴掃描來源目錄子資料夾。
- `source.excel_path`：單檔模式使用；若未設定 `source.directory`，就會改讀此 Excel 檔案。相對路徑會先以設定檔所在目錄解析，找不到才改以專案根目錄解析。
- `source.sheet`：來源工作表名稱；可填單一字串（例如 `"漁業活動紀錄"`），也可填字串陣列（例如 `["漁業活動紀錄", "漁業活動資料"]`）讓同一個 JSON 設定檔一次匯入同一 Excel 內多個工作表。JSON 不允許同一層出現兩個 `sheet` key；若要多個工作表，請把 `sheet` 改成陣列，或使用同義設定 `source.sheets` / `source.sheet_names`。
- `source.sheet_aliases`：工作表名稱別名清單，會與 `source.sheet` / `source.sheets` 一起參與比對；適合把「正式設定名稱」與「實際 Excel 常見名稱」都放進同一份設定。
- `source.sheet_match`：工作表名稱比對模式，預設為 `smart`。支援：
  - `exact`：只接受完全相同的工作表名稱。
  - `normalized`：先去除前後空白、忽略大小寫並移除名稱中的空白後再比對，例如 `Sheet 1` 可比對到 `sheet1`。
  - `prefix`：接受設定名稱與實際工作表名稱互為前綴，例如設定 `漁業活動資料` 可比對到 `漁業活動資料_A` / `漁業活動資料_B`。
  - `contains`：接受設定名稱與實際工作表名稱互相包含；比 `prefix` 更寬鬆，工作表很多時請謹慎使用。
  - `smart`：先做 `exact`，再做 `normalized`，再做 `prefix`；另外若兩個名稱有明顯共同前綴也會接受，例如設定 `漁業活動紀錄` 可比對到實際工作表 `漁業活動資料`，因為兩者共同前綴為「漁業活動」。若單一 Excel 內有多個工作表符合，會全部依 Excel 原本工作表順序匯入。
- `source.header_row`：欄名所在列號，預設為 `1`。
- `source.start_row`：資料起始列號，預設為 `header_row + 1`。
- `source.end_row`：資料結束列號；`0` 代表讀到工作表最後一列。
- `destination.table`：目的 SQL Server 資料表（可含 schema，例如 `dbo.Table_SRP`）。範例使用 `vessel_activities`；其 `auto` primary key 由 SQL Server 自動填入，設定檔不需對應。
- `destination.auto_create_table`：是否在目的 table 不存在時自動執行 `CREATE TABLE`，預設 `true`；欄位會依 `mappings[*].dest_field` 與 `dest_field_type` / `destination.default_field_type` 建立，並會一併建立去重欄位與 filtered unique index（若 `destination.create_hash_index=true`）。若 SQL 帳號沒有 `CREATE TABLE` / `CREATE INDEX` 權限，可設為 `false` 並由 DBA 手動建立資料表。
- `destination.auto_create_missing_fields`：是否在目的 table 缺少 `mappings[*].dest_field` 欄位時自動執行 `ALTER TABLE ... ADD`，預設 `true`；例如缺少 `vessel_names` 時會在匯入前自動補欄位，避免整批資料因「無效的資料行名稱」失敗。若 SQL 帳號沒有 DDL 權限，可設為 `false` 並由 DBA 手動建立欄位。
- `destination.default_field_type`：自動新增一般目的欄位時的預設型別，預設 `NVARCHAR(MAX)`；建議在個別 mapping 使用 `dest_field_type` 明確指定重要欄位型別。
- `destination.hash_field`：目的資料表用來存放去重 hash 的欄位，預設 `hash_value`；內容是 SHA-256 的十六進位 digest，固定 64 個 ASCII 字元（256-bit），所以 `CHAR(64)` / `VARCHAR(64)` 足夠完整存放，不會截斷。
- `destination.auto_create_hash_field`：是否在目的 table 缺少去重欄位時自動執行 `ALTER TABLE ... ADD`，預設 `true`；若 SQL 帳號沒有 DDL 權限，可設為 `false` 並由 DBA 手動建立欄位。
- `destination.hash_field_type`：自動新增去重欄位時使用的型別，預設 `CHAR(64)`；為避免 SQL 注入，僅允許 `CHAR(64)`、`NCHAR(64)`、`VARCHAR(64)`、`NVARCHAR(64)`。
- `destination.create_hash_index`：自動新增去重欄位後是否建立 filtered unique index（`WHERE hash_value IS NOT NULL`）以強化防重，預設 `true`。
- `mappings`：Excel 欄位與 SQL 欄位對應表。
  - `source_column`：以 Excel 標題列欄名指定來源欄位；預設 `match: "smart"`，會先精準比對，再做正規化、前綴與唯一包含比對。
  - `match`：可設 `exact`、`smart`、`normalized`、`prefix`、`contains`。`smart` 會先做精準比對，再做正規化、前綴與唯一包含比對；例如設定 `source_column: "敘述"` 可比對到 Excel 欄名「作業敘述」。若要明確允許欄名包含關係，可設定 `match: "contains"`；若主要是欄名前綴浮動，例如「船名(多艘)」或「船名...」，可設定 `match: "prefix"`，且目前 `prefix` 在找不到前綴時也會退回唯一包含比對，避免「敘述」遇到「作業敘述」這類欄名時整檔失敗。
  - `aliases`：可提供來源欄位別名清單，降低欄名浮動造成的失敗。
  - 也可改用 `source_column_letter`（例如 `A`）或 `source_column_index`（例如 `1`），適合標題列重複或沒有穩定欄名時使用。
  - `dest_field`：目的 SQL 欄位名稱。
  - `dest_field_type` / `destination_field_type` / `sql_type`：自動新增目的欄位時使用的 SQL Server 型別；支援常見純量型別（例如 `NVARCHAR(255)`、`NVARCHAR(MAX)`、`INT`、`BIGINT`、`DECIMAL(18,2)`、`DATE`、`DATETIME2`）。未設定時，日期 mapping 使用 `DATE`，其他欄位使用 `destination.default_field_type`。
  - `required`：設為 `true` 時，該欄在資料列為空會記錄該列失敗、寫入 audit/log，且不匯入該列。
  - `default`：來源值空白時要寫入的預設值。
  - `value_type` / `data_type` / `type`：可設為 `date`，透過 `python-dateutil` 解析並把 Excel 日期儲存格或日期字串正規化為 Python `date` 物件後交給 pyodbc 寫入 SQL Server `date` / `datetime` 欄位；支援西元 `YYYY-MM-DD`、`YYYY/MM/DD`、`YYYYMMDD`，以及民國年 `114/07/04`（會轉為 `2025-07-04`）。若欄名為「日期」或目的欄位為 `*_date`，未明確設定時也會自動套用日期正規化。
- `import.batch_size`：每批 `executemany` 寫入筆數。
- `import.skip_empty_rows`：是否跳過所有對應欄位皆為空的列。
- `import.truncate_before_load`：寫入前是否先 `TRUNCATE TABLE`；預設 `false`，開啟前請確認權限與資料保留需求。若是長期增量匯入，通常不建議開啟。
- `import.fast_executemany`：啟用 pyodbc 批次寫入最佳化。
- `retry.max_attempts`：單一 Excel 檔案匯入失敗或仍有失敗列時，最多嘗試次數；預設為 `1`（不重試）。
- `retry.interval_seconds`：兩次重試之間等待秒數；預設為 `0`。在達到 `retry.max_attempts` 前，檔案不會被搬到 `archive.fail_dir`。
- `archive.enabled`：是否在檔案處理後搬移來源 Excel；目錄模式預設啟用。
- `archive.success_dir` / `archive.fail_dir`：成功檔案備份目錄與失敗待確認目錄。
- `archive.log_dir`：JSONL log 輸出目錄，檔名格式為 `excel_to_sql_YYYYMMDD.jsonl`。
- `audit.enabled`：是否寫入 SQL audit table。
- `audit.table`：audit table 名稱；不是依目的資料表自動命名，而是由設定檔指定；若省略，系統使用預設 `dbo.ExcelImportAudit`。若該 audit table 不存在，程式會自動建立預設欄位結構。
- `dashboard.enabled`：是否讓此設定檔出現在 `/excel-to-sql-dashboard` 的任務下拉選單；儀表板只會掃描並顯示此值為 `true` 的設定檔。
- `dashboard.name`：儀表板顯示名稱；未填時會退回使用 `destination.table` 或設定檔檔名。

### 4) 去重與 audit 機制

- 每一列會以「來源欄名 + 來源內容」組成穩定字串，再計算 SHA-256，寫入 `destination.hash_field`（預設 `hash_value`）。
- SHA-256 輸出是 256-bit；以十六進位表示時固定為 64 個字元，因此欄位長度 64 是剛好完整存放，不是截短版 hash。若使用 `NCHAR(64)` / `NVARCHAR(64)` 也可存放，但會使用較多儲存空間。
- 寫入前會先查目的 table 的 `hash_value`；若已存在，就將該列標示為 `duplicate` 並略過，不會重複導入。
- 同一次執行中若不同檔案或不同列產生相同 hash，也會略過後續重複列。
- 每一筆資料列的處理結果都會寫入 SQL audit table，包含 `run_id`、來源檔案、工作表、列號、hash、目的 table、狀態、訊息、row payload 與處理時間，方便後續儀表板彙整每天收到資料與處理結果。audit table 名稱由 `audit.table` 控制；未設定時使用 `dbo.ExcelImportAudit`，不是依 `destination.table` 自動產生不同名稱。
- 若工作表名稱採用智慧比對（例如設定「漁業活動紀錄」比對到實際工作表「漁業活動資料」），會以 `sheet_smart_match` 狀態寫入 audit table 與 JSONL log，方便事後檢查工作表名稱浮動是否符合預期。
- 若欄位採用智慧比對（例如「船名」前綴比對到「船名...」，或「敘述」以包含關係比對到「作業敘述」），也會以 `header_smart_match` 狀態寫入 audit table 與 JSONL log，方便事後檢查欄名浮動是否符合預期。

### 5) 匯入行為與輸出

- 腳本會以唯讀模式開啟 Excel，並以 `data_only=true` 讀取公式儲存值。
- 寫入 SQL Server 時會自動為 table 與 field 加上 SQL Server 方括號引用，降低保留字或特殊字元造成的問題。
- 日期欄位會先正規化再寫入 SQL，例如 `2025-07-04`、`2025/07/04` 與 `114/07/04` 都會以一致的 SQL 日期值匯入。
- 匯入過程會逐批輸出新增筆數、重複略過筆數與失敗筆數，並在 log 檔留下批次與檔案處理事件。
- 若檔案處理成功，會搬到 `archive.success_dir`；若檔案或資料處理失敗，會依 `retry.max_attempts` / `retry.interval_seconds` 先等待並重試，達到上限後仍失敗才搬到 `archive.fail_dir` 等待人工確認。

### 6) 常見問題

- 找不到 Excel 檔案：確認 `source.directory` 或 `source.excel_path` 路徑；相對路徑會先以設定檔所在目錄解析，找不到才改以專案根目錄解析。
- 找不到工作表或欄名：確認 `source.sheet`（或 `source.sheets`）與 `mappings[].source_column` 是否與 Excel 一致；若工作表只是名稱略有差異，可將 `source.sheet_match` 設為 `smart`、`prefix` 或 `contains`，或加入 `source.sheet_aliases`。有重複欄名時請改用 `source_column_letter` 或 `source_column_index`。
- 寫入 SQL 失敗：確認目的資料表欄位型別、必要欄位、ODBC driver、帳密、網路、防火牆與 SQL Server 權限。若錯誤為 `IM002` 找不到 driver，可將 `db.driver` 設為 `auto`，讓程式自動偵測本機 ODBC Driver 18/17。
- 去重欄位錯誤：預設會自動在目的 table 新增 `hash_value`（或 `destination.hash_field` 指定的欄位）並建立 unique index；若 SQL 帳號沒有 `ALTER TABLE` / `CREATE INDEX` 權限，請由 DBA 手動新增 `CHAR(64)` 或 `NVARCHAR(64)` 欄位，或把 `destination.create_hash_index` 設為 `false`。


### 7) 自動化監控儀表板

啟動 API 後，可先進管理頁面登入，再開 Excel→SQL 儀表板：

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

```text
http://localhost:8000/editor
http://localhost:8000/excel-to-sql-dashboard
```

管理頁面是 `/editor`，Excel→SQL 儀表板是 `/excel-to-sql-dashboard`。儀表板會沿用 `/editor` 登入後儲存在瀏覽器的 `sra_editor_token`，所以進入方式是：先到 `/editor` 登入，再開 `/excel-to-sql-dashboard`。頁面會先呼叫 `/v1/excel-to-sql/dashboard-tasks` 掃描 `config/excel_to_sql/*.json`，只列出 `dashboard.enabled=true` 的匯入任務；選定任務後再呼叫 `/v1/excel-to-sql/dashboard` 讀取該任務設定的 SQL audit table，呈現：

- 指定天數內的總事件、新增、重複略過、失敗、欄名智慧比對數。
- 每日各狀態筆數，方便監控每天收到資料與處理結果。
- 各 Excel 檔案處理彙總。
- 最近 audit 事件與 row payload，方便追查失敗列或欄名智慧比對。
- 對有 `hash_value` 的事件提供「刪除SQL列」操作，可用既有登入帳號刪除目的 SQL table 中對應列，並寫入 `sql_deleted` / `sql_delete_not_found` audit 記錄。若資料已進 ES，仍需到 ES 編輯介面另行處理。

可在頁面上選擇監控任務，或手動調整設定檔路徑、回看天數與列數上限。若 audit table 尚未建立，儀表板會提示目前無 audit table。

### 8) 模組區塊化

Excel→SQL 匯入已移到 `data_ingestion/excel_to_sql/`，SQL→ES 匯入已移到 `data_ingestion/sql_to_es/`，讓資料處理流程與 agent runtime 分離：

- `data_ingestion/excel_to_sql/ingest.py`：匯入 CLI、欄名比對、去重、archive、audit 寫入。
- `data_ingestion/excel_to_sql/dashboard.py`：監控儀表板的任務掃描、audit table 查詢與彙總邏輯。
- `data_ingestion/excel_to_sql/README.md`：此 Excel→SQL 前置流程的獨立說明文件。
- `data_ingestion/sql_to_es/ingest_sql.py`：SQL Server 匯入 Elasticsearch CLI。

## 環境變數（.env）與 Index 多環境設定

### .env 載入優先順序
專案使用 `config/bootstrap.py` 的 `bootstrap_env()` 載入環境變數，優先順序如下（高 → 低）：

1. OS 環境變數（系統已注入）
2. `.env.local`
3. `.env.{APP_ENV}`（例如 `.env.dev`、`.env.local`、`.env.prod`）
4. `.env`

> `APP_ENV` 若未設定，預設為 `dev`。

### 報告生成逾時設定

模型收到 ES 檢索結果後，若需要較長時間進行綜整、統計表或 SWOT 報告撰寫，可透過環境變數延長等待時間：

```env
# 單位：秒；預設 300 秒。大型報告可先調整為 600 或更高。
REPORT_LLM_TIMEOUT=600
```

`REPORT_TIMEOUT` 仍保留為向後相容別名；若同時設定，`REPORT_LLM_TIMEOUT` 優先。

### Index 設定檔載入順序
`config/index_loader.py` 支援多種方式指定設定檔：

1. `INDEXES_CONFIG` 或 `INDEX_CONFIG`（向後相容）
   - 可填單一路徑，或多路徑（用 `,` 或 `:` 分隔；Windows 可用 `;`）
2. `INDEXES_CONFIGS`
   - 多路徑清單，後者優先
3. 若都未指定：
   - 先載入 `config/indexes.yaml`
   - 再載入 `config/indexes.{APP_ENV}.yaml`（若存在）

### 合併規則（重要）
- `topic_index_map.<topic>.indexes`：**擴增式覆蓋**（base + override，去重、保序）
- 其他欄位（例如 `description`）：**後者覆蓋前者**（last-file-wins）
- `default_indexes`：若後者有提供，則覆蓋前者

### 建議用法範例

`.env`（共用）
```env
APP_ENV=local
```

`config/indexes.yaml`（共用基礎）
```yaml
topic_index_map:
  mil_intel:
    indexes: [mil_reports-01, nav_intel_sentences_synthetic_v1, satmeta]
```

`config/indexes.local.yaml`（本機擴增）
```yaml
topic_index_map:
  mil_intel:
    indexes: [shipsprite_sql]
```

最終 `mil_intel.indexes` 會是：
`[mil_reports-01, nav_intel_sentences_synthetic_v1, satmeta, shipsprite_sql]`

## ES 結構化資料人工編輯介面與帳號設定

本專案提供一個人工校正 Elasticsearch 結構化文件的網頁介面：啟動 API 後開啟 `/editor`。

### 功能

- 使用者可登入後搜尋指定 Elasticsearch index 中的文件。
- 載入文件後可用表單修改常用結構化欄位（標題、主旨、日期、事件主體/客體/地點/描述、核心實體、地點清單）。
- 可用表單新增、刪除或修改證據片段（`multidim_event_json.evidence_snippets` 的文字、來源 ID、段落 ID），不需要一般使用者直接編輯 JSON。
- 進階使用者仍可切換到 JSON 檢視完整 `_source`，並在儲存前套用表單到 JSON。
- 每次實際寫入 Elasticsearch 的修改都會記錄稽核 log，預設位置為 `logs/editor_audit.jsonl`，可用 `SRA_EDITOR_AUDIT_LOG` 覆寫。
- 帳號具備 `pending` / `active` / `rejected` 狀態。
- 新使用者可自行建立帳號；新帳號預設為 `pending`，需由超級使用者核准為 `user` 或 `superuser` 後才可登入。
- `superuser` 可在同一介面中審核、拒絕新帳號。


### 表單欄位設定檔

編輯器表單不是寫死在前端；預設會讀取 `config/editor_form.default.json`。此檔即為目前 SRA 結構化文件的套用範例，定義：

- `schemas.<schema_name>.sections`：表單區塊、使用者看見的欄位名稱、欄位說明、輸入型態。
- `compact_hide: true`：可標記欄位在「簡要顯示模式」下隱藏，便於大量欄位時的美觀編排。
- `fields[].path`：實際要寫回 Elasticsearch `_source` 的 doc 欄位路徑，例如 `multidim_event_json.Event.subject`。
- `type: "array"` 的 section：可編輯陣列型資料，例如 `multidim_event_json.evidence_snippets`。
- `search_fields` / `search_source_fields`：該 schema 搜尋時使用的 ES 欄位與列表摘要欄位。
- `index_schema_map`：可依不同 index 名稱或 wildcard pattern 指定不同 schema；未指定時使用 `default_schema`。

如未特別設定，系統會使用 `config/editor_form.default.json`。目前預設已納入 `Event.consequence`、`Event_Timeline`、`Involved_Parties`、`Event_Summary`、`Event.time_precision`、`article_date_precision`、`Impact`、`Event.subject`、`Event.object`、`Event.time_raw`、`Event.action`、`Event.source`、`Event.aspect`、`article_title`、`article_date_iso`、`Event.medium`、`core_entities`、`Person`、`facet`、`rawInfo.content` 等欄位。

此外 UI 新增「簡要顯示模式」開關，會隱藏標記 `compact_hide: true` 的欄位與說明文字，讓大量欄位時更易讀。

若其他應用需要不同資料庫結構，可另外建立 JSON 設定檔，並在專案根目錄的 `.env`、`.env.{APP_ENV}` 或 `.env.local` 設定：

```env
# 例如：/workspace/poc-agent/.env.local
SRA_EDITOR_FORM_CONFIG=/secure/path/editor_form.my_app.json
```

登入稽核已和帳號資料分檔；若未設定 `SRA_LOGIN_AUDIT_FILE`，預設會放在 `SRA_AUTH_USERS_FILE` 同目錄、同檔名前綴的 `.login_audit.json` manifest。實際登入事件會再依月份寫入旁邊的 shard 目錄（例如 `.sra_users.login_audit.json.d/login_audit-202606.json`），避免單一 audit JSON 日積月累肥大。帳號檔與每個 audit shard 每次寫入前都會更新最新 `.bak`；另在每天第一次改寫該檔案時保留 1 份 `.bak.<YYYYMMDD>` 歷史備份，預設保留 20 天版本；讀取遇到 JSON 損壞時會從最新備份一路嘗試到歷史備份還原；還原成功、備份不可用或無法還原時會輸出 warning/error log，並在同目錄寫入 `<file>.recovery.jsonl` 供管理者追蹤。

#### Auth 檔案路徑設定與產物說明

- `SRA_AUTH_USERS_FILE` 指定帳號管理主檔，內容包含 users、token denylist、password reset token 等登入必要狀態；建議正式部署放在 repo 外的持久化目錄，例如 `/var/lib/sra-auth/sra_users.json`。
- `SRA_LOGIN_AUDIT_FILE` 指定登入稽核 manifest；若未設定，會依 `SRA_AUTH_USERS_FILE` 派生，例如 `/var/lib/sra-auth/sra_users.login_audit.json`。manifest 不保存大量事件，只描述 sharded storage。
- 實際登入稽核事件會寫入 `<SRA_LOGIN_AUDIT_FILE>.d/login_audit-YYYYMM.json`，例如 `/var/lib/sra-auth/sra_login_audit.json.d/login_audit-202606.json`。
- 建議將 `SRA_AUTH_USERS_FILE` 與 `SRA_LOGIN_AUDIT_FILE` 指到同一個受備份 / 監控的 runtime 目錄，但不要指到同一個檔案。
- 備份與還原產物包含：`<file>.bak`、`<file>.bak.<YYYYMMDD>` 與 `<file>.recovery.jsonl`；管理者可監控 application log 中的 `auth_json_*` 訊息與 recovery JSONL。

設定範例：

```env
SRA_AUTH_USERS_FILE=/var/lib/sra-auth/sra_users.json
SRA_LOGIN_AUDIT_FILE=/var/lib/sra-auth/sra_login_audit.json
```

此專案的 env 載入順序是 OS 環境變數優先，其次 `.env.local`、`.env.{APP_ENV}`、`.env`；因此正式部署可用系統環境變數覆蓋 `.env` 內的值。

最小 schema 範例：

```json
{
  "version": 1,
  "default_schema": "my_app",
  "index_schema_map": {
    "my-index-*": "my_app"
  },
  "schemas": {
    "my_app": {
      "label": "我的應用資料",
      "sections": [
        {
          "title": "基本欄位",
          "fields": [
            {"path": "title", "label": "標題", "type": "text", "help": "寫入 _source.title"},
            {"path": "summary", "label": "摘要", "type": "textarea"}
          ]
        }
      ]
    }
  }
}
```

### Audit log 儲存位置

目前修改 audit **不會寫在 Elasticsearch 原本同一筆 doc 裡**，也不會修改 `_source` 增加 audit 欄位；這樣可避免稽核資料污染原始情資文件，並避免使用者編輯文件時順手覆蓋或刪除稽核紀錄。

每次成功儲存且內容真的有變更時，後端會把一筆 JSONL 紀錄 append 到獨立檔案：

- 預設路徑：`logs/editor_audit.jsonl`
- 可用 `.env` / `.env.local` 設定覆寫：`SRA_EDITOR_AUDIT_LOG=/secure/path/editor_audit.jsonl`

每筆 audit 會記錄 `ts`、`username`、`role`、`index`、`id`、ES 寫入結果、`changed_paths` 與每個欄位的 before/after 摘要。因此雖然 audit 不放在 ES 同 doc 下面，仍可透過 `index + id` 對回被修改的 Elasticsearch 文件。

### 初始超級使用者設定

建議將初始超級使用者帳密放在固定位置 `config/auth/bootstrap_superusers.json`（此檔已被 `.gitignore` 排除，避免誤提交真實密碼）。可複製 `config/auth/bootstrap_superusers.example.json` 後修改：

```json
{
  "superusers": [
    {
      "username": "admin",
      "password": "change-this-password"
    }
  ]
}
```

如需改用其他路徑，可設定：

```env
SRA_BOOTSTRAP_SUPERUSERS_FILE=/secure/path/bootstrap_superusers.json
```

也可使用單一帳號環境變數：

```env
SRA_BOOTSTRAP_SUPERUSER_USERNAME=admin
SRA_BOOTSTRAP_SUPERUSER_PASSWORD=change-this-password
```

也可使用 JSON 設定多組初始超級使用者：

```env
SRA_BOOTSTRAP_SUPERUSERS=[{"username":"admin","password":"change-this-password"},{"username":"reviewer","password":"change-this-too"}]
```

建議正式部署時另行設定 token 簽章密鑰與帳號資料檔位置：

```env
SRA_AUTH_SECRET=replace-with-a-long-random-secret
SRA_AUTH_USERS_FILE=/secure/path/sra_users.json
SRA_LOGIN_AUDIT_FILE=/secure/path/sra_login_audit.json
SRA_EDITOR_AUDIT_LOG=/secure/path/editor_audit.jsonl
SRA_EDITOR_FORM_CONFIG=/secure/path/editor_form.my_app.json
```

登入稽核已和帳號資料分檔；若未設定 `SRA_LOGIN_AUDIT_FILE`，預設會放在 `SRA_AUTH_USERS_FILE` 同目錄、同檔名前綴的 `.login_audit.json` manifest。實際登入事件會再依月份寫入旁邊的 shard 目錄（例如 `.sra_users.login_audit.json.d/login_audit-202606.json`），避免單一 audit JSON 日積月累肥大。帳號檔與每個 audit shard 每次寫入前都會更新最新 `.bak`；另在每天第一次改寫該檔案時保留 1 份 `.bak.<YYYYMMDD>` 歷史備份，預設保留 20 天版本；讀取遇到 JSON 損壞時會從最新備份一路嘗試到歷史備份還原；還原成功、備份不可用或無法還原時會輸出 warning/error log，並在同目錄寫入 `<file>.recovery.jsonl` 供管理者追蹤。
