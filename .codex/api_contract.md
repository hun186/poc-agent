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
