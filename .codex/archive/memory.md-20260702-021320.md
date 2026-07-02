# Project Memory

## Current Summary

- 本專案是 FastAPI + Elasticsearch 的 RAG / agent 系統；API 在 `sra_api/`（另有相容 shim），agent / retrieval / evidence 在 `agent/`，資料匯入與 ETL 在 `data_ingestion/`，設定在 `config/`，測試在 `tests/`。
- Editor 表單由 `config/editor_form.default.json` 選擇 UI 顯示欄位，並在載入特定 index 時用 Elasticsearch live mapping metadata 補上欄位型別與 mapping_path；前端在 `sra_api/static/editor_form.js` 依 schema sections 渲染一般欄位與 array 欄位；array 新增不應依賴載入文件本身已有第一筆範例。
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

### 2026-06-25 DOC_FOLLOWUP multidim_event_json list 修正

- 目的：修正多輪對話中使用者要求「給我第二篇的全文」並進入 DOC_FOLLOWUP 時，文件來源的 `multidim_event_json` 為 `list[dict]` 造成 `list` 沒有 `.get()` 而後端例外。
- 主要修改：`agent/doc_followup/fetcher.py` 改用既有 `as_blocks()` 正規化 `multidim_event_json`，支援 dict、list[dict] 與 JSON 字串後再抽取 Event / Event_Timeline / article_title。
- 驗證：`python -m py_compile agent/doc_followup/fetcher.py tests/test_doc_followup_fetcher.py` 通過；`PYTHONPATH=. pytest tests/test_doc_followup_fetcher.py -q` 通過（1 passed）。執行 `python -m pip install --upgrade pip` 時套件索引回覆 403 retry，但目前環境已有所需套件，`python -m pip install -r requirements.txt` 顯示 requirements 已滿足。

### 2026-06-25 multidim_event_json 型別適應性擴大檢查

- 目的：回應 DOC_FOLLOWUP 修正後的追問，檢查專案其他使用 `multidim_event_json` 的流程是否仍假設固定 dict 形狀。
- 主要修改：修正全文下載 API、evidence parser inner_hits fallback、Editor mapping shape normalizer 與 Editor 清單標題顯示，讓 `multidim_event_json` 可安全處理 dict、list[dict] 與 JSON 字串；並補上跨模組回歸測試。
- 驗證：`python -m py_compile agent/doc_followup/fetcher.py agent/es/evidence_core/parser.py sra_api/routers/docs.py sra_api/services/editor_index_utils.py tests/test_doc_followup_fetcher.py tests/test_multidim_shape_normalization.py` 通過；`PYTHONPATH=. pytest tests/test_doc_followup_fetcher.py tests/test_multidim_shape_normalization.py -q` 通過（5 passed）；`node --check sra_api/static/editor_core.js` 通過。

### 2026-06-25 multidim_event_json 概要文件

- 目的：依使用者說明，為第一年開發階段的 LLM 文章萃取成果建立查閱用概要，說明 `multidim_event_json` 架構、欄位語意與已完成 / 預期支援的應用目標。
- 主要修改：新增 `docs/multidim_event_json_overview.md`，摘要 `docs/taskSetting_Enrichment.py` 的輸出結構、事件聚合原則、證據優先原則、日期時間設計、ES / RAG / Editor / 多維分析應用與後續擴充注意事項。
- 驗證：`python - <<'PY' ... PY` 檢查文件存在必要標題與 `evidence_snippets` 關鍵內容，並輸出文件行數與字元數。

### 2026-06-25 multidim_event_json 多頂層事件 TODO 文件

- 目的：回應多維度事件應用情境中，長文切片合併可能把不同事件合成單一大字典，以及 agent / Editor 仍偏向單一事件物件的長期風險。
- 主要修改：新增 `docs/multidim_event_json_multi_event_todo.md`，記錄未來 event-cluster merge、multi-event agent selector、Editor 事件列表 UI 與 event-level index 的分階段建議；本次僅文件化待辦，不調整通用 LLM 抽取框架與 merge slice 程式。
- 驗證：`python - <<'PY' ... PY` 檢查 TODO 文件存在必要標題與關鍵內容；`git diff --check` 通過。

### 2026-06-25 Editor array add rendering guard

- 目的：回應 Editor 文件編修頁在文件原本沒有 evidence / Timeline / Party / Person 陣列時，按新增按鈕只看到成功訊息但未看到新輸入格的回報。
- 主要修改：`sra_api/static/editor_form.js` 的新增陣列項目流程明確以表單設定 schema section fields 建立新 item，不依賴已載入文件中既有樣本列；新增後會檢查 DOM 是否實際渲染對應 array item，若未渲染改顯示錯誤，避免只有成功訊息。`editor.html` 同步更新 `editor_form.js` cache-busting 版本，避免瀏覽器沿用舊版前端資產。
- 驗證：`node --check sra_api/static/editor_form.js` 通過；`PYTHONPATH=. pytest tests/test_editor_form_static.py tests/test_editor_auth_ui_static.py -q` 通過（25 passed, 1 warning；warning 為既有 Starlette/httpx deprecation）。執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 時 pip index 曾回覆 403 retry，但目前環境 requirements 已滿足。


### 2026-06-25 Editor form config 與 ES mapping 連動

- 目的：回應 Editor 是 ES 資料庫編修介面，欄位型別與資料結構應自然連動 Elasticsearch mapping；`config/editor_form.default.json` 應偏向 UI 顯示哪些欄位，而不是唯一資料型別來源。
- 主要修改：`public_editor_form_config()` 在有 index 時讀取 ES live mapping metadata，將 mapping type / mapping_path 合併到 schema sections 與 fields；對 date / number / boolean / text 類 mapping 會推導 UI input type，讓新增空白陣列項目與表單欄位格式跟 ES mapping 保持一致。
- 驗證：`python -m py_compile sra_api/services/editor_form_config.py sra_api/services/editor_index_utils.py tests/test_editor_form_config_mapping.py` 通過；`PYTHONPATH=. pytest tests/test_editor_form_config_mapping.py tests/test_editor_form_static.py tests/test_editor_auth_ui_static.py tests/test_multidim_shape_normalization.py -q` 通過（31 passed, 1 warning；warning 為既有 Starlette/httpx deprecation）。

### 2026-06-25 Editor single-item array normalize 修正

- 目的：修正部署後新增第一筆 Involved_Parties / evidence / Timeline / Person 時，狀態列顯示 `已更新資料但未成功渲染新增格子` 的問題。
- 根本原因：`normalizeLeaf()` 會把所有單元素 array 壓平成單一 object；新增第一筆 array item 後，`populateForm()` 重新 normalize 時把 `[item]` 壓成 `item`，後續 array path normalizer 又把非 array 重設成 `[]`，導致 render guard 發現資料有新增但 DOM 沒格子。已有 item 的文件按新增後 array 長度通常變成 2，因此不會觸發單元素壓平。
- 主要修改：`normalizeLeaf()` 改為 path-aware，對 schema array paths / normalizers.array_paths / csv paths 保留 array 形狀，即使只有一個 item 也不壓平；同步更新 `editor_form.js` cache-busting 版本，避免瀏覽器沿用舊 normalize 邏輯。
- 驗證：`node --check sra_api/static/editor_form.js` 通過；`PYTHONPATH=. pytest tests/test_editor_form_static.py tests/test_editor_auth_ui_static.py tests/test_editor_form_config_mapping.py tests/test_multidim_shape_normalization.py -q` 通過（32 passed, 1 warning；warning 為既有 Starlette/httpx deprecation）。

### 2026-06-25 Excel→SQL 任務 JSON UI 建立功能

- 目的：讓具資料庫管理權限的使用者可在「Excel 匯入作業中心」透過 UI 建立真正的 Excel→SQL 任務 JSON 設定檔，而不是手動編輯 `config/excel_to_sql/*.json`。
- 主要修改：新增 `POST /v1/excel-to-sql/task-configs`（需 `db_operator` / `superuser`），後端以白名單檔名、SQL table/field/type 驗證與 atomic replace 產生 dashboard-enabled 設定檔；作業中心新增任務建立表單與欄位對應 UI，建立後重新載入任務清單並可直接用於上傳匯入。
- API Contract：已追加記錄 `POST /v1/excel-to-sql/task-configs` request/response 與錯誤語意。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 完成（pip upgrade 查詢套件索引遇 403 retry，但既有環境套件已滿足）；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 通過（17 passed）。

### 2026-06-25 Known issues memory compaction

- 因 `.codex/known_issues.md` 超過 400 行，已將濃縮前全文歸檔至 `.codex/archive/known_issues.md-20260625-130126.md`，並將 active known issues 重寫為目前仍有效摘要、近期 resolved / open items 與歸檔索引。
- 驗證：`wc -l .codex/known_issues.md .codex/memory.md` 確認 known issues 濃縮後低於 200 行。

### 2026-06-25 Excel→SQL 任務 JSON 子目錄與連線來源修正

- 目的：修正任務設定檔檔名不支援 `config/excel_to_sql` 下子目錄完整路徑，以及直接輸入 DB 帳密時需確認生成 JSON 會保存；同時降低業務使用者接觸資料庫帳密的需求。
- 主要修改：任務 JSON 檔名改支援如 `business/monthly_task.json` 的安全相對子路徑；新增 `connection_source_config`，可從既有任務 JSON 複製完整 `db` 區塊（server、database、user/password、encrypt、trust_server_certificate、driver 等）；前端新增「資料庫連線來源任務」下拉並優先建議沿用既有 DB 連線。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 完成（pip upgrade 查詢套件索引仍遇 403 retry，但 requirements 已滿足）；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 通過（20 passed）。

### 2026-06-25 Excel→SQL 任務 pending 審核與 SQL 型別輔助

- 目的：降低非資訊背景業務人員設定 SQL 型別與欄位比對方式的門檻，並避免具 `db_operator` 權限者建立任務後立刻啟用可上傳資料、影響 SQL schema 的任務。
- 主要修改：欄位對應的 SQL 型別輸入改提供常見 datalist 選項且保留手動輸入；新增欄位比對方式說明浮窗；新建任務改為 `dashboard.enabled=false` / `status=pending`，不出現在可上傳任務清單；新增 superuser-only `POST /v1/excel-to-sql/task-configs/approve` 將待審任務啟用為 active。
- 設計決策：已記錄「db_operator 建草稿、superuser 審核啟用」的雙人覆核原則於 `.codex/decisions.md`。
- 驗證：`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 通過（21 passed）。

### 2026-06-25 Excel→SQL 任務設定版面與 superuser 審核強化

- 目的：優化 Excel 匯入作業中心的建立任務設定區塊，將設定分成基本資訊、資料庫連線、Excel 來源與 SQL 目的地群組；並讓 superuser 審核改用選單、支援啟用與停用 pending 狀態。
- 主要修改：新增 superuser-only task config list/status API；前端僅於 `/v1/auth/me` 回傳 `superuser` 時顯示審核區，且後端 list / approve / status endpoint 均強制 `require_superuser`，避免非 superuser 直接打 API 啟用或停用任務。
- 驗證：`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py tests/test_excel_to_sql_user_imports.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 通過（22 passed, 3 warnings；warnings 為既有 Starlette/httpx 與 invalid escape deprecation）。套件安裝前置指令執行時 pip index 仍有 403 retry，但 requirements 已滿足。

### 2026-06-26 Excel→SQL superuser 審核轉換細節

- 目的：讓 superuser 在審核待審 Excel→SQL 任務前，可直接檢視任務 JSON 的資料來源、目的資料表、欄位對應、自動建表 / 建欄、audit、匯入、retry 與封存設定，降低只看檔名就啟用的風險。
- 主要修改：`GET /v1/excel-to-sql/task-configs` 對 superuser 回傳 `review_summary` 與遮蔽密碼後的 `config_preview`；前端審核下拉選定任務後即顯示「JSON 任務轉換細節」卡片與可展開的遮蔽 JSON。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 執行時 pip index 仍有 403 retry 但 requirements 已滿足；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py tests/test_excel_to_sql_user_imports.py`、`node --check sra_api/static/excel_to_sql_import_records.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 均通過（22 passed, 3 warnings；warnings 為既有 Starlette/httpx 與 invalid escape deprecation）。

### 2026-06-26 Excel→SQL SQL 型別選單與說明補強

- 目的：讓「預設欄位型別」與「Excel 欄位對應」的 SQL 型別輸入一致，都可用常用型別選單並保留手動輸入；同時為不熟 SQL 型別的使用者補充簡短用途說明。
- 主要修改：`taskDefaultFieldType` 改用 `list="sqlTypeOptions"`，與欄位對應列共用 `NVARCHAR(255)`、`NVARCHAR(MAX)`、`INT`、`BIGINT`、`DECIMAL(18,2)`、`FLOAT`、`DATE`、`DATETIME2`、`BIT` 選項；新增「常用 SQL 型別小提醒」說明區塊並更新前端 asset version。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 執行時 pip index 仍有 403 retry 但 requirements 已滿足；`python -m py_compile tests/test_excel_to_sql_user_imports.py`、`node --check sra_api/static/excel_to_sql_import_records.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 均通過（22 passed, 3 warnings；warnings 為既有 Starlette/httpx 與 invalid escape deprecation）。

### 2026-06-26 Excel→SQL 匯入任務欄位轉換檢視與多欄位拼裝

- 目的：讓資料庫管理者在「使用者 Excel 匯入操作」選擇任務時能看到該任務的 Excel→SQL 欄位轉換方式，並提供多個 Excel 欄位拼裝成一個 SQL 新欄位的實際匯入功能。
- 主要修改：`GET /v1/excel-to-sql/dashboard-tasks` 對啟用任務回傳非敏感 `review_summary`；作業中心會在上傳前顯示目前任務的欄位轉換。任務建立 UI 新增「多欄位拼裝成 SQL 新欄位」，後端 `composite_mappings` 會轉成帶 `compose` 的 mapping，匯入時將多個來源欄位依分隔字串組合後寫入新 SQL 欄位並參與自動建欄。View 自動建立未以 stub 提供，已記錄為後續設計。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 執行時 pip index 仍有 403 retry 但 requirements 已滿足；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/workbook_rows.py tests/test_excel_to_sql_user_imports.py`、`node --check sra_api/static/excel_to_sql_import_records.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 均通過（23 passed, 3 warnings；warnings 為既有 Starlette/httpx 與 invalid escape deprecation）。

### 2026-06-26 Excel→SQL composite template and task summary visibility

- 目的：確認資料修改者 / 閱讀者在「使用者 Excel 匯入操作」選擇任務時可看到 Excel→SQL 欄位轉換摘要，並補足 composite mappings 的模板式拼裝能力。
- 主要修改：`dashboard-tasks` 保持登入即可讀取 active 任務並含 `review_summary`；匯入作業中心會在任務選單下顯示欄位轉換摘要。`composite_mappings` 新增可選 `template`，支援 `{Excel欄名}` placeholder，以每列來源值組成 SQL 新欄位；未填模板時仍使用 separator 串接。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 執行時 pip index 仍有 403 retry 但 requirements 已滿足；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/workbook_rows.py tests/test_excel_to_sql_user_imports.py`、`node --check sra_api/static/excel_to_sql_import_records.js`、`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q`、`git diff --check` 均通過（24 passed, 3 warnings；warnings 為既有 Starlette/httpx 與 invalid escape deprecation）。

### 2026-06-26 Excel→SQL 任務 JSON 管理分頁與建立者權限

- 目的：讓 db_operator 建立待審任務 JSON 後，可查看自己建立的任務清單與審核進度，並只能停用 / 刪除自己建立的任務；同時將較少使用且較獨立的任務 JSON 建立流程移出 Excel 匯入作業中心。
- 主要修改：新增 `/excel-to-sql-task-configs` 獨立頁與 Editor 導航按鈕；`GET /v1/excel-to-sql/task-configs` 預設 `scope=mine`，`scope=all` 僅 superuser 可用；db_operator 可停用自己的任務但不能啟用任務；新增 `DELETE /v1/excel-to-sql/task-configs` 刪除自己建立的任務設定檔。
- UI 調整：SQL 型別欄位不再預填 `NVARCHAR(MAX)`，改用 placeholder 與 datalist 提示；常用 SQL 型別提示與下方按鈕增加間距；Excel 來源目錄說明補充其為伺服器批次掃描資料夾，上傳 Excel 不依賴使用者本機存在該目錄。
- 驗證：`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（14 passed, 1 warning；warning 為既有 StarletteDeprecationWarning）。執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 時 pip upgrade 查詢套件索引遇 403 retry，但目前 requirements 已滿足。

### 2026-06-26 Excel→SQL 連線來源 UI 帶入 ODBC / trusted connection

- 目的：當建立 Excel→SQL 任務設定檔時，若使用者選擇既有任務作為資料庫連線來源，前端同步帶入該任務的 ODBC Driver 與 trusted connection 勾選狀態，避免 UI 顯示仍停留在預設值造成誤解。
- 主要修改：`excel_to_sql_import_records.js` 新增 `applyConnectionSourceDefaults()`，在載入連線來源選項與使用者切換來源時，從 `review_summary.db` 套用 `driver` 與 `trusted_connection` 到表單。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` requirements 已滿足但 pip upgrade 索引查詢遇 403 retry；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/task_configs.py tests/test_excel_to_sql_user_imports.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（22 passed, 1 warning）；`git diff --check` 通過。

### 2026-06-26 Excel→SQL 導航與任務連線來源調整

- 目的：調整 Editor / Excel→SQL 三頁導航文案與對稱性，移除匯入作業中心的重複任務管理區塊，並讓建立 Excel→SQL 任務設定檔時可從既有任務帶入 DB 連線資訊。
- 主要修改：Editor 導航「監控 Dashboard」改為「SQL條目匯入情況監控Dashboard」；Excel 匯入作業中心移除「任務設定檔管理」卡片；Excel→SQL 匯入查詢儀表板新增「任務 JSON 管理」按鈕；任務設定檔頁的資料庫連線來源候選改為合併 dashboard active 任務與使用者可見的既有任務 JSON，選取後帶入 server、database、user、driver 與 trusted connection 顯示值，建立 payload 仍以 connection_source_config 沿用來源任務 DB 設定。
- 驗證：`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_excel_to_sql_dashboard_static.py tests/test_editor_auth_ui_static.py -q` 通過（43 passed, 3 warnings；warnings 為既有 Starlette / invalid escape deprecation）。依規定先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，pip upgrade 遭套件索引 403 retry 但結束碼 0，requirements 均已 satisfied。

### 2026-06-26 Excel→SQL audit 批次刪除與報告

- 目的：依 review 回饋將 Editor 匯入管理導航與目標頁標題一致，並改善 Excel→SQL 匯入查詢儀表板中最近 audit 事件的時間篩選、批次 SQL row 刪除與刪除報告下載。
- 主要修改：Editor 導航文字改為「Excel→SQL 匯入查詢儀表板」；最近 audit 事件篩選新增本機起訖時間欄位並共用 datetime-local 轉 UTC helper；recent table 增加可刪除列勾選欄、批次刪除按鈕、批次刪除報告 Excel（HTML .xls）下載；新增 `POST /v1/excel-to-sql/delete-rows`，逐一呼叫既有單筆刪除流程並彙整報告，單筆刪除 response 也回傳刪除前 payload 供報告使用。
- 設計結論：只刪 SQL 不應直接硬刪 ES。已在 decisions/backlog 記錄建議後續採 lineage metadata + SQL delete outbox/tombstone + ES soft-delete/supersede 或人工審核補償流程，避免跨系統交易與誤刪。
- 驗證：`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/dashboard_delete.py data_ingestion/excel_to_sql/mock_sql.py tests/test_dashboard_filters.py` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_editor_auth_ui_static.py tests/test_vercel_mock_runtime.py -q` 通過（43 passed, 1 warning）；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（15 passed, 1 warning）。依規定先執行套件安裝前置指令，pip upgrade 仍遇索引 403 retry 但 requirements 均已 satisfied。

### 2026-06-26 Excel→SQL 批次刪除確認機制強化

- 目的：回應批次刪除 SQL 條目需避免誤按造成事故的疑慮。
- 主要修改：批次刪除前端流程改為多階段確認：必填刪除原因、顯示批次筆數與前 5 筆 hash、要求輸入精確確認字串 `DELETE <筆數>`，最後再顯示 browser confirm；確認字串不符合時不呼叫批次刪除 API。
- 驗證：`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_editor_auth_ui_static.py tests/test_vercel_mock_runtime.py tests/test_excel_to_sql_user_imports.py -q` 通過（58 passed, 1 warning）；`git diff --check` 通過。依規定先執行套件安裝前置指令，pip upgrade 仍遇索引 403 retry 但 requirements 均已 satisfied。

### 2026-06-26 Excel→SQL 任務連線來源敏感欄位遮蔽

- 目的：建立 Excel→SQL 任務設定檔時，選擇既有 JSON 作為資料庫連線來源後，不再把 Server、資料庫名稱、DB 使用者與 DB 密碼顯示在頁面上，只提示後端會讀取套用該設定檔連線資訊。
- 主要修改：任務設定頁新增連線來源提示與敏感欄位 hide/disabled/clear 行為；既有來源只帶入較不敏感的 ODBC Driver 與 trusted connection；任務清單 / 審核摘要與遮蔽 JSON 也同步遮蔽 db server、database、user、password。
- 驗證：`python -m pip install --upgrade pip` 遇到套件索引 403 retry，但環境已有 pip；`python -m pip install -r requirements.txt` 顯示相依套件已滿足；`python -m py_compile data_ingestion/excel_to_sql/task_configs.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（15 passed, 1 warning；warning 為既有 Starlette / httpx deprecation）。

### 2026-06-26 Excel→SQL SSH active config status display fix

- 目的：修正以 SSH 直接放到伺服器、已可導入 Excel 的 `dashboard.enabled=true` 任務，在「資料庫連線來源任務」選項被標示為 pending 的問題。
- 主要修改：dashboard 任務探索現在對所有可上傳任務回傳 `enabled=true` 與 `status=active`；任務設定檔清單也以 `dashboard.enabled=true` 作為 active 顯示權威，即使舊 JSON 仍留有 `dashboard.status=pending` 也不再顯示 pending。
- 驗證：`python -m pip install --upgrade pip` 遇到套件索引 403 retry，但環境已有 pip；`python -m pip install -r requirements.txt` 顯示相依套件已滿足；`python -m py_compile data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/task_configs.py` 通過；`PYTHONPATH=. pytest tests/test_dashboard_filters.py tests/test_excel_to_sql_user_imports.py -q` 通過（27 passed, 1 warning；warning 為既有 Starlette / httpx deprecation）；`git diff --check` 通過。

### 2026-06-26 Excel→SQL connection source excludes pending tasks

- 目的：回應「建立 Excel→SQL 任務設定檔」的資料庫連線來源選單不應列出尚未 active、仍為 pending 的任務。
- 主要修改：前端合併 dashboard active 任務與 task-config list 後，新增 `isActiveConnectionSourceTask()` 過濾，只保留 `enabled=true` 或 `status=active` 的設定檔作為連線來源候選；pending 任務仍可留在我的任務清單 / superuser 審核區，不再出現在連線來源下拉。
- 驗證：`python -m pip install --upgrade pip` 遇到套件索引 403 retry，但環境已有 pip；`python -m pip install -r requirements.txt` 顯示相依套件已滿足；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_dashboard_filters.py -q` 通過（27 passed, 3 warnings；warnings 為既有 Starlette / Python invalid escape deprecation）；`git diff --check` 通過。

### 2026-06-29 Excel→SQL SQL 型別提示文案調整

- 目的：回應 JSON 任務設定頁的 SQL 欄位型態灰底提示使用 `NVARCHAR(255)` 可能讓業務使用者誤以為長文字也適用，造成較長描述或 JSON 欄位匯入 SQL 時被拒絕或截斷風險。
- 主要修改：任務設定頁的預設欄位型別與欄位對應提示改為「長文字建議 NVARCHAR(MAX)，短代碼才用 NVARCHAR(255)」，並在 SQL 目的地說明與常用型別提醒中明確說明 `NVARCHAR(255)` 最多 255 字元、不適合描述 / JSON / 可能很長的欄位；前端 JS asset version 已更新以避免瀏覽器快取舊提示。
- 驗證：`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（16 passed, 3 warnings；warnings 為既有 Starlette / Python invalid escape deprecation）。執行 `python -m pip install --upgrade pip` 時套件索引回覆 403 retry，但目前環境已有所需套件，`python -m pip install -r requirements.txt` 顯示 requirements 已滿足。

### 2026-06-29 Editor 登入冷卻與輸入提示改善

- 目的：回應使用者詢問登入密碼因大小寫、全半型或中英輸入錯誤導致多次失敗後被暫時鎖定的冷卻時間、superuser 是否可解鎖，以及是否能提示常見輸入錯誤。
- 主要修改：登入冷卻維持 15 分鐘失敗觀察窗、5 次失敗門檻與 5 分鐘冷卻，但 429 訊息會顯示約略剩餘時間；新增 `POST /v1/auth/users/{username}/unlock-login` 供 superuser 清除該帳號目前記憶體中的 login throttle；Editor 帳號管理 UI 增加「解除登入冷卻」按鈕；登入前後偵測帳號非 ASCII、密碼全形、中文、前後空白與 Caps Lock 並提示使用者。
- 驗證：`python -m py_compile sra_api/routers/editor_auth.py sra_api/services/auth_store.py` 通過；`node --check sra_api/static/editor_auth_nav.js` 與 `node --check sra_api/static/editor_documents.js` 通過；`PYTHONPATH=. pytest tests/test_auth_store_security.py tests/test_editor_auth_ui_static.py -q` 通過（43 passed, 1 warning；warning 為既有 Starlette TestClient deprecation）。執行 `python -m pip install --upgrade pip` 時套件索引回覆 403 retry，但 `python -m pip install -r requirements.txt` 顯示相依套件已滿足。

### 2026-06-29 portable_auth_pack 登入冷卻功能同步

- 目的：將主系統 Editor 帳密登入冷卻剩餘時間、superuser 解除登入冷卻與登入輸入提示同步加入 `portable_auth_pack` 範例包，避免範例包與主系統功能分岔。
- 主要修改：portable auth route 的 429 detail 會顯示約略剩餘時間；新增 `POST /v1/auth/users/{username}/unlock-login`；auth store 增加跨 client host 清除特定帳號 login throttle 的 helper；portable minimal admin UI 新增登入輸入提示、Caps Lock 提醒與「解除登入冷卻」按鈕；README / import guide / API contract 已同步說明。
- 驗證：`python -m py_compile portable_auth_pack/fastapi_auth_pack/auth_routes.py portable_auth_pack/fastapi_auth_pack/auth_store.py portable_auth_pack/scripts/verify_auth_pack.py` 通過；`node --check portable_auth_pack/static/login_admin_auth.js` 與 `node --check portable_auth_pack/static/login_admin_admin.js` 通過；`PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py -q` 通過（22 passed, 1 warning）；`PYTHONPATH=. python portable_auth_pack/scripts/verify_auth_pack.py` 通過。執行 `python -m pip install --upgrade pip` 時套件索引回覆 403 retry，但 `python -m pip install -r requirements.txt` 顯示相依套件已滿足。

### 2026-06-29 Excel→SQL 任務欄位轉換權限控制

- 目的：修正資料修改者（data_editor）可在 Excel 匯入作業中心看到任務 Excel→SQL 欄位轉換細節的問題。
- 主要修改：`GET /v1/excel-to-sql/dashboard-tasks` 依使用者角色回傳任務資訊；`db_operator` / `superuser` 保留 `review_summary`，低於資料庫操作者權限的角色會移除欄位轉換摘要。前端同步加上 `db_operator` / `superuser` 檢查，非資料庫管理權限不渲染欄位轉換說明。
- 範例包修正：`config/excel_to_sql/vessel_activities.example.json` 的 DB 連線欄位改為 placeholder，避免範例檔看起來像真實內網連線資訊。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt && python -m py_compile sra_api/routers/excel_to_sql.py && node --check sra_api/static/excel_to_sql_import_records.js && PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（18 passed, 3 warnings；pip upgrade 查詢套件索引仍出現既有 403 retry，但 requirements 已滿足）。

### 2026-06-29 Excel→SQL 任務設定頁權限與拼裝檢查

- 目的：修正資料管理帳號在「建立待審任務 JSON」按下後無反應，並降低無權限使用者誤入 Excel→SQL 任務設定檔建立頁的機率。
- 主要修改：任務設定頁共用 JS 的 preview 顯示改為支援沒有 `previewBox` 的頁面，避免成功建立後前端例外；Editor 導航會依角色隱藏 / 停用「任務 JSON 管理」按鈕，任務設定頁本身也會對非 `db_operator` / `superuser` 顯示權限提示並隱藏建立表單。
- 拼裝欄位：新增拼裝欄位比對方式選項並寫入 JSON；後端接受 composite mapping 的 `match`（exact / prefix / contains）。現行匯入解析若 prefix / contains 命中多個欄位，會選用排序後最短且最前面的欄位並留下 ambiguous 診斷訊息；因此 UI 送出前智慧檢查會攔截拼裝欄位使用非 exact、目的欄位重複、拼裝來源不足、來源重複與模板 placeholder 未列入來源欄位等常見問題。
- 驗證：`python -m pip install --upgrade pip` 因套件索引 403 retry 但本機 pip 已存在；`python -m pip install -r requirements.txt` 顯示 requirements 已滿足；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`node --check sra_api/static/editor_auth_nav.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_editor_auth_ui_static.py -q` 通過（40 passed, 1 warning）。

### 2026-06-29 Excel→SQL 拼裝欄位 ambiguity 檢查時機修正

- 目的：修正前次說明與 UI 檢查過度保守的問題；建立任務 JSON 時尚未讀取使用者未來會上傳的 Excel，因此無法判斷 `prefix` / `contains` 是否會命中多個實際標題欄位。
- 主要修改：任務設定頁文案改為明確說明 ambiguity 只會在預掃描或確認匯入讀到實際 Excel 標題列時檢查並進入診斷；前端智慧檢查只攔截目前表單內容即可判斷的錯誤（目的欄位重複、拼裝來源不足、來源重複、模板 placeholder 不在來源欄位），不再把拼裝欄位使用非 `exact` 當成建立 JSON 時的阻擋錯誤。
- 驗證：`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過。

### 2026-06-29 Excel→SQL 拼裝欄位非 exact 比對允許說明

- 目的：釐清「不再把拼裝欄位使用非 exact 當成建立 JSON 時的阻擋錯誤」不代表不能使用非 exact；拼裝來源欄位可使用 `exact`、`prefix` 或 `contains`。
- 主要修改：任務設定頁文案改為明確說明建立 JSON 時不會因為選 `prefix` / `contains` 而被擋下；只有需要實際 Excel 標題列的不唯一問題會延後到預掃描或確認匯入時診斷。
- 驗證：`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過。

### 2026-06-29 Excel→SQL task_configs 拆檔評估與重構

- 目的：回應 `editor_auth_nav.js`、`task_configs.py`、`excel_to_sql_import_records.js` 是否過於肥大。實測行數：`editor_auth_nav.js` 194 行、`excel_to_sql_import_records.js` 364 行、`task_configs.py` 525 行；依既有 500 行門檻，優先拆分 `task_configs.py`。
- 主要修改：新增 `data_ingestion/excel_to_sql/task_config_builder.py`，承接任務 JSON build / validation；`task_configs.py` 保留路徑解析、檔案建立、審核摘要、列表、啟停與刪除 facade。拆分後 `task_configs.py` 約 299 行，builder 約 236 行；兩個 JS 檔目前低於門檻，先保留避免前端 script 載入順序與全域函式風險。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/task_configs.py data_ingestion/excel_to_sql/task_config_builder.py` 通過；`node --check sra_api/static/excel_to_sql_import_records.js` 與 `node --check sra_api/static/editor_auth_nav.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py tests/test_editor_auth_ui_static.py -q` 通過（40 passed, 3 warnings）。

### 2026-06-29 Excel→SQL 任務 JSON 建立回饋改善

- 目的：改善 Excel→SQL 任務 JSON 管理頁建立待審任務時的使用者回饋，避免成功訊息只出現在頁面上方而被忽略，並修正未輸入任務名稱時顯示 `[object Object]` 的不明錯誤。
- 主要修改：任務建立成功後除頁面訊息外會以瀏覽器對話框提示；前端新增 API error detail formatter，將 FastAPI validation list/object 轉成可讀文字；送出前若任務名稱空白會直接提示「請輸入任務名稱。」；設定檔檔名未以 `.json` 結尾時會自動補上副檔名並在頁面提示使用者。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt && node --check sra_api/static/excel_to_sql_import_records.js && PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（18 passed, 3 warnings；pip upgrade 查詢套件索引仍出現既有 403 retry，但 requirements 已滿足）。

### 2026-06-29 Excel 匯入 compose template 空列跳過修正

- 任務目的：修正 Excel 匯入任務使用 compose.template 時，空白列會被模板固定文字組成非空 payload，導致 `skip_empty_rows=true` 無法跳過空列的問題。
- 主要修改：`data_ingestion/excel_to_sql/workbook_rows.py` 在 compose 欄位處理時新增來源欄位是否有實際值的判斷；若模板來源全為空，compose 產出改為 `None`，避免固定模板文字讓空列被視為有效資料列。
- 測試：已執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（環境套件已存在，但 pip index 連線顯示 403 retry 警告）；已執行 `pytest tests/test_excel_to_sql_user_imports.py -q`，結果 19 passed、3 warnings。
- 重要結論：空列判定應以 Excel 來源值為準，compose.template 僅在至少一個來源欄位有值時產生描述文字。

### 2026-06-29 Excel→SQL superuser 刪除任務與拼裝欄位比對簡化

- 目的：回應任務 JSON 管理頁 superuser 全站審核區缺少刪除任務設定檔操作，以及多欄位拼裝另外選比對方式造成使用者混淆。
- 主要修改：superuser 審核區新增「刪除任務設定檔」按鈕，沿用既有後端 DELETE `/v1/excel-to-sql/task-configs` superuser 權限；拼裝欄位 UI 移除獨立比對選項，建立 JSON 時會從上方單欄欄位對應中相同來源欄位繼承 exact / prefix / contains，並寫入 `compose.source_matches` 供匯入解析逐來源欄位套用。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt`（requirements 已存在，pip index 仍有 403 retry 警告）；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`python -m py_compile data_ingestion/excel_to_sql/workbook_rows.py data_ingestion/excel_to_sql/task_config_builder.py tests/test_excel_to_sql_user_imports.py` 通過；`pytest tests/test_excel_to_sql_user_imports.py -q` 通過（20 passed, 1 warning）；`git diff --check` 通過。

### 2026-06-29 Excel→SQL 拼裝欄位實體儲存與 View 模式說明

- 目的：回應使用者詢問多欄位拼裝是否會建立新欄並重複保存完整資料、是否浪費空間，以及能否改用 SQL View。
- 主要修改：任務 JSON 管理頁說明目前拼裝欄位為實體欄位模式，會多佔 SQL 空間但查詢 / 匯出 / 下游消費簡單；同步說明 View / computed expression 可降低重複儲存，但目前尚未開放真正建 View，需補齊 view name、CREATE OR ALTER 權限、欄位引用安全檢查、audit/hash/downstream 資料流設計。
- 後續：已在 `.codex/backlog.md` 追加 View 模式設計待辦；本次未新增 STUB 或假 View 功能。

### 2026-06-29 Excel→SQL composite source match preservation

- 目的：回應 Codex Review 指出多欄位拼裝來源欄位未填 match 時被強制記為 `exact`，導致 runtime 原本可用的 `smart` / legacy composite match 無法解析如 `地點（中文）` 這類標題。
- 主要修改：任務設定 builder 對一般欄位未填 match 時記錄為 runtime 預設 `smart`；composite mapping 支援並保留自身 `match` 作為未列於一般 mappings 來源欄位的 fallback；`compose.source_matches` 不再把未指定來源一律降成 `exact`。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 完成（pip upgrade 索引仍有 403 retry，但 requirements 均已滿足）；`python -m py_compile data_ingestion/excel_to_sql/task_config_builder.py tests/test_excel_to_sql_user_imports.py` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（21 passed, 3 warnings，warnings 為既有 Starlette / invalid escape 訊息）。

### 2026-06-29 Excel→SQL 任務 JSON UI 回饋與拼裝說明收合

- 目的：避免任務 JSON 管理頁建立失敗訊息只顯示在頁面上方、使用者未往上捲動而誤以為系統無反應；並降低「多欄位拼裝成 SQL 新欄位」長篇說明佔用版面。
- 主要修改：建立任務時的前端驗證錯誤、缺少任務名稱 / 欄位對應與 API 錯誤除頁面訊息外，也會用瀏覽器 alert 跳窗提示；拼裝欄位說明改為可展開 / 收合的 details 區塊，並分成實體欄位模式、拼裝規則、欄名比對與診斷、未來 View 模式四段條列。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 完成（pip upgrade 索引仍有 403 retry，但 requirements 均已滿足）；`node --check sra_api/static/excel_to_sql_import_records.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_user_imports.py -q` 通過（21 passed, 1 warning，warning 為既有 Starlette TestClient deprecation）；`git diff --check` 通過。

### 2026-07-01 Excel→SQL dashboard 肥大檔案拆分

- 目的：依使用者要求掃描單檔過大的程式 / HTML / JS / CSS，優先針對接近 500 行且職責可拆的 Excel→SQL dashboard 後端檔案進行小範圍重構。
- 主要修改：`data_ingestion/excel_to_sql/dashboard.py` 保留既有 facade 與 API 呼叫相容性，將 dashboard task discovery 拆至 `dashboard_tasks.py`，將批次刪除報表組裝拆至 `dashboard_batch_delete.py`；保留 monkeypatch seam，既有測試可繼續 patch `dashboard.delete_imported_sql_row`。
- 掃描結果：排除 vendored Swagger 與檔名含複製的檔案後，仍有 `tests/test_excel_to_sql_user_imports.py`、`sra_api/routers/excel_to_sql.py`、`data_ingestion/sql_to_es/ingest_sql.py`、`data_ingestion/excel_to_sql/workbook_rows.py` 等較大檔案可列為後續拆分候選；本次未擴大改動以降低風險。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/dashboard_tasks.py data_ingestion/excel_to_sql/dashboard_batch_delete.py` 通過；`PYTHONPATH=. pytest tests/test_dashboard_filters.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（19 passed）。`python -m pip install --upgrade pip` 因套件索引 tunnel 403 未能升級，但 `python -m pip install -r requirements.txt` 顯示需求已滿足。

### 2026-07-01 Excel→SQL 刪除 SQL 列來源任務修正

- 目的：修正匯入查詢儀表板刪除 SQL 列時，使用上方目前選取的匯入任務定位 table，若 audit 列實際來源任務不同會刪錯 table 或找不到資料，且錯誤只出現在畫面上方不易察覺的問題。
- 主要修改：刪除按鈕改從 audit row payload 的 `config_path` / `source_config_path` 取得來源任務設定檔，與上方選項不同時跳出確認；批次刪除限制同批必須同一來源任務；訊息區同步呼叫瀏覽器 alert；匯入 audit payload 補寫來源任務設定檔，刪除 API 回傳與刪除 audit message 也包含 config_path / destination_table。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/file_processor.py data_ingestion/excel_to_sql/dashboard_delete.py tests/test_dashboard_filters.py tests/test_excel_to_sql_dashboard_static.py tests/test_audit.py` 通過；`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_audit.py tests/test_sql_utils.py -q` 通過（38 passed, 4 warnings；warnings 為既有 `datetime.utcnow()` deprecation）。

### 2026-07-01 Excel→SQL 刪除來源任務資訊權限修正

- 目的：回應 dashboard audit payload 內未顯示 `config_path` 的疑問與 SQL table / 任務設定檔對低權限讀者可見的資安顧慮；前次做法若把任務路徑寫入每筆 `row_payload`，會讓所有可看 audit payload 的使用者看到操作型 metadata。
- 主要修改：不再把 `config_path` / `source_config_path` 寫入通用 audit `row_payload`；dashboard 改於查詢時只對 `db_operator` 以上角色，透過使用者匯入 registry 由 `source_file` 對應回來源任務設定檔並加到 top-level `source_config_path`，供刪除操作使用。非 db_operator 會移除 `destination_table_options`、recent row 的 `destination_table` 與 `source_config_path`，且前端不顯示刪除勾選 / 按鈕。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/file_processor.py sra_api/routers/excel_to_sql.py tests/test_dashboard_filters.py tests/test_audit.py tests/test_excel_to_sql_dashboard_static.py` 通過；`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_audit.py tests/test_sql_utils.py tests/test_vercel_mock_runtime.py -q` 通過（42 passed, 4 warnings；warnings 為既有 `datetime.utcnow()` deprecation）。

### 2026-07-01 Excel→SQL db_operator 操作來源欄位

- 目的：回應 db_operator 以上使用者雖可刪除，但表格中缺少一眼辨識該 audit row 來源任務與 SQL table 的資訊。
- 主要修改：最近 audit 事件表格新增「操作來源」欄；只有 `can_delete=true`（db_operator 以上）時顯示來源任務檔名、目的 SQL table，且當 row 的來源任務與上方目前選取任務不同時顯示警示。低權限使用者仍不取得後端操作 metadata，因此該欄不顯示敏感內容。
- 驗證：`python -m pip install -r requirements.txt` 通過；`python -m py_compile data_ingestion/excel_to_sql/dashboard.py data_ingestion/excel_to_sql/file_processor.py sra_api/routers/excel_to_sql.py tests/test_dashboard_filters.py tests/test_audit.py tests/test_excel_to_sql_dashboard_static.py` 通過；`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_audit.py tests/test_sql_utils.py tests/test_vercel_mock_runtime.py -q` 通過（42 passed, 4 warnings；warnings 為既有 `datetime.utcnow()` deprecation）。

### 2026-07-01 Excel→SQL dashboard 依選定任務篩選 audit

- 目的：修正儀表板上方選擇「匯入任務」後，下方 audit 仍混合顯示同一 audit table 中其他任務資料列，導致使用者需要依 row 來源判斷刪除目標的反直覺行為。
- 主要修改：dashboard 查詢會依目前選定 config 建立 source_file scope，包含 user import registry 中該 config 的上傳檔、設定檔 `source.excel_path` 與 `source.directory` / `source.excel_dir` 前綴；summary、daily、files、destination table options、username options 與 recent audit 都套用相同 scope。操作來源欄仍保留用於 db_operator 快速確認與 legacy / fallback 情境。
- 驗證：`python -m pip install -r requirements.txt` 通過；`python -m py_compile data_ingestion/excel_to_sql/dashboard.py sra_api/routers/excel_to_sql.py tests/test_dashboard_filters.py tests/test_excel_to_sql_dashboard_static.py` 通過；`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py tests/test_dashboard_filters.py tests/test_ingest_diagnostics.py tests/test_ingest_insert_fallback.py tests/test_audit.py tests/test_sql_utils.py tests/test_vercel_mock_runtime.py -q` 通過（43 passed, 4 warnings；warnings 為既有 `datetime.utcnow()` deprecation）。

### 2026-07-01 Excel→SQL dashboard 操作來源欄位權限顯示

- 目的：調整 Excel→SQL 匯入查詢儀表板最近 audit 事件表格，避免沒有刪除權限 / 無法查看操作來源的使用者看到空白「操作來源」欄位，並縮減該欄寬度以節省水平空間。
- 主要修改：`excel_to_sql_dashboard.html` 將 `op-col` 欄寬由 10% / 260px 改為 5% / 130px，payload 欄寬同步增加；新增 `operator-source-hidden` CSS 讓無權限時隱藏 `col/th/td.op-col`。`excel_to_sql_dashboard_app.js` 在 dashboard payload 的 `can_delete` 權限狀態更新後同步切換表格 class。
- 驗證：`python -m pip install --upgrade pip` 因既有 package index 403 retry 未能升級至最新 pip，但目前套件已安裝；`python -m pip install -r requirements.txt` 顯示 requirements 已滿足；`node --check sra_api/static/excel_to_sql_dashboard_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（9 passed）。

### 2026-07-01 SQL 來源資料編輯器第一版

- 目的：在 Excel 匯入流程管理底下新增像資料表 UI 的 SQL 來源資料編輯器，讓使用者可直接瀏覽與單列修正 Excel→SQL 任務目的資料表，而不只能從 audit 事件刪除列。
- 主要修改：新增 `data_ingestion/excel_to_sql/table_editor.py`，以任務設定檔白名單方式查詢 `destination.table`、提供分頁搜尋與單列更新；新增 `GET /excel-to-sql-source-editor`、`GET /v1/excel-to-sql/source-rows`、`PATCH /v1/excel-to-sql/source-row`；新增 `excel_to_sql_source_editor.html/js` 並在 Editor 匯入管理導航加入「SQL 來源資料編輯器」。
- 權限決策：`data_editor` 可讀與單列編輯，需 reason、禁止改 hash / 系統欄位並寫 audit；刪除 / 批次刪除維持 `db_operator` 以上與二次確認，不要求 superuser。
- 驗證：`python -m py_compile data_ingestion/excel_to_sql/table_editor.py sra_api/routers/excel_to_sql.py` 通過；`node --check sra_api/static/excel_to_sql_source_editor_app.js sra_api/static/editor_bootstrap.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py tests/test_excel_to_sql_dashboard_static.py::test_sql_source_editor_page_and_navigation_are_wired -q` 通過。

### 2026-07-01 SQL 來源資料編輯器白名單說明補強

- 回應使用者詢問：SQL 來源資料編輯器的 audit 使用同一個 Excel→SQL audit table schema，但以 `sql_source_editor.update_row` action/status 與 `source_file=sql-source-editor` 區分人工編輯事件；「table 白名單」補強為只能操作 `discover_dashboard_tasks(config_dir)` 已啟用任務清單中的設定檔與其 `destination.table`，避免任意 config path / table name。
- 驗證：`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py -q` 通過（4 passed, 1 existing Starlette TestClient warning）。

### 2026-07-01 SQL 來源資料編輯器 UI / 篩選 / 導航修正

- 目的：改善 SQL 來源資料編輯器頁面空間、登入狀態與二層 Excel→SQL 導航一致性，並加入接近 Excel→SQL audit dashboard 的常用篩選操作。
- 主要修改：將受控資料表長說明改為點擊展開的 tooltip / popover；來源編輯器 header 改用與 Excel→SQL dashboard 相同的深色列與按鈕風格，補齊 Excel 匯入作業中心、任務 JSON 管理與登入 / 編輯器導航；Excel→SQL dashboard、匯入作業中心與任務 JSON 管理頁皆補上 SQL 來源資料編輯器按鈕。
- 後端：`GET /v1/excel-to-sql/source-rows` 增加 source_file、row_no、hash 與資料欄位 payload 關鍵字篩選，仍只操作已啟用任務設定檔的 `destination.table`。
- 驗證：`node --check sra_api/static/excel_to_sql_source_editor_app.js` 通過；`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/table_editor.py` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py tests/test_excel_to_sql_dashboard_static.py -q` 通過（14 passed, 1 warning）。執行 `python -m pip install --upgrade pip` 時套件索引更新檢查遭 403，但 `python -m pip install -r requirements.txt` 顯示需求已安裝。

### 2026-07-01 SQL 來源資料編輯器使用者篩選補強

- 目的：回應 review 問題，讓 SQL 來源資料編輯器也提供與 Excel→SQL audit dashboard 相同操作風格的使用者多選篩選。
- 主要修改：來源編輯器頁面載入 `/static/audit_tools.js`，使用既有 `SraAuditTools.renderMultiFilterOptions` / `summarizeMultiFilterSelection` / `setVisibleMultiFilterSelection` helper 呈現使用者多選；後端 `source-rows` 支援 `username_filter` 並回傳 `username_options`，只在目的資料表存在 `username` / `audit_actor` / `audit_user` / `actor` 欄位時套用。
- 驗證：`node --check sra_api/static/excel_to_sql_source_editor_app.js`、`python -m py_compile sra_api/routers/excel_to_sql.py data_ingestion/excel_to_sql/table_editor.py`、`PYTHONPATH=. pytest tests/test_excel_to_sql_source_editor.py tests/test_excel_to_sql_dashboard_static.py -q` 均通過（15 passed, 1 warning）。

### 2026-07-02 SQL 來源資料編輯器登入承接修正

- 目的：修正使用者在 Editor 首頁成功登入後，透過導航進入「SQL 來源資料編輯器」時頁面仍顯示未登入的問題。
- 主要修改：Editor 導航到 SQL 來源資料編輯器時以 URL hash 傳遞一次性前端 token handoff；SQL 來源資料編輯器載入時從 hash 還原 `sra_editor_token` 到 localStorage，並立即用 `history.replaceState` 清除 hash，避免後續 API request 或頁面顯示攜帶 token。
- 任務清單說明：SQL 來源資料編輯器仍只列出 `/v1/excel-to-sql/dashboard-tasks` 回傳的已啟用 dashboard 任務；目前 repo 內預設只有 `config/excel_to_sql/vessel_activities.example.json`。
- 驗證：`python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 已執行，pip upgrade 檢查遇到套件索引 403 retry 但既有套件已滿足；`node --check sra_api/static/editor_bootstrap.js` 通過；`node --check sra_api/static/excel_to_sql_source_editor_app.js` 通過；`PYTHONPATH=. pytest tests/test_excel_to_sql_dashboard_static.py -q` 通過（10 passed）。
