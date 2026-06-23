# 技術決策（Technical Decisions）

## Current Summary

- Reset token 以可複製 modal 呈現，不再使用 `alert`；保留 Clipboard API 與 textarea fallback。
- Editor 與 `portable_auth_pack` 維持靜態 HTML / CSS / vanilla JS 架構；主功能入口位於頂端 header，多層導航採桌機 hover、觸控 click 的漸進式互動。
- Editor 工作區由導航狀態切換；文件搜尋 / 編修顯示 ES editor，其餘帳號、審核、audit、統計頁採單欄呈現。
- 文件異動與帳號操作共用 audit 基礎資料，但以前端頁面與 `action_prefix` 分流；一般使用者僅能查自己的 `auth.*` 帳號操作紀錄。
- 共用 `audit_tools.js` 負責 audit chart、分頁與 progressive nav；主系統與 portable auth pack 需同步維護。
- Auth 採四層角色：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 正規化為 `data_editor`。
- Auth security 決策：不存在帳號仍做 dummy password hash timing balance；登入 / reset-password / register 採 process-local throttle；公開登入失敗與註冊回應避免帳號列舉；production 必須設定足夠強度 token secret。
- 長期記憶採 active summary + archive 濃縮模式；`.codex/archive/` 僅追溯時讀取。
- 可視 UI 變更若環境缺少 Playwright / browser runtime，採靜態 UI 測試與 JS 語法檢查替代，並於 known issues 記錄。

## Recent Changes

- 2026-06-14：主系統與 `portable_auth_pack` route / static JS 進行責任導向拆檔，但維持 API path 與既有 contract。
- 2026-06-14：註冊 API 對成功申請與 duplicate username 回相同泛用訊息，duplicate 只留內部 audit；註冊節流以 `client_host` 為 key。
- 2026-06-14：usage stats username 篩選改為 exact match 並支援逗號多選；非 superuser 仍強制限縮為自己。
- 2026-06-14：統計儀表板在個人模式隱藏使用者多選，改顯示 scope note 與 focus-stable tooltip。
- 2026-06-14：帳號操作 audit / usage stats 顯示與統計 `client_host`，讓帳號操作紀錄頁與儀表板可查來源 IP。

## Archived History

- `decisions.md-20260614-125305.md`：歸檔 2026-06-14 前完整 technical decisions，包含 reset token modal、導航架構、工作區切換、共用 audit tools、Auth security、長期記憶濃縮、角色層級與近期拆檔 / 註冊安全決策。

## 2026-06-15 Report Agent 拆檔決策

- 當 Python orchestration 檔案主要因大型 prompt 或純 helper 過長時，優先拆成同 package 的小模組，避免改動既有 public import path 與 runtime behavior。
- `ReportAgent` 與 `ask_with_report()` 的外部入口維持在 `agent/report_agent.py`，降低呼叫端遷移成本；prompt / config / stats helper 則使用相對 import 管理。

## 2026-06-15 Agent Router 拆檔決策

- 當 orchestration 檔案同時包含大型 prompt、分類 helper 與 session / dispatch 流程時，優先將 prompt + router helper 拆到同 package 小模組，讓主入口維持薄 orchestration。
- `answer_with_routing()` 的外部入口維持在 `agent/agent.py`；router 相關 public helper 則以 `agent/routing.py` 作為後續維護位置，並於必要時在 `agent.agent` 保留 re-export 相容。

## 2026-06-15 Auth Store 拆檔決策

- 對正在使用且超過 600 行的 auth store，優先依責任拆出 support / token 小模組，而不是改變 route 或 storage contract。
- 為降低呼叫端遷移風險，`api.services.auth_store` 與 `portable_auth_pack.fastapi_auth_pack.auth_store` 保留原本 public symbols；新模組只承接內部 helper 與 token 實作。

## 2026-06-15 登入失敗記錄決策

- 登入失敗不只寫入持久 audit，也同步輸出 `auth.login.failed` warning log，方便部署環境以 stdout / file log / log aggregator 即時告警。
- 記錄內容限於 username、失敗 reason、client_host、user_agent 與 role/status（若已知）；不得記錄密碼、token 或其他敏感內容。
- 主系統與 `portable_auth_pack` 的登入失敗記錄語意需同步維護，涵蓋 `invalid_credentials`、`inactive_account` 與 `rate_limited`。

## 2026-06-15 Auth Route Logging Helper 拆檔決策

- Auth route 檔應聚焦 HTTP 流程與 response；登入失敗 warning log 這類可重用且安全敏感的記錄格式放到同 package 的 `auth_logging.py` / `editor_auth_logging.py`。
- 新增安全記錄時應避免對整個 route 檔做大規模格式化，降低 review 噪音與 merge 風險。

## 2026-06-15 Excel→SQL Dashboard 拆檔決策

- 對仍在使用且超過 600 行的 dashboard backend，優先抽出無狀態 helper 至同 package 的功能導向小模組，保留原 public function 所在檔案與名稱。
- 避免建立籠統 `dashboard_support.py` 長期累積不同責任；helper 依 config、filter/time/chart、SQL/serialization 三類拆分，讓後續變更有明確落點。
- `delete_imported_sql_row()` 暫時保留在 `dashboard.py`，原因是既有測試與呼叫端會 monkeypatch `dashboard.load_json_config` / `dashboard._connect`；若未來拆出刪除流程，需先設計 dependency injection 或相容 wrapper。

## 2026-06-15 Excel→SQL 使用者匯入決策

- 使用者上傳匯入採「先保存原檔與記錄、再預掃描、最後確認匯入」三階段，避免上傳即寫入 SQL。
- 預掃描必須重用既有 Excel mapping / hash 邏輯與 SQL 去重查詢，確保預估新增 / 重複 / 錯誤列數接近實際匯入，不使用假結果。
- 刪除匯入記錄採軟刪除語意：記錄保留為 `deleted`，原 Excel 移至內部 `deleted/` 備查目錄，而不是直接刪除檔案。
- 記錄 API 不回傳內部檔案路徑，避免使用者透過 UI 看到伺服器 filesystem layout。

## 2026-06-15 Excel→SQL 使用者匯入拆檔決策

- 使用者匯入流程雖仍是單一功能，但 storage、preview scan 與 confirmed import 依賴不同且變更頻率不同，應拆成小模組並由 `user_imports.py` facade 維持對外相容。
- Dashboard 新增的使用者匯入 JS 不繼續塞入既有 HTML inline script；新增功能 JS 以獨立靜態檔管理，避免 dashboard HTML 因後續操作功能擴充而持續膨脹。
- 本次不改 API contract、不改資料存放語意、不重構既有 workbook / dashboard 監控核心，避免在 review 修正中擴大風險。

## 2026-06-15 Excel→SQL 肥大檔案二次拆分決策

- Excel→SQL 功能檔若超過或接近 400 行，優先以 facade / wrapper 保留既有 import path 與 monkeypatch seam，再把明確子責任拆出。
- Workbook 拆分選擇把 row/mapping/hash helper 移到 `workbook_rows.py`，而不是改動 sheet discovery API；既有 `from ...workbook import read_column_mappings` 等呼叫維持可用。
- Dashboard 刪除 SQL row 流程移出 `dashboard.py`，但 wrapper 仍在原檔載入 config 並注入 `_connect` / `_table_exists`，降低既有測試與呼叫端風險。
- Dashboard HTML 不再承載大量 inline JS；監控 dashboard JS 與使用者匯入記錄 JS 分別以獨立靜態檔管理。

## 2026-06-15 Excel 匯入操作與 SQL 監控頁面分流決策

- 使用者上傳 / 預掃描 / 確認匯入 SQL / 匯入記錄管理屬於「操作型流程」，SQL audit dashboard 屬於「監控型查詢」，兩者放同頁會讓日期篩選與操作記錄語意混淆；因此拆成「Excel 匯入作業中心」與「Excel→SQL 匯入 SQL 監控儀表板」。
- 監控儀表板的 `days` 只在未提供 explicit start/end 時生效；前端預設不填起迄，避免永遠帶起迄導致回看天數無法被使用。
- 不在前端硬編特定錯誤原因；imported_with_errors 一律顯示後端真實 `failure_summary` / samples，維持 Real Functionality First。

## 2026-06-15 Excel 匯入記錄儲存拆分決策

- Excel 匯入記錄不再提供 UI 或 API 刪除能力；保留查詢、預掃描與確認匯入作為主要操作。
- 匯入記錄 storage 從「單一 `records.json` 存所有 payload」改為「compact `records.json` ID index + `records/<id>.json` per-record payload」，降低單檔無界成長風險並保留 JSON 檔案式部署簡單性。
- 為兼容既有部署，讀取到舊版 `records.json` 的 `records` array 時採 lazy migration，不需要一次性手動搬遷。

## 2026-06-16 Auth JSON Store 與初始管理者決策

- 登入稽核不可再長期寫入帳號管理 JSON 檔；帳號檔只保存帳號、token denylist 與 reset token 等登入必要狀態，登入稽核使用獨立 audit JSON 檔，降低無界成長與壞檔 blast radius。
- JSON 檔案式 auth store 保留簡單部署優點，但必須有最低限度壞檔保護：atomic replace + 寫入前 `.bak` + JSON decode 失敗時嘗試還原。
- 不採用「第一個註冊帳號自動升為 superuser」；初始管理者必須透過受控 bootstrap 檔、環境變數或 secret manager 注入，避免部署後公開註冊視窗被搶註冊造成最高權限接管。

## 2026-06-16 Login Audit 分片決策

- 單純把登入稽核從帳號檔拆到另一個 JSON 單檔仍會有 audit 單檔無界成長與壞檔風險，因此 audit 應採 manifest + time-based shard。
- 目前以月份作為 shard key（`login_audit-YYYYMM.json`），因為查詢需求主要取最近 N 筆，月份 shard 可保持檔案數量少且避免每日過度碎片化。
- `SRA_LOGIN_AUDIT_FILE` / `AUTH_LOGIN_AUDIT_FILE` 保留為設定入口與 manifest path，避免再次新增目錄型設定造成導入成本；實際事件目錄由 manifest path 派生。

## 2026-06-16 Auth Store 拆檔決策補充

- auth store 不應同時承擔帳號 domain 流程、低階 JSON IO 與 login audit sharding；當檔案接近 500 行且責任明確可分時，優先拆出可測的小 helper module。
- 保留 `AuthStore` public API（`record_login_audit()` / `list_login_audit()` 等）以避免 route 與測試呼叫端改動；內部以 composition 委派給 `JsonFileStore` 與 `LoginAuditStore`。

## 2026-06-16 JSON Store 多版本備份決策

- 單一 `.bak` 只能處理「正式檔壞、上一版仍好」的狀況；為提高檔案式部署的基本韌性，JSON store 每天第一次改寫時保留 1 個 dated historical backup，預設保留 20 天版本。
- 保留 `.bak` 作為最新備份相容入口，同時新增 `.bak.<YYYYMMDD>` 歷史版本；還原順序為最新 `.bak` 優先，再往每日歷史版本回溯。

## 2026-06-16 JSON Store daily backup cadence

- 多版本備份改採「每天第一次改寫時建立歷史備份」，避免高頻登入 audit 寫入造成版本爆量。
- 最新 `.bak` 仍每次寫入前更新，作為最近一次寫入失敗的快速復原點；`.bak.<YYYYMMDD>` 則保存較長時間跨度，預設保留 20 天版本。

## 2026-06-16 JSON Recovery Alerting

- 檔案式 auth store 自動還原不應靜默發生；還原成功、備份不可用與還原失敗都需寫入 application log，並附帶 JSONL recovery record，方便管理者後續追查壞檔時間與使用的備份版本。
- Recovery record 採 sidecar `<file>.recovery.jsonl`，避免寫回正在復原的 JSON 檔而造成遞迴或二次損壞。

## 2026-06-22 Vercel Mock Runtime 決策

- Mock runtime 只用於 Vercel / 唯讀 / 明確強制 mock 的檢閱情境；若正式 ES `ping()` 成功，即使在 Vercel 也優先使用真實 ES，避免 mock 掩蓋可用的正式資料。
- Mock 資料必須透過 `mock_mode` response 欄位與 warning 明確揭露，不以假成功冒充正式 ES / SQL Server 寫入。
- Vercel mock Excel 匯入採 in-memory process-local registry，不嘗試在 serverless 唯讀檔案系統落盤；此功能定位為檢閱流程，不保證跨 instance / cold start 持久化。

## 2026-06-22 Vercel Mock SQL 決策

- Excel→SQL mock 不只涵蓋上傳 / 預掃描 / 確認匯入，也必須涵蓋目的地 SQL Server audit dashboard 與刪除列操作，因使用者檢閱流程會從匯入記錄跳到 SQL audit 查詢。
- Mock delete-row 採 no-op 並明確回傳 `deleted: false`，避免以假刪除冒充正式 SQL Server 異動。

## 2026-06-22 Vercel Config 決策

- Vercel entrypoint 曾採根目錄 `app.py` re-export `api.main.app`；此決策已被後續 `api/app.py` entrypoint 與移除 `functions` override 的設定取代。
- `vercel.json` 只放非機密預設值與必要 rewrite；正式 ES / auth secret 等敏感設定必須由 Vercel Project Settings 注入，不寫入 repo。

## 2026-06-22 Vercel Functions Override Removal

- `vercel.json` 不再設定 `functions` / `maxDuration` pattern，因 Vercel build 曾回報 `app.py` 與 `api/app.py` patterns 無法匹配已發現的 Serverless Functions。
- 曾短暫採用 `api/app.py` 讓 Vercel Python framework preset 自行 discovery；此決策已被 2026-06-22 single function 決策取代，現行設定改用根目錄 `app.py` + explicit `@vercel/python` build / route。

## 2026-06-22 Vercel Bundle Footprint 決策

- Vercel preview deployment 不上傳本地語料、技術文件、logs、runtime state、sample、docs、tests 與 `.codex` 記憶檔；這些內容對 on-premise / 開發有用，但不屬於 Vercel runtime 必需資產。
- 優先用 `.vercelignore` 降低 bundle footprint，而不是啟用較大的 Vercel function limit，因為 preview runtime 已有 mock mode，不應把大型本地資料 workspace 一起打包。

## 2026-06-22 Vercel Single Function 決策

- 因本專案既有 application package 名稱就是 `api/`，若把 Vercel entrypoint 放在 `api/app.py` 並採 zero-config discovery，Vercel 可能把 `api/` 底下多個 Python 模組視為多個 Serverless Functions，超過 Hobby plan 12 functions 限制。
- 曾改採根目錄 `app.py` + explicit `@vercel/python` build / route；此決策已被 2026-06-22 zero-config FastAPI 決策取代，現行保留 root `app.py` 但移除 legacy `builds/routes`。

## 2026-06-22 Vercel Zero-config FastAPI 決策

- 根目錄 `app.py` 保留為唯一 FastAPI ASGI entrypoint，但 `vercel.json` 不再使用 legacy `builds` / `routes` 強制 `@vercel/python`，避免繞過 Vercel FastAPI framework preset 後發生 runtime function crash。
- 現行 Vercel 策略：root `app.py` + zero-config framework discovery + `.vercelignore` 控制 bundle footprint；不使用 `api/app.py`、`functions`、`rewrites`、legacy `builds/routes`。

## 2026-06-22 Portable auth pack Vercel mock preview 決策

- `portable_auth_pack` 範例包同步提供 Vercel mock preview reader login，但使用獨立環境變數 `AUTH_VERCEL_MOCK_MODE`，避免與主系統 `SRA_VERCEL_MOCK_MODE` 混淆。
- mock preview 帳號固定為最低權限 `data_reader` 且無固定密碼；正式部署若不需要 preview shortcut，應設定 `AUTH_VERCEL_MOCK_MODE=never`。
- Vercel/NOW 環境未指定 `AUTH_USERS_FILE` 時，portable auth pack 預設將 runtime auth state 放在 `/tmp/portable-auth-pack/`，避免 serverless read-only filesystem 寫入失敗。

## 2026-06-22 Legacy api path conflict-resolution mirrors

- Legacy `api/routers/` 與 `api/static/` mirror files 僅曾作為短期 GitHub conflict mitigation；衝突解除後應移除，避免 Vercel 或維護者誤認其為 runtime source。
- Runtime import 順序仍以 `sra_api/` 優先，top-level `api/` 只保留 `api.index` Vercel entrypoint 與 compatibility shim。
- `.codex/memory.md` 屬 append-only project memory，設定 `merge=union` 以降低 PR merge conflict；若 union merge 產生重複紀錄，後續 memory compaction 再整理。
