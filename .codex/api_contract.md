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
- `DELETE /v1/excel-to-sql/import-records`：需要 `db_operator` 以上權限。Request JSON：`{"record_ids": [str], "reason": str}`。Response：`{"deleted": [str], "skipped": [{"id": str, "reason": str}]}`；被刪除記錄的原 Excel 會移到使用者不可見的 deleted storage。
