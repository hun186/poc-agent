# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；API 在 `sra_api/`（另有相容 shim），agent / retrieval / evidence 在 `agent/`，資料匯入與 ETL 在 `data_ingestion/`，設定在 `config/`，測試在 `tests/`。
- Editor 表單由 `config/editor_form.default.json` 驅動，前端在 `sra_api/static/editor_form.js` 依 schema sections 渲染一般欄位與 array 欄位；array 新增不應依賴載入文件本身已有第一筆範例。
- Vercel / mock runtime 只用於檢閱或唯讀環境，正式 ES / SQL 可用時仍應優先使用真實服務；mock response 必須透過 `mock_mode` 與 warnings 明確揭露。
- Excel→SQL 使用者匯入採上傳保存、預掃描、確認匯入 SQL 三階段；mock SQL dashboard 覆蓋 audit 查詢與 no-op delete，避免在 Vercel preview 假裝寫入正式 SQL Server。
- Auth 採四層 role：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 正規化為 `data_editor`。新註冊帳號預設 `data_reader` + `pending`。
- JSON auth store 採 atomic replace、最新 `.bak`、每日歷史備份與 recovery JSONL；login audit 使用 manifest + 月份 shard，不再寫入 users JSON。
- 目前環境缺少 Playwright / browser runtime；可視 UI 變更若無法截圖，以靜態 UI 測試、JS 語法檢查與 pytest 替代，並於 known issues 記錄。

## Recent Changes

### 2026-06-23 Editor array 新增與 mock 資料補強

- 目的：修正 Editor 文件本身缺少 evidence / Timeline / Party / Person 陣列時，按「新增...」只顯示成功訊息但沒有新輸入格的問題，並提升 ES / Excel→SQL mock demo 資料完整度。
- 主要修改：array section render 改由 schema path 初始化 array 容器；新增 array item 時依欄位型別給預設值；表單設定補上 reference doc 常見欄位如 date_raw、date_precision、party_role、Person quote/action/stance/relation 與 evidence confidence。
- Mock ES：改成包含印尼災害援助事件的 multidim_event_json、Timeline、Involved_Parties、Person、evidence_snippets、entities 與較完整 mapping；另保留一筆刻意缺少 array 欄位的文件，用於驗證可從空白結構新增第一筆。
- Mock Excel→SQL：audit rows 改為對應印尼災害援助事件的事件、人物與證據 payload，保留 inserted / duplicate 狀態與 mock no-write 語意。
- 驗證：`python -m py_compile agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py` 通過；`node --check sra_api/static/editor_form.js` 通過；`PYTHONPATH=. pytest tests/test_vercel_mock_runtime.py tests/test_editor_form_static.py -q` 通過（5 passed）。

### 2026-06-23 Memory compaction

- 因 active memory 累積多個工作紀錄區塊，已將濃縮前全文歸檔至 `.codex/archive/memory.md-20260623-064506.md`，並重寫 active memory 為目前仍有效摘要與近期重點。
- 驗證：`wc -l .codex/memory.md` 確認濃縮後低於 200 行。

### 2026-06-23 Vercel mock preview login hardening

- Mock preview login 在 production-like 環境預設停用，只有明確 force 才可啟用；preview login secret 只由環境變數提供，不寫入 repo。
- Mock preview token 使用 mock_preview claim，ES 讀取 endpoint 對 mock preview token 採 mock-only 資料邊界。

### 2026-06-22 Vercel mock runtime / config

- Mock runtime 可在 Vercel / 唯讀 / 強制 mock 情境提供 ES 與 Excel→SQL demo；若正式 ES ping 成功則優先使用真實 ES。
- 現行 Vercel 策略為 root `app.py` + zero-config FastAPI discovery + `.vercelignore` 控制 bundle footprint。

### 2026-06-16 Auth JSON Store / Login Audit

- Auth JSON IO、備份還原與 login audit sharding 已拆成專責模組；login audit manifest path 由 `SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE` 指定，事件寫入月份 shard。
- JSON store 每次寫入更新最新 `.bak`，每天第一次改寫建立 dated historical backup，預設保留 20 天版本。

## Archived History

- `.codex/archive/memory.md-20260612-032146.md`：歸檔 2026-06-12 03:21 UTC 前完整 memory 歷史。
- `.codex/archive/memory.md-20260616-042648.md`：歸檔 2026-06-12 至 2026-06-16 的 active memory。
- `.codex/archive/memory.md-20260623-064506.md`：歸檔 2026-06-16 至本次濃縮前的 active memory，包含 Auth、Excel、Vercel mock、Editor 與部署決策相關工作紀錄。

### 2026-06-23 ES mock demo documents expansion

- 目的：依使用者補充的兩筆 Kibana 參考文件，讓 Vercel/mock ES demo 清單更美觀且更接近實際新聞與 SQL import 文件混合情境。
- 主要修改：新增聯大/埃博拉/氣候峰會事件 mock doc 與福隆88號漁獲 SQL import mock doc；保留敏感資訊排除原則，未寫入參考資料中的 API key、內網 server IP 或本機檔案路徑。
- 驗證：`python -m py_compile agent/es/mock_es_client.py data_ingestion/excel_to_sql/mock_sql.py` 通過；`node --check sra_api/static/editor_form.js` 通過；`PYTHONPATH=. pytest tests/test_vercel_mock_runtime.py tests/test_editor_form_static.py -q` 通過（5 passed）。

### 2026-06-23 Editor form asset cache bust for schema-based array add

- 目的：回應文件編修頁在原文件缺少 evidence / Timeline / Party / Person 陣列時，新增按鈕看似成功但使用者可能仍載入舊版 `editor_form.js` 而看不到新格子的問題。
- 主要修改：Editor HTML 將 `editor_form.js` query version 更新為 `20260623-array-schema`，強制瀏覽器重新抓取已改為依表單 schema 建立 array item 的前端程式；並新增靜態回歸測試確認新增 array item 由 schema fields 決定，不依賴既有文件樣本列。
- 驗證：`node --check sra_api/static/editor_form.js` 通過；`PYTHONPATH=. pytest tests/test_editor_form_static.py tests/test_editor_auth_ui_static.py -q` 通過（25 passed, 3 warnings；warnings 為既有 Starlette / Python invalid escape deprecation 訊息）。

### 2026-06-25 肥大程式檔拆分重構

- 目的：檢查主要程式 / 靜態 / 測試檔案是否有單檔過於肥大的情況，並優先以不改 API contract 的方式拆分責任。
- 主要修改：`sra_api/routers/chat.py` 保留 FastAPI route orchestration，將 Chat payload、session/history、meta task、citation、session/memory 保存等 helper 拆到 `sra_api/routers/chat_support.py`；`agent/data_agent/prompts.py` 改為相容 facade，將風格與報告 prompt 分別拆到 `style_prompts.py` / `report_prompts.py`；移除 `tests/test_editor_auth_ui_static.py` 中重複的常數與重複測試。
- 驗證：`python -m py_compile sra_api/routers/chat.py sra_api/routers/chat_support.py agent/data_agent/prompts.py agent/data_agent/style_prompts.py agent/data_agent/report_prompts.py tests/test_editor_auth_ui_static.py` 通過；掃描 `api/ sra_api/ agent/ data_ingestion/ config/ tests/ portable_auth_pack/` 的 `.py/.js/.html/.css` 後已無單檔 >= 500 行（排除 swagger / 複製檔）；`PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py tests/test_vercel_mock_runtime.py -q` 通過（24 passed, 3 warnings；warnings 為既有 Starlette / invalid escape deprecation）。

### 2026-06-25 DOC_FOLLOWUP 單篇全文錯誤修正

- 目的：修正多輪對話中使用者要求「給我第二篇的全文」並進入 `DOC_FOLLOWUP` 時，`ESFetchDocById` 在處理 ES get/search response shape 差異時可能拋出 `'list' object has no attribute 'get'` 或漏判 mock get 成功的問題。
- 主要修改：`agent/tools_es/fetch_doc.py` 將 ES get response 正規化為 dict，允許沒有 `found` flag 但含 `_source` 的成功回應；fallback search 改用既有 `safe_search` body 介面並防禦非 dict hits shape。
- 驗證：`python -m py_compile agent/tools_es/fetch_doc.py tests/test_es_fetch_doc_by_id.py` 通過；`PYTHONPATH=. pytest tests/test_es_fetch_doc_by_id.py -q` 通過（2 passed）。
