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
