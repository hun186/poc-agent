# SRAF OpenWebUI 個人授權 Pipe（試行候選）

**此程式不會自動安裝或啟用。** 必須先合併、部署 #503/#504 及本 PR 並完成 Linux 驗收。現有 OpenWebUI 連線不需要改動。

## 設計與安裝前條件

- OpenWebUI 版本需實際支援 Pipe 的 UserValves、`__chat_id__`、`__message_id__`、`__task__` 與 Valve 加密。版本尚未在使用者環境確認；不能將 Hosted CI 當成該版本驗收。
- 管理員先確認 OpenWebUI 的 `ENABLE_VALVE_ENCRYPTION=true` 確實啟用，且有長度至少 32 的穩定高熵 `WEBUI_SECRET_KEY`；依官方文件確認資料庫內保存的是加密值，備份及管理員存取受控。**只遮罩 UI 不代表加密，確認前不要輸入任何 token。** 此功能信任 OpenWebUI 管理員及其執行環境，不是對管理員的秘密隔離。
- 只准受管理的 HTTPS SRAF endpoint、正確主機名／憑證及選用的 CA 檔案；不關閉 TLS 驗證、不跟隨 redirect、不讀取代理環境、不使用 HTTP。原有 HTTP 私網若沒有適當 TLS 入口，先保留現有一般模式，禁止將個人 token 透過明文傳輸。
- 由管理員將本目錄的 `sraf_pipe.py` 匯入 OpenWebUI Functions，檢查程式碼，配置 `SRAF_API_ROOT`（不含 /v1）、必要時 `SRAF_CA_FILE`（OpenWebUI 主機上的 PEM CA 路徑），才明確開啟 ENABLED。限制 Function 使用權限。
- 每位使用者以既有 SRAF 登入取得自己的短效 access token（既有受信任登入 API `POST /v1/auth/login` 回傳 access_token）；只輸入自己的加密 UserValves 密碼遮罩欄位。不要將 token、密碼或 CA 內容貼進對話、issue、命令列參數、共用 Valves 或記錄。不要使用 SRAF service key、OpenWebUI 本身 JWT、使用者名稱或其他人的 token。
- Token 到期要透過既有 SRAF 登入更新；不保存密碼、不自行延長 SRAF token 效期、不新增長效 key。自動登入／SSO 需要獨立信任與授權設計，這個版本未實作。

## 實際路徑

Pipe 首先向已設定的 HTTPS SRAF origin 查詢 `GET /v1/sraf/openwebui/capabilities`，必須有本人授權且協定完全吻合，才送出問題。每次 POST 使用個人 bearer 與 `X-SRAF-OpenWebUI-Chat-Id`；SRAF 端自行導出帳號世代隔離的 session。一般純文字新對話且有訊息 ID 時，加入由 chat ID + message ID 導出的穩定 Idempotency-Key。內部 task、多輪／system 訊息或缺 message ID 不派送新的深度任務；聊天本身仍遵守原有 API。缺 chat ID 或不支援的檔案／工具／多媒體輸入明確拒絕。完整原始文字消息保留，不刪除 system/history 來強迫匹配。

非串流回傳保留 SRAF 原始 JSON（含 context/citations）；串流要求僅傳回真正已完成的 Markdown，由 OpenWebUI 包裝為一段，不製造假的輪次提示或 heartbeat。保留一般 Word 與後端真的接受的深度 Job 入口。

## Linux 最終驗收（未執行）

1. 固定 OpenWebUI 版本與反向代理 TLS；檢查 Valve 加密及權限，確認舊 SRAF 不通過 capability probe。
2. 個人帳號 A/B 使用相同 chat ID，確認 session 與 Job 不互通；舊帳號停用／重建、token 過期／登出、service key 均不得取得對方 scoped session。
3. 用明確事件日期、單主題問句測試一般 Word 與深度 Job 連結；相同 message ID 重試不增加 Job，另一 message ID 可建立獨立 Job（僅新且可驗證範圍的對話）。
4. 關閉 OpenWebUI，回到 SRAF 狀態頁登入同一帳號；驗證排隊／執行／完成／失敗／Word 與重啟行為。尚未完成不直接提供 Word。
5. 真實 ES/LLM、代理逾時、長任務容量、報告正確性與實際點擊仍需獨立驗收。不要將 synthetic HTTP 測試誤認為部署完成。

## 上游文件（開發時參考）

- https://docs.openwebui.com/features/extensibility/plugin/functions/pipe/
- https://docs.openwebui.com/features/extensibility/plugin/development/reserved-args/
- https://docs.openwebui.com/features/extensibility/plugin/development/valves/
