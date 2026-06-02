# Agent 工作指南

此檔提供 Codex / agent 修改本 repo 時的優先參考資訊。目標是減少不必要的全專案探索、降低 token 用量，並讓修改更快聚焦。

## 專案概覽

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統。
- API 與 HTTP endpoint 主要在 `api/`。
- Agent、retrieval、evidence、SQL/ES ingestion 主要在 `agent/`。
- 設定檔主要在 `config/`。
- 測試主要在 `tests/`。

## 優先工作路徑

| 任務類型 | 優先查看 |
| --- | --- |
| Chat completion / 對話 API | `api/routers/chat.py`, `api/services/sessions.py`, `agent/` |
| FastAPI app 啟動、middleware、路由掛載 | `api/main.py`, `api/routers/` |
| Elasticsearch 查詢、證據整理 | `agent/es/`, `agent/data_agent/` |
| SQL Server 匯入 Elasticsearch | `agent/es/ingest_sql.py`, `config/sql_import/` |
| Excel 匯入 SQL Server | `agent/excel_to_sql/`, `config/excel_to_sql/` |
| Excel 匯入監控 dashboard | `agent/excel_to_sql/dashboard.py`, `api/routers/excel_to_sql.py`, `api/static/excel_to_sql_dashboard.html` |
| Word / DOCX 匯出 | `api/services/export_word_service.py`, `api/core/presenters/docx/` |
| Editor 表單與稽核 | `api/routers/editor.py`, `api/services/editor_form_config.py`, `api/services/editor_audit.py`, `config/editor_form.default.json` |

## 降低 token 用量的搜尋原則

- 除非任務明確要求，避免掃描或讀取 `data/`；此目錄包含大量資料檔。
- 除非任務明確要求，避免修改 vendored Swagger UI 靜態檔：`api/static/swagger-*`、`api/static/oauth2-redirect.html`。
- 檔名含 `複製` 的檔案通常是舊備份或重構前版本；除非任務明確要求，不要作為主要修改目標。
- 優先用 `rg` / `rg --files` 限定目錄搜尋，例如：`rg "pattern" api agent tests`。
- 不要使用 `ls -R` 或 `grep -R`。

## 常用測試指令

```bash
pytest tests
```

Excel 匯入與 dashboard 相關：

```bash
pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_audit.py tests/test_sql_utils.py
```

## 修改規範

- 優先做小範圍修改，避免跨多個不相關模組重構。
- API response shape 或前端 dashboard 行為改變時，請同步補測試或更新既有測試。
- 不要把密碼、token、私有連線資訊寫死到程式碼或文件。
- Python import 不要包在 try/except 裡。
- 修改靜態 web UI 且可執行時，若環境允許請截圖驗證。
