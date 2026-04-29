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

本專案提供 `agent/es/ingest_sql.py`，可依 JSON 設定檔，從遠端 SQL Server 讀取資料後 bulk 寫入 Elasticsearch。

### 1) 執行指令

在專案根目錄執行：

```bash
python -m agent.es.ingest_sql --config config/sql_import/srp_import.json
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
- `db.driver`：ODBC driver 名稱（常見為 `ODBC Driver 17 for SQL Server`）。
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


## 環境變數（.env）與 Index 多環境設定

### .env 載入優先順序
專案使用 `config/bootstrap.py` 的 `bootstrap_env()` 載入環境變數，優先順序如下（高 → 低）：

1. OS 環境變數（系統已注入）
2. `.env.local`
3. `.env.{APP_ENV}`（例如 `.env.dev`、`.env.local`、`.env.prod`）
4. `.env`

> `APP_ENV` 若未設定，預設為 `dev`。

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
