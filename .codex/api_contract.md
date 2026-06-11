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
