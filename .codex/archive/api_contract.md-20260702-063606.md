# api contract


---

## 2026-06-11 標題列多層導航更新

- 本次僅調整靜態前端導航與 portable auth pack 參考頁 UI，未新增、移除或變更 API route、request 格式或 response 格式。


---

## 2026-06-11 帳號與文件紀錄分流更新

- 本次未新增、移除或變更 API route、request 格式或 response 格式。
- `POST /v1/auth/register`、`POST /v1/auth/users/{username}/approve`、`POST /v1/auth/users/{username}/reject`、`DELETE /v1/auth/users/{username}` 維持原 response shape，但會額外寫入 `auth.user_registered`、`auth.user_approved`、`auth.user_rejected`、`auth.user_deleted` audit events，供既有 `GET /v1/editor/audit-logs` 查詢後由前端分流顯示。

---

## 2026-06-11 Editor 使用統計與共用 audit tools API 更新

- 新增靜態資源 route：`GET /static/audit_tools.js`，回傳共用前端 audit / navigation 工具 JavaScript。
- `GET /v1/editor/usage-stats` 保留原本 `me` / `all` response 欄位，並新增可選 query：
  - `category`: `all`、`document`、`account`，預設 `all`。
  - `username`: superuser 可指定；非 superuser 會被後端限制為自己。
  - `action`: 操作類型部分比對。
  - `index`: ES index 精準比對。
  - `start_ts` / `end_ts`: ISO 8601 時間範圍。
  - `chart_bucket`: `hour`、`6_hours`、`12_hours`、`day`、`week`、`month`。
- `GET /v1/editor/usage-stats` response 新增 `filtered`：包含 `category`、`stats`、`series`、`chart_bucket`、`chart_bucket_label`、`is_restricted_to_self`。
- `GET /v1/editor/audit-logs` 新增可選 query `action_prefix`，例如 `editor.` 或 `auth.`，用於後端分流文件異動與帳號操作紀錄。

---

## 2026-06-12 Auth 安全回應契約更新

- `POST /v1/auth/login` request / success response shape 不變。
- `POST /v1/auth/login` 對無效帳密與未啟用帳號統一回 HTTP 401，detail 為「帳號或密碼錯誤，或帳號尚未啟用。」；詳細失敗原因僅寫入 audit / login audit。
- `POST /v1/auth/login` 與 `POST /v1/auth/reset-password` 若同一 username + client host 在 auth throttle window 內失敗達門檻，回 HTTP 429，detail 為「登入或密碼重設嘗試次數過多，請稍後再試。」，並帶 `Retry-After` header。
- `POST /v1/auth/reset-password` success response shape 不變；audit event 會額外包含 `success`，失敗 audit event 會包含 `success: false` 與 `reason`。

---

## 2026-06-12 portable_auth_pack Auth 安全契約同步

- `portable_auth_pack` 的 `POST /v1/auth/login` success response shape 不變；無效帳密與未啟用帳號統一回 HTTP 401，detail 為「帳號或密碼錯誤，或帳號尚未啟用。」。
- `portable_auth_pack` 的 `POST /v1/auth/login` 與 `POST /v1/auth/reset-password` 若同一 username + client host 在 throttle window 內失敗達門檻，回 HTTP 429，detail 為「登入或密碼重設嘗試次數過多，請稍後再試。」，並帶 `Retry-After` header。
- 此契約只描述外帶範例包；主系統 API 已於 2026-06-12 Auth 安全回應契約更新記錄。

## 2026-06-12 Auth 四層權限契約更新

- Auth role 正式擴充為四層：`superuser`、`db_operator`、`data_editor`、`data_reader`，權限由低到高遞增；舊 role `user` 只作為相容輸入，會正規化為 `data_editor`。
- `POST /v1/auth/register` 建立的 pending 帳號預設 role 改為 `data_reader`。
- `POST /v1/auth/users/{username}/approve` request body `role` 可為 `superuser`、`db_operator`、`data_editor`、`data_reader`（或 legacy `user`，等同 `data_editor`）；不合法 role 回 HTTP 400。
- `GET /v1/auth/me` response 新增 `role_options`，格式為 `[{"value": role, "label": display_label}]`，供前端下拉選單使用。
- `GET /v1/auth/users` response 新增 `role_options`，並要求 `superuser` 權限；`users[*].role` 會回傳正規化後的新四層 role。
- `PUT /v1/editor/doc`、`DELETE /v1/editor/doc`、`DELETE /v1/editor/docs` 現在需要 `data_editor` 以上權限；`data_reader` 只可查閱資料。
- `POST /v1/excel-to-sql/delete-row` 現在需要 `db_operator` 以上權限；dashboard 查閱 endpoint 仍允許所有 active user。
- `portable_auth_pack` 同步上述 role values、`/v1/auth/me` / `/v1/auth/users` 的 `role_options` response 與 approve role contract。

## 2026-06-12 Usage Stats Audit Event Entries

`GET /v1/editor/usage-stats` 新增 query 與 response 欄位：

- Query：`events_limit`（int，1～500，預設 100），控制回傳套用同一統計篩選條件的 audit event 條目數。
- Response：`filtered.events` 回傳依目前 `category`、`username`、`action`、`index`、`start_ts`、`end_ts` 篩選後的最近 audit event 條目；非 superuser 仍固定限制為目前登入者自己的紀錄。
- Response：`filtered.events_total` 為套用篩選後的總事件數；`filtered.events_limit` 為本次條目上限。

## 2026-06-12 Reject Label Clarification

- `POST /v1/auth/users/{username}/reject` route、request 與 response shape 不變；本次僅釐清前端與文件語意：此操作用於拒絕 pending 申請或停權 active 帳號，帳號資料會保留且既有 token 失效。
- `portable_auth_pack` 同步上述 reject 操作語意說明。

## 2026-06-14 Usage Stats Local Timezone Offset

- `GET /v1/editor/usage-stats` 新增 query：`timezone_offset_minutes`（int，預設 0）。前端會傳入瀏覽器本地時區相對 UTC 的分鐘偏移，用於 `filtered.series` 的 hour / day / week / month 等統計曲線分桶。
- 權限限制不變：非 superuser 仍強制以目前登入帳號作為 `filtered` 篩選對象；superuser 可查詢全體統計與指定帳號。
- Response `filtered.timezone_offset_minutes` 回傳實際套用的偏移值，供前端或除錯確認。

## 2026-06-14 Audit Logs Self Account Access

- `GET /v1/editor/audit-logs` 權限調整：active user 可呼叫此 endpoint，但非 superuser 僅允許 `action_prefix=auth.` 的帳號操作紀錄查詢。
- 非 superuser 傳入的 `username` 會被後端忽略並強制改為目前登入帳號；若嘗試查詢非 `auth.` 類別（例如 `editor.` 文件異動），回 HTTP 403。
- superuser 行為不變，可依 `username`、`action_prefix`、`index`、`id`、`changed_path` 與時間範圍查詢全體 audit logs。

## 2026-06-14 portable_auth_pack Login Audit Self Access

- `portable_auth_pack` 的 `GET /v1/auth/login-audit` 權限調整：active user 可查詢自己的登入稽核，superuser 可查全體或透過 `username` query 篩選指定帳號。
- Response 新增 `is_restricted_to_self`，一般使用者為 `true`；superuser 為 `false`。

## 2026-06-14 帳號操作紀錄統計儀表板 contract

- 主系統 `GET /v1/editor/usage-stats` 既有 `category=account` contract 保持：統計 `auth.*` 帳號操作紀錄，response 的 `filtered.is_restricted_to_self` 指出是否受限於目前登入者；非 superuser 即使送出 `username` 也會被強制改為目前登入帳號。
- `portable_auth_pack` 新增相容 `GET /v1/editor/usage-stats` endpoint，支援 `category=account|all`、`username`、`action`、`chart_bucket`、`events_limit`；資料來源為 `/v1/auth/login-audit` 的 login audit events，回傳 `me`、`filtered`，superuser 額外回傳 `all`。
- `portable_auth_pack` 的此 endpoint 僅提供帳號操作記錄統計；若 category 非 `account` / `all`，回 HTTP 400。

## 2026-06-14 usage-stats username 精準多選篩選

- `GET /v1/editor/usage-stats` 的 `username` query 仍為字串參數，但現在可接受逗號分隔的多個帳號，例如 `username=alice,bob`。
- `username` 篩選語意由原本的 case-insensitive substring match 改為 case-insensitive exact match；若指定 `alice`，不再匹配 `malice` 或 `alice2`。
- 非 superuser 呼叫時仍忽略外部指定 username，固定限定目前登入者。
- 同一 exact-match / comma-list 語意也適用於共用的 audit record filtering helper，因此使用該 helper 的 audit 查詢會避免帳號子字串誤匹配。

## 2026-06-14 Editor static assets

- `GET /static/{filename}`：服務 Editor 頁面允許的靜態資產白名單，包含 `editor.css`、`audit_tools.js`、`editor_core.js`、`editor_form.js`、`editor_auth_nav.js`、`editor_stats.js`、`editor_audit.js`、`editor_documents.js`、`editor_bootstrap.js`。
- Response：檔案存在且在白名單內時回 200 與對應 `text/css` 或 `application/javascript`；未知檔名或檔案不存在時回 404。

## 2026-06-14 Editor router backend split

- 本次僅拆分後端 router 檔案職責，未新增、移除或變更 API path、request 格式或 response 格式。
- `/v1/auth/*` 仍由主 app include `api.routers.editor.router` 後提供；實作檔移至 `api/routers/editor_auth.py`。
- `GET /v1/editor/usage-stats` 與 `GET /v1/editor/audit-logs` contract 不變；實作檔移至 `api/routers/editor_usage.py`。

## 2026-06-14 portable_auth_pack router backend split

- 本次僅拆分 `portable_auth_pack` router 實作檔，未新增、移除或變更 API path、request 格式或 response 格式。
- 外部導入仍使用 `from fastapi_auth_pack import router` 後 `app.include_router(router)`；`/v1/auth/*`、`GET /v1/auth/login-audit` 與 portable `GET /v1/editor/usage-stats` contract 不變。

## 2026-06-14 Auth 註冊防列舉、IP 稽核與註冊節流

- 主系統與 `portable_auth_pack` 的 `POST /v1/auth/register` 對「新帳號申請成功」與「帳號已存在」改回相同 HTTP 200 response：`{"message": "若資料符合申請條件，帳號申請已送出；請等待系統管理員審核。"}`，避免公開 response 直接揭露帳號是否存在；真正的 `duplicate_username` 只寫入內部 audit / login audit。
- `POST /v1/auth/register` 對格式錯誤或密碼長度不足仍回 HTTP 400，因這類錯誤不代表帳號存在性。
- `POST /v1/auth/register` 新增 process-local per-IP 節流：同一 `client_host` 在現有 auth throttle window 內達門檻後，後續註冊嘗試回 HTTP 429，detail 為「嘗試次數過多，請稍後再試。」並帶 `Retry-After` header。
- 主系統帳號操作 audit event（註冊、登入、登出、變更密碼、忘記密碼、reset-password、核准、拒絕／停權、刪除、發 reset token、superuser 重設密碼）新增 `client_host` 欄位，供資安檢核追蹤來源 IP / client host。
- `portable_auth_pack` 的註冊、登入與註冊節流事件會在 login audit 中保留 `client_host` / `user_agent`；註冊事件的內部 reason 使用 `registered`、`register_duplicate_username`、`register_invalid_request`、`register_rate_limited`。

## 2026-06-14 Usage Stats client_host 統計

- 主系統 `GET /v1/editor/usage-stats` 的 `me`、`all`（superuser only）與 `filtered.stats` 現在包含 `by_client_host`，格式為 `{client_host: count}`；缺少 `client_host` 的歷史 event 會歸入 `"-"`。
- `filtered.events[*]` 保留既有 audit event shape，若事件有 `client_host` / `user_agent`，前端帳號操作紀錄與統計事件清單會直接顯示；API 不會為歷史事件補假 IP。
- `portable_auth_pack` 相容 `GET /v1/editor/usage-stats` 的 stats response 同步新增 `by_client_host`，供帳號操作統計儀表板顯示 IP 數。

## 2026-06-14 Usage Stats client_host 篩選

- 主系統 `GET /v1/editor/usage-stats` 新增 `client_host` query，可接受單一 IP / client host 或逗號分隔多個值，例如 `client_host=10.0.0.1,10.0.0.2`；比對語意為 case-insensitive exact match，缺少 `client_host` 的歷史 event 可用 `-` 篩選。
- 主系統 `GET /v1/editor/audit-logs` 同步支援 `client_host` query；非 superuser 仍只能查自己的 `auth.*` 帳號操作紀錄。
- `portable_auth_pack` 相容 `GET /v1/editor/usage-stats` endpoint 同步支援 `client_host` query，供帳號操作統計儀表板依 IP 多選篩選。

## 2026-06-15 Excel→SQL 使用者匯入記錄 API

- `POST /v1/excel-to-sql/import-records?config=<path>`：`multipart/form-data` 上傳 `file`。需要 `db_operator` 以上權限。Response：`{"record": {...}}`，record 包含 `id`、`original_filename`、`config_path`、`username`、`created_at`、`status`、`file_size`、`preview`、`import_result` 等，不包含內部 `stored_path`。
- `POST /v1/excel-to-sql/import-records/{record_id}/preview`：需要 `db_operator` 以上權限；一般使用者只能操作自己的記錄。Response：`{"record": {...}, "preview": {"total_rows": int, "will_insert": int, "duplicate": int, "failed": int, "sheets": list, "failure_summary": object, "samples": list, "scanned_at": str}}`。
- `POST /v1/excel-to-sql/import-records/{record_id}/confirm`：需要 `db_operator` 以上權限；一般使用者只能操作自己的記錄。Response：`{"record": {...}, "import_result": {"run_id": str, "inserted_rows": int, "duplicate_rows": int, "failed_rows": int, "ok": bool, "failure_summary": object, "imported_at": str}}`。
- `GET /v1/excel-to-sql/import-records`：登入使用者可查；一般使用者只看自己的記錄，superuser 可看全部。Query filters：`config`、`status`、`filename`、`actor`、`start_ts`、`end_ts`。Response：`{"records": [...]}`。
- 匯入記錄不再提供刪除 API；`/v1/excel-to-sql/import-records` 僅保留上傳、查詢、預掃描與確認匯入。

## 2026-06-15 Excel→SQL 匯入作業中心頁面

- `GET /excel-to-sql-import-center`：回傳「Excel 匯入作業中心」靜態頁，供登入使用者進行 Excel 上傳、預掃描、確認匯入 SQL 與匯入記錄管理。
- 既有 `/v1/excel-to-sql/import-records*` 上傳、查詢、預掃描與確認匯入 contract 不變；前端新增顯示 `preview.failure_summary`、`preview.samples`、`import_result.failure_summary` 等既有 response 欄位。
- `GET /excel-to-sql-dashboard` contract 不變，但頁面語意調整為 SQL audit 監控；使用者匯入操作改由 `/excel-to-sql-import-center` 承接。

## 2026-06-16 Auth Storage Configuration

- API route shape 未變更。
- 主系統新增可選環境變數 `SRA_LOGIN_AUDIT_FILE`，用於指定登入稽核 JSON 檔位置；未指定時依 `SRA_AUTH_USERS_FILE` 派生。
- `portable_auth_pack` 新增可選環境變數 `AUTH_LOGIN_AUDIT_FILE`，用於指定登入稽核 JSON 檔位置；未指定時依 `AUTH_USERS_FILE` 派生。

## 2026-06-16 Auth Login Audit Shards

- API route shape 未變更。
- `SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE` 仍是可選設定，但語意調整為 login audit manifest path；實際登入事件依月份寫入同旁路徑的 `<audit_file>.d/login_audit-YYYYMM.json` shards。

## 2026-06-18 Excel→SQL dashboard recent audit username filter

- `GET /v1/excel-to-sql/dashboard` 新增可重複 query 參數 `username_filter`，用於「最近 audit 事件」與套用目前篩選的統計曲線。
- `username_filter` 以 exact match 比對 audit row payload 的 `audit_actor`，並相容既有刪除 audit payload 的 `actor`。
- Response 新增 `username_options: string[]`，提供前端使用者多選篩選清單；`recent_filters.username` 會回傳已正規化的使用者篩選值。

## 2026-06-18 Excel→SQL dashboard recent audit username

- `GET /v1/excel-to-sql/dashboard` 的 `recent[]` 事件物件新增 `username` 欄位，值由 audit `row_payload` 的 `audit_actor` 優先，其次 `actor` 解析而來，與 `username_filter` / `username_options` 使用相同來源。
- 舊 audit rows 若沒有 `audit_actor` 或 `actor`，`recent[].username` 會是空值；這類資料也不會出現在 `username_options`。

## 2026-06-18 ExcelImportAudit username 欄位

- SQL audit table contract 更新：`ExcelImportAudit` 新增 nullable `username NVARCHAR(255)` 欄位；`ensure_audit_table()` 會在既有表缺少此欄位時執行 `ALTER TABLE ... ADD username NVARCHAR(255) NULL`。
- 新寫入的 audit rows 會將使用者資訊寫入 `username` 欄位；來源優先序為 `row_payload.audit_actor`、`row_payload.audit_user`、`row_payload.actor`。
- `GET /v1/excel-to-sql/dashboard` HTTP response shape 不變；`recent[].username` 改為優先使用 SQL `username` 欄，並保留 JSON payload fallback 以相容舊資料。

## 2026-06-22 Vercel Mock Runtime response 標記

- `GET /v1/editor/indexes` response 新增 `mock_mode: bool`，表示目前是否使用 in-memory mock Elasticsearch。
- `GET /v1/editor/search` response 新增 `mock_mode: bool`；mock 啟用時 `warnings[]` 會包含「目前使用 Vercel mock Elasticsearch 測試資料，未連線正式 ES。」。
- `POST /v1/excel-to-sql/import-records` 在 mock runtime 回傳的 `record` 會包含 `mock_mode: true`，且不保存上傳檔到磁碟。
- `POST /v1/excel-to-sql/import-records/{record_id}/preview` 在 mock runtime 回傳的 `preview` 會包含 `mock_mode: true` 與示範統計。
- `POST /v1/excel-to-sql/import-records/{record_id}/confirm` 在 mock runtime 回傳的 `import_result` 會包含 `mock_mode: true` 與示範匯入結果；不連 SQL Server。

## 2026-06-22 Vercel Mock SQL Dashboard contract

- `GET /v1/excel-to-sql/dashboard` 在 mock runtime 不連 SQL Server；response 新增 / 保留 `mock_mode: true`、`warnings[]`，並回傳可檢閱的 `summary`、`daily`、`files`、`destination_table_options`、`username_options`、`recent` 與 `recent_paging`。
- `POST /v1/excel-to-sql/delete-row` 在 mock runtime 不刪 SQL Server row；response 包含 `ok: true`、`deleted: false`、`mock_mode: true` 與說明訊息。

## 2026-06-22 Vercel Deployment routing

- Vercel 部署透過 `api/index.py` 匯出同一個 `api.main.app` FastAPI instance；HTTP API path / request / response contract 不因 Vercel entrypoint 改變。
- `vercel.json` 使用 rewrite 將 `/(.*)` 導向 `/api/index.py`，因此 `/editor`、`/excel-to-sql-dashboard`、`/excel-to-sql-import-center` 與 `/v1/*` 在 Vercel 上仍由既有 FastAPI router 處理。

## 2026-06-22 Portable auth pack Vercel mock preview endpoints

- `GET /v1/auth/vercel-preview-login-enabled`（portable auth pack）：回傳 `{ "enabled": bool, "username": "portable_mock_reader" | null }`；由 `AUTH_VERCEL_MOCK_MODE` 控制，預設 `auto` 僅在 Vercel/NOW 環境啟用。
- `POST /v1/auth/vercel-preview-login`（portable auth pack）：僅在 mock preview enabled 時建立 / 更新 process-local `portable_mock_reader` data_reader 帳號並回傳 `{ access_token, token_type, user }`；disabled 時回 404。此帳號不具備 superuser 權限且不使用固定密碼。

## 2026-06-23 Vercel mock preview login hardening contract

- `GET /v1/auth/vercel-preview-login-enabled` response 新增 `secret_required: bool`，表示 mock preview login 是否需要額外 header secret。
- `POST /v1/auth/vercel-preview-login` 在設定 `SRA_VERCEL_PREVIEW_LOGIN_SECRET` 時需要 request header `X-SRA-Preview-Login-Secret`；缺少或錯誤時回 HTTP 403；多次失敗會依既有 auth throttle window 回 HTTP 429。
- `POST /v1/auth/vercel-preview-login` success response 的 `user` 物件新增 `mock_preview: true`；token payload 同步帶 `mock_preview` claim。
- `SRA_VERCEL_MOCK_MODE=auto` 在 production-like 環境（`APP_ENV` / `ENV` / `PY_ENV` 或 `VERCEL_ENV` 為 `prod` / `production`）不啟用 mock preview login；需明確 `force` 才會覆寫。
- 主系統 mock preview token 只允許讀取 mock Elasticsearch；若 backend 正在使用真實 ES，Editor ES 讀取 endpoint 回 HTTP 403。
- `portable_auth_pack` 同步上述 preview login response/header/throttle/production auto-disabled 契約，環境變數名稱為 `AUTH_VERCEL_MOCK_MODE` 與 `AUTH_VERCEL_PREVIEW_LOGIN_SECRET`。

## 2026-06-23 Vercel mock mode env reliance clarification

- HTTP API contract 不變。
- `SRA_VERCEL_MOCK_MODE` 不再由 `vercel.json` 設定；未設定時仍由程式預設為 `auto`。
- Production preview-login 防護不依賴使用者手動設定 `SRA_VERCEL_MOCK_MODE=never`，而是透過 Vercel 內建 `VERCEL_ENV=production` 或 `APP_ENV` / `ENV` / `PY_ENV` production-like 判斷自動停用。

## 2026-06-23 Restore Vercel mock mode env in vercel.json

- HTTP API contract 不變。
- `vercel.json` 重新提供非機密預設環境變數 `SRA_VERCEL_MOCK_MODE=auto`，讓 Vercel preview 預設走 mock-friendly 模式。
- Production 防護仍由 `should_prefer_mock_runtime()` 讀取 `VERCEL_ENV=production` / production-like env 後停用 `auto` mock preview login；因此即使 `vercel.json` 設為 `auto`，production-like 環境仍不會開啟 mock preview login，除非明確設定 force。

## 2026-06-23 Mock response data shape note

- No production API path changed. Mock Elasticsearch responses under Vercel/mock runtime now include richer `multidim_event_json` structures (`Event_Timeline`, `Involved_Parties`, `Person`, `evidence_snippets`) and mock SQL dashboard audit rows include event/person/evidence payload fields for demo realism.

## 2026-06-23 Mock ES demo document expansion

- No production API path changed. Mock Elasticsearch data now includes additional demo documents for UN General Assembly / Ebola / climate summit coverage and a SQL-imported fishing vessel activity, with sensitive source credentials and internal host/path details intentionally omitted.


## 2026-06-25 Editor form-config mapping metadata

- `GET /v1/editor/form-config` response 新增：
  - `mapping_ok: boolean`：是否成功讀取指定 index 的 Elasticsearch mapping metadata。
  - `mapping_field_count: number`：後端從 mapping 擷取到的欄位 metadata 數量。
  - `schema.sections[*].mapping`：若 section path 對應 ES object/nested 欄位，包含 mapping metadata，例如 `{"type": "nested", "has_properties": true}`。
  - `schema.sections[*].fields[*].mapping_path`：表單欄位對應到 ES mapping 的完整 dot path；array section 內相對欄位會展開為 `<section.path>.<field.path>`。
  - `schema.sections[*].fields[*].mapping`：欄位的 ES mapping metadata，例如 `{"type": "date"}` 或 `{"type": "integer"}`。
- `config/editor_form.default.json` 仍負責 UI layout / 顯示欄位；ES mapping metadata 是欄位型別與資料結構的輔助權威來源。

## 2026-06-25 Excel→SQL task config creation API

- 新增 `POST /v1/excel-to-sql/task-configs`，需 `db_operator` 或 `superuser` 權限。
- Request body 用於建立 `config/excel_to_sql/*.json` 任務設定檔，主要欄位包含：
  - `filename`：安全 JSON 檔名，僅允許英數、底線、連字號、句點並以 `.json` 結尾。
  - `task_name`：dashboard 顯示名稱。
  - `db_driver`、`db_server`、`db_database`、`db_trusted_connection`、`db_user`、`db_password`、`db_encrypt`、`db_trust_server_certificate`：SQL Server 連線設定；非 trusted connection 時需提供 user/password。
  - `source_directory`、`file_pattern`、`recursive`、`source_sheet`、`header_row`、`start_row`、`end_row`：Excel 來源設定。
  - `destination_table`、`auto_create_table`、`auto_create_missing_fields`、`default_field_type`、`hash_field`、`hash_field_type`、`create_hash_index`：SQL 目的表與 hash 欄位設定。
  - `mappings`：至少一筆 `{source_column, dest_field, dest_field_type, required, match?, value_type?}`。
  - `audit_table`、`overwrite` 等進階設定。
- Response：`{"task": {"config_path": "config/excel_to_sql/<filename>", "name": "<task_name>", "created_by": "<username>"}}`。
- 錯誤：檔名或欄位不合法回 400；同名檔案且未 `overwrite` 回 409；未達資料庫管理權限回 403。

### 2026-06-25 Excel→SQL task config creation update

- `filename` now supports nested relative paths under `config/excel_to_sql`, for example `business/monthly_task.json`; absolute paths and `..` segments remain forbidden.
- Request body adds optional `connection_source_config`. When provided, the backend loads that existing task JSON under `config/excel_to_sql` and copies its `db` block into the new task config, allowing business users to create import tasks without seeing or retyping DB server, credentials, encryption, certificate, or ODBC driver settings.
- Direct DB connection fields remain supported for DB managers; when `connection_source_config` is empty and `db_trusted_connection=false`, generated JSON includes `db.user` and `db.password` from the request.
- Missing `connection_source_config` file returns 404; invalid path / missing `db` block returns 400.
- `filename` and `connection_source_config` may be provided either as paths relative to `config/excel_to_sql` or with the `config/excel_to_sql/` prefix; both resolve inside the same root.

### 2026-06-25 Excel→SQL pending task approval update

- `POST /v1/excel-to-sql/task-configs` now creates configs with `dashboard.enabled=false` and `dashboard.status="pending"`; pending configs do not appear in dashboard task discovery and cannot be selected for upload until approved.
- Response includes `task.status` and `task.enabled` so the UI can tell the creator to notify a superuser.
- Added `POST /v1/excel-to-sql/task-configs/approve` requiring `superuser` permission. Request body: `{ "config": "relative/or/config/excel_to_sql/prefixed.json" }`. It sets `dashboard.enabled=true`, `dashboard.status="active"`, and records `dashboard.approved_by`.
- Missing config returns 404; invalid config path or malformed dashboard section returns 400; non-superuser callers receive 403 from auth dependencies.
- UI mapping rows now expose common SQL type options (`NVARCHAR(255)`, `NVARCHAR(MAX)`, `INT`, `BIGINT`, `DECIMAL(18,2)`, `FLOAT`, `DATE`, `DATETIME2`, `BIT`) while still allowing manual input.

### 2026-06-25 Excel→SQL task config superuser review list/status update

- Added `GET /v1/excel-to-sql/task-configs`, requiring `superuser`, to list task JSON files with dashboard metadata for review UI. Response: `{ "tasks": [{ "config_path", "name", "status", "enabled", "created_by", "approved_by" }] }`.
- Added `POST /v1/excel-to-sql/task-configs/status`, requiring `superuser`, with request body `{ "config": "relative/or/config/excel_to_sql/prefixed.json", "enabled": boolean }`. `enabled=true` sets `dashboard.enabled=true` / `dashboard.status="active"`; `enabled=false` sets `dashboard.enabled=false` / `dashboard.status="pending"` and records `dashboard.disabled_by`.
- Existing `POST /v1/excel-to-sql/task-configs/approve` remains as a compatibility alias for enabling a task and still requires `superuser`.
- Non-superuser callers receive 403 for list, approve, and status endpoints; this is the backend security boundary even though the UI hides review controls from non-superusers.

### 2026-06-26 Excel→SQL task config review details

- `GET /v1/excel-to-sql/task-configs` response `tasks[]` now includes `review_summary` and `config_preview` for superuser review.
- `review_summary` groups the generated JSON into `db`, `source`, `destination`, `audit`, `mappings`, `import`, `retry`, and `archive` sections so superusers can inspect Excel→SQL conversion details before enabling a task.
- `config_preview` returns the generated task JSON with sensitive `db.password` masked as `********`; the backend still requires `superuser` for this endpoint.

### 2026-06-26 Excel→SQL dashboard task review summary and composite mappings

- `GET /v1/excel-to-sql/dashboard-tasks` response `tasks[]` now includes `review_summary` so db_operator / superuser users can inspect enabled task Excel→SQL field mappings before uploading.
- `POST /v1/excel-to-sql/task-configs` request body adds optional `composite_mappings: [{ source_columns: string[], dest_field: string, separator?: string, dest_field_type?: string, required?: boolean }]`.
- Composite mappings materialize a new SQL destination field during import by concatenating multiple Excel source columns with `separator`; they participate in auto-create table / missing-field logic like regular mappings.
- View-based composite fields are not yet created automatically by the importer; this release implements the real materialized SQL field path first.

## 2026-06-26 Excel→SQL composite template update

- `POST /v1/excel-to-sql/task-configs` 的 `composite_mappings[]` 仍用於把多個 Excel 來源欄位寫入一個實際 SQL 欄位；物件欄位包含：
  - `source_columns: string[]`：至少兩個 Excel 欄名，會依既有欄名比對流程解析。
  - `dest_field: string`：SQL 欄位安全命名，只允許英文字母、數字與底線且不可用數字開頭；例如應使用 `complete_description`，不要使用 `complete description`。
  - `template?: string`：可選模板。若提供，支援 `{Excel欄名}` placeholder，以每列來源欄位值替換；例如 `日期是{日期}，發生地點是{地點}，當天的敘述是{敘述}`。
  - `separator?: string`：未提供 `template` 時才用於串接來源欄位；預設空白。
  - `dest_field_type?: string`、`required?: boolean`：與一般 mapping 相同。
- `GET /v1/excel-to-sql/dashboard-tasks` 仍只要求已登入使用者，會回傳 active dashboard tasks 的 `review_summary`。因此資料閱讀者 / 資料修改者可在「使用者 Excel 匯入操作」選擇任務時看到欄位轉換摘要；真正上傳、預掃描與確認匯入仍由各操作 API 自行執行權限檢查。

## 2026-06-26 Excel→SQL 任務設定檔管理權限

- `GET /v1/excel-to-sql/task-configs?scope=mine|all`
  - Auth：`db_operator` / `superuser`。
  - 預設 `scope=mine`：只回傳目前登入使用者建立的任務設定檔。
  - `scope=all`：僅 `superuser` 可用，回傳所有 dashboard 任務設定檔供審核。
  - Response：`{"tasks": [{"config_path", "name", "status", "enabled", "created_by", "approved_by", "review_summary", "config_preview"}]}`。
- `POST /v1/excel-to-sql/task-configs/status`
  - Auth：`db_operator` / `superuser`。
  - Request：`{"config": "config/excel_to_sql/example.json", "enabled": false}`。
  - `db_operator` 只能將自己建立的任務停用；啟用任務仍僅限 `superuser`。
- `DELETE /v1/excel-to-sql/task-configs`
  - Auth：`db_operator` / `superuser`。
  - Request：`{"config": "config/excel_to_sql/example.json"}`。
  - `db_operator` 只能刪除自己建立的任務；`superuser` 可刪除任務設定檔。
  - Response：`{"task": {"config_path", "deleted", "created_by", "deleted_by"}}`。

## 2026-06-26 Excel→SQL batch SQL row deletion API

- Added `POST /v1/excel-to-sql/delete-rows`, requiring `db_operator` permission.
- Request body: `{ "config": "config/excel_to_sql/task.json", "hash_values": ["..."], "reason": "復原錯誤 Excel 匯入" }`; `hash_values` accepts 1-500 values and is de-duplicated server-side.
- Response body: `{ "ok": true, "processed": number, "deleted_rows": number, "report": { "generated_at", "actor", "config_path", "reason", "rows": [...] } }`.
- Each report row includes at least `deleted_at`, `actor`, `config_path`, `hash_value`, `status`, `deleted_rows`, `destination_table`, `hash_field`, `reason`, optional `error`, and `deleted_row_payloads` captured before SQL deletion.
- The existing single-row `POST /v1/excel-to-sql/delete-row` remains supported; its response now also includes `deleted_row_payloads` for report generation.

## 2026-06-26 Excel→SQL task config DB summary redaction

- `GET /v1/excel-to-sql/task-configs` response shape 不變，但 `tasks[*].review_summary.db` 與 `tasks[*].config_preview.db` 的敏感值顯示策略更嚴格：`server`、`database`、`user`、`password` 若存在會以 `********` 回傳。
- `driver`、`trusted_connection`、`encrypt`、`trust_server_certificate` 仍保留於 summary / preview，供前端在使用既有連線來源時提示與帶入較不敏感設定。
- `POST /v1/excel-to-sql/task-configs` request / response shape 不變；當 `connection_source_config` 有值時，後端仍讀取套用該 JSON 的真實 db 區塊，前端不需要也不應送出來源設定檔的 Server / DB / user / password。

## 2026-06-26 Excel→SQL enabled task status normalization

- `GET /v1/excel-to-sql/dashboard-tasks` response 的任務物件新增 / 明確回傳 `enabled: true` 與 `status: "active"`，因該 endpoint 只列出 `dashboard.enabled=true`、可用於上傳導入的任務。
- `GET /v1/excel-to-sql/task-configs` response shape 不變；當設定檔 `dashboard.enabled=true` 時，`tasks[*].status` 以 `active` 顯示，即使舊版或手動上傳 JSON 仍留有 `dashboard.status=pending`。

## 2026-06-29 Editor login throttle unlock contract

- `POST /v1/auth/login` throttle 行為維持同一 `username + client_host` 在 15 分鐘觀察窗內失敗達 5 次後暫停 5 分鐘；HTTP 429 response 仍帶 `Retry-After` header，`detail` 會包含約略剩餘時間，例如「嘗試次數過多，請稍後再試（剩餘約 5 分鐘）。」。
- `POST /v1/auth/users/{username}/unlock-login` 需要 `superuser` 權限；會清除該 username 目前 process-local 記憶體中的 login throttle records，response 為 `{username, cleared, message}`，並寫入 `auth.login_unlocked` audit event。


## 2026-06-29 portable_auth_pack login throttle unlock contract

- `portable_auth_pack` 同步主系統 login throttle UX：HTTP 429 `detail` 會包含約略剩餘時間，並保留 `Retry-After` header。
- `portable_auth_pack` 新增 `POST /v1/auth/users/{username}/unlock-login`，需要 `superuser` 權限，清除該 username 目前 process-local 記憶體中的 login throttle records，response 為 `{username, cleared, message}`。
- `portable_auth_pack/static/login_admin_minimal.html` 範例頁同步登入輸入提示與「解除登入冷卻」superuser 操作。

## 2026-06-29 Excel→SQL composite mapping match preservation

- `POST /v1/excel-to-sql/task-configs` 的 `composite_mappings[].match` 可作為拼裝來源欄位未列在一般 `mappings[]` 時的 fallback 比對方式；支援 `exact`、`smart`、`normalized`、`prefix`、`contains`。
- 一般 `mappings[]` 來源欄位若未指定 `match`，建立出的 `compose.source_matches` 會保留 runtime 預設 `smart`，避免把可由智慧比對解析的 Excel 標題強制降為完全相等比對。

## 2026-07-01 Excel→SQL delete-row response / audit metadata 補充

- `POST /v1/excel-to-sql/delete-row` 仍以 `{ config, hash_value, reason }` 呼叫；成功 response 補充 `config_path`，讓前端顯示實際用於定位 SQL destination table 的來源任務設定檔。
- Excel→SQL 匯入寫入 audit row 的 `row_payload` 會補上 `config_path` 與 `source_config_path`（若流程已提供 config path），供 dashboard 在單筆 / 批次刪除 SQL 列時使用 audit row 自身來源任務，而不是依賴頁面上方目前選取的任務。
- 刪除 audit 的 `message` / `row_payload` 會包含 `config_path` 與 `destination_table`，方便使用者在最近 audit 事件內追溯刪除操作實際來源任務檔與目的 table。

## 2026-07-01 Excel→SQL dashboard operational metadata 權限邊界修正

- `GET /v1/excel-to-sql/dashboard` 對 `db_operator` 以上角色回傳 `can_delete=true`，recent row 可包含 top-level `source_config_path` 供刪除 SQL 列時定位來源任務；此值由 server-side user import registry 依 `source_file` 對應，不寫入通用 `row_payload`。
- 對低於 `db_operator` 的角色，dashboard response 會回傳 `can_delete=false`，並移除操作型 metadata：`destination_table_options` 置空、recent row 不提供 `destination_table` 與 `source_config_path`。前端應依 `can_delete` 隱藏刪除 checkbox 與「刪除SQL列」操作。
- Excel→SQL audit `row_payload` 不應承載任務設定檔路徑或 SQL table 等操作型資訊；payload 保留資料內容與 actor 等必要稽核資訊，避免資料閱讀者透過 payload 看到 SQL 實體結構。

## 2026-07-01 Excel→SQL dashboard 操作來源 UI 補充

- `GET /v1/excel-to-sql/dashboard` 的 `can_delete=true` response 既有 top-level `recent[*].source_config_path` 與 `recent[*].destination_table` 會供前端「操作來源」欄顯示，方便 `db_operator` 以上角色快速確認 row 來源任務與 SQL table。
- `can_delete=false` response 仍不提供上述操作型 metadata；前端操作來源欄不得顯示敏感任務路徑或 SQL table。

## 2026-07-01 Excel→SQL dashboard selected-task audit scope

- `GET /v1/excel-to-sql/dashboard?config=...` 現在會以 `config` 指定的匯入任務建立 audit source scope，讓 summary / chart / files / recent rows / options 預設只反映選定任務相關 audit rows。
- Source scope 來源包含：user import registry 中 `config_path` 等於目前 config 的 `stored_path`、設定檔 `source.excel_path`、以及 `source.directory` / `source.excel_dir` 下的檔案前綴。若設定檔缺少可推導來源，會維持既有 audit table 查詢行為。
- 目的地 table 篩選與使用者篩選是在 selected-task scope 內再套用，避免不同任務共用 audit table 時互相混入查詢結果。

## 2026-07-01 SQL 來源資料編輯器 API

- `GET /excel-to-sql-source-editor`：回傳 SQL 來源資料編輯器靜態頁。
- `GET /v1/excel-to-sql/source-rows`
  - 權限：登入且啟用的 `data_reader` 以上可唯讀；`data_editor` 以上 response 會標示 `can_edit=true` / `can_delete=true`；`db_operator` 以上另有 `can_batch_delete=true`。
  - Query：`config`（Excel→SQL 任務設定檔路徑）、`q`、`source_file_filter`（audit `source_file`）、`import_start_ts` / `import_end_ts`（audit `processed_at` ISO 8601）、`username_filter`、`row_no_filter`、`hash_value_filter`、`payload_filter`、`page`、`limit`（1～200）。
  - 行為：只依任務設定檔的 `destination.table` 查詢資料列，不接受任意 SQL 或任意 table name；匯入使用者、匯入執行時間與來源 Excel 由 audit table 依 hash 補回 `_import_username`、`_imported_at`、`_source_excel` 虛擬欄位。
  - Response：`ok`、`config_path`、`destination_table`、`hash_field`、`columns`、`editable_columns`、`username_options`、`rows`、`total`、`page`、`limit`、`has_more`、`can_edit`、`can_delete`、`can_batch_delete`。
- `PATCH /v1/excel-to-sql/source-row`
  - 權限：`data_editor` 以上。
  - Request：`config`、`hash_value`、`changes`、`reason`。
  - 行為：以任務設定檔的 `destination.hash_field` 定位單列；禁止修改 hash 欄位與常見系統/虛擬欄位；必須填寫 `reason`；成功後若 audit table 存在，寫入 `sql_source_editor.update_row` audit payload（含 before / after / changes）。
  - Response：`ok`、`status`、`updated_rows`、`hash_value`、`config_path`、`destination_table`、`hash_field`、`blocked_columns`、`row`。
- `POST /v1/excel-to-sql/delete-row`
  - 權限：`data_editor` 以上；後端同樣確認 `config` 在已啟用任務白名單內。
  - Request / response 沿用既有 `{config, hash_value, reason}` 與刪除結果；SQL 來源資料編輯器前端會要求原因與二次確認。
- `POST /v1/excel-to-sql/delete-rows` 仍需 `db_operator` 以上，用於批次刪除，前端需採高風險確認文字 + 最後確認。

### 2026-07-01 SQL 來源資料編輯器白名單補充

- `GET /v1/excel-to-sql/source-rows` 與 `PATCH /v1/excel-to-sql/source-row` 新增/使用 `config_dir` query（預設 `config/excel_to_sql`）作為已啟用任務清單來源。
- 後端會先確認 `config` 存在於 `discover_dashboard_tasks(config_dir)` 回傳的已啟用任務清單；未列入清單時回傳 403，不會讀取任意 config path 或任意 SQL table。
- SQL 來源資料編輯器 audit 寫入同一個 Excel→SQL audit table schema；人工編輯事件以 `status/action = sql_source_editor.update_row` 與 `source_file = sql-source-editor` 區分於一般匯入列事件；dashboard selected-task audit scope 會納入 `run_id=manual-control` 且 `row_payload.config_path` 等於目前 config 的人工編輯/刪除事件，避免最近 audit 事件出現缺口。
