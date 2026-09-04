# API Contract

## 2026-09-04 Phase 1B Requirement management

- Authenticated reads cover sources, profiles, import runs, sets, snapshots, and items.
- `db_operator+` manages metadata/versions and imports; source/profile enablement and version approval require `superuser`.
- Manual preview/import accepts multipart `file`; preview may select a draft, while commit always uses the approved active version. Errors use safe `detail.code` values.
- Named SQL acquisition failures expose only `sql_read_error` (HTTP 503); Requirement persistence failures expose only `persistence_error` (HTTP 500). Stale/anomaly conflicts remain HTTP 409 and validation errors retain their existing safe codes.
- Import Run diagnostics use SQL `NULL` for `source_row_number` when a safe profile/source-level failure cannot be attributed to one source row; row-scoped diagnostics retain their actual row number and bounded safe code/message.

## 2026-09-02 Phase 0 unified security boundary

- `GET /v1/models`, `POST /v1/chat/completions`, and `POST /v1/report/word` require Bearer principals with `model:read`, `model:invoke`, and `report:sync` respectively.
- Report Job create/read/download require corresponding scopes; persisted `owner_kind`/`owner_id` enforce owner isolation, while `report:job:admin` may access all jobs.
- Document detail/fulltext and legacy Word export accept either the direct-read scope or an exact HMAC `sig` capability. Signed Word URLs always bind an explicit `turn_id`.
- Superuser-only service-key administration is exposed at `/v1/auth/service-keys`; plaintext is returned once on creation and never by list/revoke.

## 2026-09-01 Persisted report Job API

- `POST /v1/report/jobs` accepts the dedicated `{prompt, filename?, session_id?, model?, options?, metadata?}` model; default model is `SRA-Structured Retrieval Agent`, supported `options` is currently empty, and success is `202` with job/status/download URLs. Optional `Idempotency-Key` returns the same job for the same normalized resource and `409` for different content.
- `GET /v1/report/jobs/{job_id}` returns `queued|running|completed|failed|interrupted` persisted state; safe failure category/message may be present.
- `GET /v1/report/jobs/{job_id}/word` returns DOCX only for completed jobs: unknown is `404`, non-completed is `409`, and completed with a missing/invalid artifact is `500`.
- `POST /v1/report/word` remains synchronous `ChatPayload → DOCX`; `GET /v1/export/word` remains snapshot-based and independent of Job SQLite/files.

## 2026-09-01 Synchronous Word report automation

### `POST /v1/report/word`

- Request JSON：沿用 Chat 的 `model`、`messages`、`stream`，另可傳 `filename`（最長 180 字元）；`stream=true` 回 422。
- Session headers：依序採 `X-OpenWebUI-Chat-Id`、`X-Conversation-Id`、`X-Session-Id`，未提供則由 messages 推導。
- Success：200，body 為本輪 structured result 直接 render 的 DOCX；Content-Type 為 OOXML Word MIME，並回傳 `Content-Disposition`、`Content-Length`、`Cache-Control: no-store`、`X-Session-Id`、`X-Turn-Id`、`X-Request-Id`。
- Failure：validation 為 422；Agent 執行錯誤為 500 JSON detail，不回傳假的 Word 檔。
- 此 contract 為 synchronous execution，不依賴 `state.json` round-trip，也不包含 queue / scheduler。

### `POST /v1/chat/completions` metadata extension

- 非 META 正常 Agent response 的 `choices[0].message.context.word_export` 新增 `method`、URL-encoded `url`、`session_id`、`turn_id`。
- URL 指向既有 `GET /v1/export/word` 的精確輪次快照；既有 response 欄位不移除。

## Current Summary

- 本專案主要對外 API 由 FastAPI 提供，常用路由集中在 `sra_api/routers/`；OpenAI-compatible chat、Editor/Auth、Excel→SQL 匯入與 SQL 來源資料編輯器是目前主要 contract。
- Auth 使用 bearer token；角色階層為 `data_reader` < `data_editor` < `db_operator` < `superuser`。`GET /v1/auth/me` 回傳目前使用者資訊；登入、註冊、帳號審核、重設密碼與 unlock login contract 詳見歸檔歷史。
- `GET /v1/models`、`POST /v1/chat/completions`、`GET /v1/docs/{doc_id}`、`GET /v1/docs/{doc_id}/fulltext`、`GET /v1/export/word` 維持 OpenWebUI-compatible 公開整合 contract，不要求 Editor bearer token；`GET /healthz` 同樣公開。Editor/Auth、Excel 匯入與 SQL 資料管理端點才套用角色授權。
- Chat completion API 維持 OpenAI-compatible response shape；Editor 文件 API 與 form-config API 維持既有 ES 文件讀寫、mapping metadata 合併與 audit 記錄契約。
- Excel→SQL 匯入流程：`GET /v1/excel-to-sql/dashboard-tasks` 列出 `dashboard.enabled=true` 任務；`POST /v1/excel-to-sql/import-records` 建立上傳記錄；`POST /v1/excel-to-sql/import-records/{id}/preview` 預掃描；`POST /v1/excel-to-sql/import-records/{id}/confirm` 實際匯入 SQL。
- Excel→SQL dashboard：`GET /v1/excel-to-sql/dashboard` 支援 audit time range、status/source/user/destination/hash/payload filters、chart bucket 與 paging。`db_operator` 以上可取得 `can_delete=true` 與操作型 metadata；較低角色會移除 destination table / source config path 等操作資訊。
- Excel→SQL task config：`GET/POST/DELETE /v1/excel-to-sql/task-configs` 與 `POST /v1/excel-to-sql/task-configs/status` 管理任務 JSON；`scope=all` 與啟用任務需 `superuser`；`db_operator` 可建立與管理自己建立的 pending 任務。review summary / config preview 會遮蔽 DB server、database、user、password。
- `POST /v1/excel-to-sql/task-configs` 的 `overwrite=true` 不代表取得目標檔案授權：db_operator 僅能覆寫自己建立且尚未啟用的任務，superuser 才能覆寫其他建立者或已啟用任務。Dashboard、import upload 與 SQL batch delete 的 `config` 必須位於已啟用任務白名單，`config_dir` 不允許改指其他目錄。
- SQL row deletion：`POST /v1/excel-to-sql/delete-row` 使用 `{config, hash_value, reason}`，目前允許 `data_editor` 以上刪除已啟用白名單任務的單列，response 含刪除狀態、實際 config/destination/hash 欄位與刪除前 payload；`POST /v1/excel-to-sql/delete-rows` 仍需 `db_operator` 以上，支援 1-500 個 hash 的批次刪除與 report。
- SQL 來源資料編輯器：`GET /excel-to-sql-source-editor` 回傳靜態頁；`GET /v1/excel-to-sql/source-rows` 允許 active `data_reader` 以上唯讀，Query 支援 `config`、`q`、`source_file_filter`（audit source_file）、`import_start_ts` / `import_end_ts`（audit processed_at）、`username_filter`、`row_no_filter`、`hash_value_filter`、`payload_filter`、`page`、`limit`。Response 含 `columns`、`editable_columns`、`rows`、`username_options`、`can_edit`、`can_delete`、`can_batch_delete`；後端只允許已啟用任務的 `destination.table`，並用 audit table 補 `_import_username`、`_imported_at`、`_source_excel` 虛擬欄位。
- `PATCH /v1/excel-to-sql/source-row` 需 `data_editor` 以上，request 為 `{config, hash_value, changes, reason}`；禁止修改 hash/system/virtual 欄位，寫入 `sql_source_editor.update_row` audit payload（before / after / changes）。
- Dashboard selected-task audit scope 包含 registry / configured source 檔案，也包含 `run_id=manual-control` 且 `row_payload.config_path` 等於目前 config 的人工編輯/刪除 audit 事件，避免 SQL 來源資料編輯器操作在最近 audit 事件缺漏。
- Editor audit logs：`GET /v1/editor/audit-logs` query `limit` 允許 1-50000；response 含 `total`、`limit`、`hits` 與 `truncated`，當篩選後筆數超過回傳 hits 時 `truncated=true`，前端可由使用者設定載入筆數上限（預設 5000、最大 50000），若未完整載入需提醒使用者縮小帳號、動作或時間條件。

## Recent Changes

- 2026-08-27：`GET /v1/docs/{doc_id}/fulltext` 新增 `text_layer=reference|raw|both`（預設 `reference`）。JSON 新增 `text_layer`、`text_field`、`available_text_layers`；`both` 另回傳 `text_layers.reference/raw`，既有 `full_text` 保持代理人參考文本主值。TXT `both` 以明確標題串接兩層，下載檔名加入 layer suffix；明確要求但該層不存在時回傳 404。
- 2026-08-27：OpenWebUI citation Markdown 將單一「下載全文」拆成「下載參考文本」、「下載原始文本」、「下載雙層比對」，並將 JSON link 改為 `text_layer=both`；舊文件缺少 configured reference 時，raw / both link 仍可用。

- 2026-08-21（更正）：`GET /v1/excel-to-sql/dashboard` 的 `limit` 是 server-side pagination 的每頁 audit 事件筆數，不是另一個「載入列數上限」；預設 2000、上限 400000。
- 2026-08-21：`GET /v1/excel-to-sql/dashboard` 的 `limit` 預設值從 50000 降為 2000（上限仍為 400000），降低首次進入儀表板時的 SQL 回傳量與瀏覽器 DOM 壓力。
- 2026-07-02：帳號操作記錄查詢改以「載入筆數上限」欄位（預設 5000、最大 50000）控制 `/v1/editor/audit-logs` limit；API 上限提高到 50000 並回傳 `truncated` 供前端告警。SQL 來源資料編輯器新增「載入筆數上限」（預設 5000、最大 50000）；Excel→SQL dashboard 保留「載入列數上限」（預設 50000、最大 400000）。
- 2026-07-02：SQL 來源資料編輯器改為 data_reader 可唯讀、data_editor 可單列編輯/刪除、db_operator 可批次刪除；source-rows 新增 audit source_file / processed_at 篩選與 `_imported_at`、`_source_excel` 虛擬欄位；dashboard audit scope 納入 manual-control 事件。
- 2026-07-02：任務 JSON 管理「我建立的任務清單 / 審核進度」新增檢示 JSON 任務轉換細節，沿用遮蔽敏感資訊後的 `review_summary` / `config_preview`。
- 2026-07-01：SQL 來源資料編輯器加入已啟用任務白名單、匯入使用者 audit 篩選與 SQL row update audit。
- 2026-07-01：Dashboard selected-task audit scope、操作來源 metadata 與 dashboard delete-row response 補強。
- 2026-06-26：Excel→SQL task config self-service 與 batch SQL row deletion API 上線。

## Archived History

- `.codex/archive/api_contract.md-20260702-063606.md`：歸檔本次濃縮前的完整 API contract（含 2026-06-11 至 2026-07-02 詳細逐項 contract）。

## 2026-07-03 SQL 來源資料統計 API

### GET `/v1/excel-to-sql/source-stats`

- Auth：需登入；可讀取的 `config` 必須存在於已啟用 Excel→SQL dashboard task 白名單。
- Query：`config`、`q`、`source_file_filter`、`row_no_filter`、`hash_value_filter`、`payload_filter`、`username_filter`（可重複）、`import_start_ts`、`import_end_ts`、`group_by`（可重複）、`top_n`、`config_dir`。
- Response：`ok`、`config_path`、`destination_table`、`hash_field`、`columns`、`groupable_columns`、`username_options`、`total`、`groups`；其中 `groups[]` 包含 `field` 與 `buckets[]`（`value`、`count`）。

## 2026-07-03 Excel→SQL SQL 來源資料統計 API 補充

- `GET /v1/excel-to-sql/source-stats` 新增 query 參數 `chart_bucket`，可用值沿用 audit dashboard：`hour`、`6_hours`、`12_hours`、`day`、`week`、`month`，預設 `day`。
- Response 新增 `chart_bucket`、`chart_bucket_label`、`import_time_series` 與相容別名 `filtered_series`。`import_time_series` 以目前篩選後的 SQL 來源資料列與 Excel→SQL audit table 依 `hash_value` / `destination_table` 交叉比對，使用 audit `processed_at` 分桶回傳 `{ bucket_start, count }`。

### 2026-07-03 Excel→SQL SQL-backed tables sort contract

- `GET /v1/excel-to-sql/dashboard` 新增可重複 query 參數 `sort=field:asc|desc`，用於 audit 事件表。支援欄位：`processed_at`、`audit_id`、`status`、`source_file`、`username`、`row_no`、`message`、`hash_value`、`destination_table`。未提供時預設 `processed_at:desc`、`audit_id:desc`。response 新增 `recent_sort`，回傳實際套用的排序規則。
- `GET /v1/excel-to-sql/source-rows` 新增可重複 query 參數 `sort=field:asc|desc`，用於受控 SQL 來源資料表。支援欄位限目的資料表實體欄位；未提供時使用 hash 欄位或第一欄升冪排序。response 新增 `sort`，回傳實際套用的排序規則。
- 排序欄位採白名單驗證，方向只允許 `asc` / `desc`；非法欄位或方向回傳 400。

## 2026-07-03 靜態頁面路由

- `GET /agent-data-flow`：回傳 `sra_api/static/agent_data_flow.html`，用於顯示代理人資料運用處理流程 SVG 說明圖；不需要 request body，也不回傳 JSON API payload。

## 2026-08-26 Chat 結果 LLM 執行情況

- Agent 產出的結果物件可包含 `llm_execution[]`；每項包含 `stage`、`status`（`success`、`fallback` 或 `error`），並可選擇包含 `model_id`、`elapsed_sec`、`detail`。`detail` 是供糾錯的截短錯誤／備註，不包含完整 prompt 或 raw response。
- `/v1/export/word` 會在 Word 最後的「各階段使用模型」清單中，將模型 ID、執行狀態與耗時整合在同一項；fallback / error 可另列截短錯誤備註。舊 session 若只有 `data_agent.model_usage[]`，仍輸出相容的模型清單，但不虛構狀態或耗時。

## 2026-09-02 Signed-resource canonical query hardening

- Capability requests reject duplicate protected keys, unsupported query keys, non-canonical browser booleans, and resource/representation/session/turn substitutions before lookup.
- Successful signed document detail/fulltext and legacy Word responses include `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Content-Type-Options: nosniff`.

## 2026-09-03 Signed fulltext canonical query clarification

- Capability mode `GET /v1/docs/{doc_id}/fulltext` 的 `download` query representation只接受字串 `0` 或 `1`；duplicate、其他拼法或額外 query key均 fail closed為 401。成功 capability response持續回傳 `no-store`、`no-referrer`、`nosniff` headers。

## 2026-09-04 Batch Scheduler client contract

The scheduler consumes, without changing, `POST /v1/report/jobs` with `Authorization`, deterministic `Idempotency-Key`, `options={}`, and batch/task metadata; `GET /v1/report/jobs/{job_id}`; and `GET /v1/report/jobs/{job_id}/word` with the DOCX MIME type. Canonical inputs accept task_id, prompt, optional filename/session_id/model/offset-aware scheduled_at, and object metadata.
