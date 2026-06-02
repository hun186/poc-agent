# API 模組速查

`api/` 負責 FastAPI app、HTTP routers、service layer、靜態頁面與輸出 presenter。

## 主要入口

| 路徑 | 用途 |
| --- | --- |
| `main.py` | 建立 FastAPI app、middleware、router 掛載 |
| `run_api.py` | API 啟動輔助 |
| `routers/` | 各功能 HTTP endpoint |
| `services/` | session、auth、editor、export、audit 等 service logic |
| `core/presenters/` | Markdown、DOCX、citation、section 等輸出整理 |
| `static/` | 靜態頁面與 Swagger UI assets |

## Router 對照

| Router | 常見任務 |
| --- | --- |
| `routers/chat.py` | Chat completion、session context、對話 request/response |
| `routers/excel_to_sql.py` | Excel 匯入監控頁面與 JSON API |
| `routers/editor.py` | Editor 表單、設定與稽核 API |
| `routers/export.py` | 匯出 API |
| `routers/docs.py` | 文件或說明相關 endpoint |

## 注意事項

- 修改 API response shape 時，請同步檢查前端 static page 與 tests。
- `static/swagger-*` 多為 vendored Swagger UI 檔案，除非任務明確要求不要修改。
- 檔名含 `複製` 的檔案通常是備份，不要作為主要修改目標。
