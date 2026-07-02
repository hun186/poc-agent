# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；API 在 `sra_api/`（另有相容 shim），agent / retrieval / evidence 在 `agent/`，資料匯入與 ETL 在 `data_ingestion/`，設定在 `config/`，測試在 `tests/`。
- Editor / SQL 來源資料編輯器共用 `sra_editor_token`；主要來源是 localStorage，SQL 來源資料編輯器另允許同分頁 sessionStorage 作為導航承接 fallback。不得把 bearer token 放進 URL query 或 hash。若修改前端靜態 JS，需同步更新 HTML script query version 以避免瀏覽器沿用舊資產。
- Excel→SQL 使用者匯入採上傳保存、預掃描、確認匯入 SQL 三階段；SQL 來源資料編輯器只允許操作已啟用 dashboard 任務的 `destination.table`，禁止任意 SQL / 任意 table name。
- Auth 採四層 role：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 正規化為 `data_editor`。新註冊帳號預設 `data_reader` + `pending`。
- Vercel / mock runtime 只用於檢閱或唯讀環境，正式 ES / SQL 可用時仍應優先使用真實服務；mock response 必須透過 `mock_mode` 與 warnings 明確揭露。
- 目前環境缺少 Playwright / browser runtime；可視 UI 變更若無法截圖，以靜態 UI 測試、JS 語法檢查與 pytest 替代，並於 known issues 記錄。

## Recent Changes

### 2026-07-02 SQL 來源資料編輯器登入修正安全調整

- 目的：回應 URL hash token handoff 的資安疑慮。
- 主要修改：移除 `#sra_token` bearer token handoff，不再把 token 放入 URL；改以既有同源 localStorage session 承接登入狀態，並新增同分頁 sessionStorage 導航承接 fallback：Editor 點 SQL 來源資料編輯器前把現有 token 寫入 sessionStorage，目標頁讀 localStorage 或 sessionStorage。同步更新 Editor bootstrap 與 SQL 來源資料編輯器 JS cache-busting 版本，避免部署後載入舊資產造成誤判未登入。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（pip upgrade 查詢套件索引遇 403 retry，但 requirements 已滿足）、`node --check sra_api/static/editor_bootstrap.js`、`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q`。

### 2026-07-02 SQL 來源資料編輯器登入承接修正（已被安全調整改寫）

- 曾短暫加入 URL hash token handoff；後續判定有 token 暴露風險，已於同日移除。保留結論：前端登入承接應避免 URL 帶 token，必要時優先以同源 storage / server-side cookie 設計處理。

### 2026-07-01 SQL 來源資料編輯器使用者篩選補強

- 來源編輯器頁面載入 `/static/audit_tools.js`，使用既有 `SraAuditTools` 多選 helper 呈現使用者篩選；後端 `source-rows` 支援 `username_filter` 並回傳 `username_options`。

### 2026-07-01 SQL 來源資料編輯器與 dashboard 拆檔

- `data_ingestion/excel_to_sql/dashboard.py` 維持 facade；task discovery / 批次刪除報表組裝拆出小模組。SQL 來源資料編輯器採受控 table 白名單、必填 reason、禁止修改 hash / 系統欄位並寫入 SQL audit。

### 2026-06-26 Excel→SQL 任務設定檔自助管理

- 任務 JSON 建立流程從 Excel 匯入作業中心拆成獨立頁；db_operator 只能管理自己建立的 pending 設定檔，superuser 維持審核啟用權限。

### 2026-06-25 Editor / multidim_event_json 穩定性修正

- Editor array 新增改以表單 schema 作為 array item shape 來源；`multidim_event_json` 相關讀取路徑支援 dict、list[dict] 與 JSON 字串；新增概要與 multi-event TODO 文件。

### 2026-06-23 Vercel mock preview login hardening

- Mock preview login 在 production-like 環境預設停用，只有明確 force 才可啟用；preview secret 只由環境變數提供，不寫入 repo；mock preview token 以 claim 標記並限制 mock-only ES 讀取邊界。

## Archived History

- `.codex/archive/memory.md-20260612-032146.md`：歸檔 2026-06-12 03:21 UTC 前完整 memory 歷史。
- `.codex/archive/memory.md-20260616-042648.md`：歸檔 2026-06-12 至 2026-06-16 的 active memory。
- `.codex/archive/memory.md-20260623-064506.md`：歸檔 2026-06-16 至 2026-06-23 的 active memory。
- `.codex/archive/memory.md-20260702-021320.md`：歸檔 2026-06-23 至本次濃縮前的 active memory；本次濃縮保留仍有效摘要、近期工作與 URL token handoff 安全修正結論。
