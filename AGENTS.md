# Agent 工作指南

此檔提供 Codex / agent 修改本 repo 時的優先參考資訊。目標是減少不必要的全專案探索、降低 token 用量，並讓修改更快聚焦。

## 專案上下文載入（Project Context Loading）

在開始任何任務前，必須依序閱讀：

1. AGENTS.md
2. .codex/memory.md
3. .codex/known_issues.md
4. .codex/decisions.md
5. .codex/backlog.md

若上述檔案或目錄不存在：

1. 建立 `.codex/` 目錄
2. 建立缺少的檔案
3. 以適當標題初始化內容

上述檔案視為本專案的長期記憶（Persistent Project Memory）。

若文件內容與目前程式碼不一致：

* 以程式碼為準
* 更新相關記錄文件

---

## 專案記憶維護（Memory Maintenance）

每次完成任務後，必須同步更新專案記憶：

1. 更新 `.codex/memory.md`
2. 若發現新的環境限制、錯誤或已知問題，更新 `.codex/known_issues.md`
3. 若產生新的設計決策或架構決策，更新 `.codex/decisions.md`
4. 若發現後續待辦事項或改善建議，更新 `.codex/backlog.md`
5. 保留歷史紀錄，僅追加內容，不覆蓋既有紀錄

所有內容以中文為主要語言。
日期格式統一使用 YYYY-MM-DD。

不得略過記憶更新步驟。

專案記憶更新屬於任務的一部分。

在完成專案記憶更新前，不得視為任務已完成。

---

## 記錄原則

### memory.md

記錄：

* 任務目的
* 主要修改內容
* 驗證結果
* 重要結論

避免記錄：

* 大量重複日誌
* 無意義執行細節

---

### known_issues.md

記錄：

* 已知錯誤
* 環境限制
* 外部服務限制
* Sandbox 限制
* Playwright、Docker、資料庫等問題

---

### decisions.md

記錄：

* 架構決策
* 技術選型原因
* 不採用方案及理由
* 長期維護考量

---

### backlog.md

記錄：

* 尚未完成事項
* 後續優化建議
* 技術債
* 預計改善項目

---

禁止將以下資訊寫入任何記憶檔案：

* API Key
* Access Token
* Password
* Cookie
* 憑證內容
* 個人敏感資料
* 機密資訊

## 專案概覽

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統。
- API 與 HTTP endpoint 主要在 `api/`。
- Agent、retrieval、evidence 主要在 `agent/`；資料匯入與 ETL 主要在 `data_ingestion/`。
- 設定檔主要在 `config/`。
- 測試主要在 `tests/`。

## 優先工作路徑

| 任務類型 | 優先查看 |
| --- | --- |
| Chat completion / 對話 API | `api/routers/chat.py`, `api/services/sessions.py`, `agent/` |
| FastAPI app 啟動、middleware、路由掛載 | `api/main.py`, `api/routers/` |
| Elasticsearch 查詢、證據整理 | `agent/es/`, `agent/data_agent/` |
| SQL Server 匯入 Elasticsearch | `data_ingestion/sql_to_es/ingest_sql.py`, `config/sql_import/` |
| Excel 匯入 SQL Server | `data_ingestion/excel_to_sql/`, `config/excel_to_sql/` |
| Excel 匯入監控 dashboard | `data_ingestion/excel_to_sql/dashboard.py`, `api/routers/excel_to_sql.py`, `api/static/excel_to_sql_dashboard.html` |
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
