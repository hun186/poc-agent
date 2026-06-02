# 專案架構速查

此文件是給人與 agent 快速定位用的短版架構圖。詳細操作細節請優先看各模組 README 與 `AGENTS.md`。

## 高層資料流

```text
User / Client
  -> FastAPI app (`api/main.py`)
  -> API routers (`api/routers/`)
  -> services / session / state (`api/services/`)
  -> agent routing / retrieval / generation (`agent/`)
  -> Elasticsearch or SQL Server
  -> presenters / static UI / API response
```

## 主要模組

| 區域 | 路徑 | 責任 |
| --- | --- | --- |
| API app | `api/main.py`, `api/run_api.py` | 建立 FastAPI app、掛載 router、啟動服務 |
| API routers | `api/routers/` | HTTP endpoint 與 request/response 轉換 |
| API services | `api/services/` | session、auth、editor config、audit、export 等服務邏輯 |
| Presenters | `api/core/presenters/` | Markdown、DOCX、section、citation 等輸出格式整理 |
| Core agents | `agent/` | 任務路由、報告生成、風格改寫、文件追問與工具協調 |
| Data agent | `agent/data_agent/` | Elasticsearch retrieval runtime、prompt 與資料型別 |
| ES utilities | `agent/es/` | ES client、query body、evidence parsing、SQL/TXT ingestion |
| Excel import | `agent/excel_to_sql/` | Excel 讀取、欄位比對、SQL 寫入、audit、dashboard 資料彙整 |
| Config | `config/` | index、auth、editor、SQL import、Excel import 設定 |
| Tests | `tests/` | 單元測試與 dashboard static 檢查 |

## 常見修改入口

### Chat / RAG 回答

1. 先看 `api/routers/chat.py` 確認 HTTP endpoint 與 request flow。
2. 再依任務追到 `agent/`、`agent/data_agent/` 或 `agent/es/`。
3. 若涉及 session，查看 `api/services/sessions.py`。

### Elasticsearch retrieval / evidence

1. 查 query construction：`agent/es/query_body.py`。
2. 查 ES client：`agent/es/es_client.py`。
3. 查 evidence parsing / snippet / topic matching：`agent/es/evidence_core/`。
4. 查 data-agent runtime：`agent/data_agent/runtime.py`。

### Excel 匯入 SQL 與監控

1. 匯入流程入口：`agent/excel_to_sql/ingest.py`。
2. 共用工具：`agent/excel_to_sql/utils.py`, `date_utils.py`, `sql_utils.py`, `audit.py`。
3. dashboard 資料彙整：`agent/excel_to_sql/dashboard.py`。
4. dashboard API：`api/routers/excel_to_sql.py`。
5. dashboard UI：`api/static/excel_to_sql_dashboard.html`。

### DOCX / 匯出

1. 匯出服務：`api/services/export_word_service.py`。
2. DOCX presenter：`api/core/presenters/docx/`。
3. Markdown / section / citation 轉換：`api/core/presenters/`。

## 不建議優先參考的內容

- `data/`：大量資料檔，除非任務指定資料處理或樣本內容。
- `api/static/swagger-*`：第三方 Swagger UI 靜態檔。
- 檔名含 `複製` 的 Python 檔：通常是歷史備份，避免與正式檔混淆。
