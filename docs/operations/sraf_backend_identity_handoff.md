# SRAF / OpenWebUI 可移植身分交接｜候選契約

## 目標與邊界

保留 OpenWebUI 原登入、既有 WEBUI_SECRET_KEY 與一般報告路徑。
不要求個別使用者取得或持久儲存 SRAF Token；#505 個人 Token pilot HOLD。
不把私網 IP、任意 HTTP Header、前端提供的使用者名稱或共用服務
API Key 當成個人身分。

候選第一步是獨立、短效、request-bound HMAC assertion。只供未來
可信任管理員安裝的 backend adapter 使用。Logical issuer/audience 是
穩定的安裝識別，不是 IP、Host header、URL 或 OpenWebUI 登入金鑰。
每個 issuer 只配置專用高熵隨機 key（至少 32 bytes；部署時以
restricted secret file/secret manager 注入，不寫 Git 或 UserValves）。
key ID 不可含 assertion 分隔字元「.」，允許兩個 key ID 作輪替；移除舊 key 後拒絕舊 assertion。
持有 key 的 issuer 能代表其明確映射的帳號，故 issuer 是受信任
安全邊界，不是普通 service key。這不是 OIDC 或完整 SSO。

## 本 PR 提供

- sra_api/security/sraf_handoff_assertion.py：HMAC-SHA256 簽章與常數時間驗證。
- 唯一 issuer/audience、外部不可變 subject、chat/message、隨機 nonce、
  30 秒預設/60 秒上限、固定 POST Chat endpoint、精確 HTTP body bytes
  SHA-256；不接受角色、scope、owner 或任意附加欄位。
- 拒絕重複 JSON keys、未知 key、過期、未到時間、跨 audience、修改
  body/method/path。Retry 必須重新簽名；chat/message 不變。
- 合成單元測試。**這個 PR 不安裝 API authentication、nonce DB、
  帳號映射、Pipe 或瀏覽器登入，不可用它當完整登入憑證。**

## 後續實作與強制安全門檻

1. 由管理員顯式映射 (issuer, immutable subject) -> SRAF account +
   account generation，且每次查當前帳號狀態、角色、scope、grant；
   不自動註冊或依姓名/信箱相同就授權。映射變更及撤銷須可稽核。
2. 驗簽後、授權/任何副作用前，以持久原子 nonce claim 防重放，
   跨程序/重啟有效；有容量與清理策略、時鐘偏差處理。驗證重放後拒絕。
   任務 idempotency 獨立，重試用新 nonce 仍只產生同一 Job。
3. 從已登入的 OpenWebUI backend 取得實際 subject/chat/message，不能
   讀 client JSON 假冒。受保護 transport、單一固定目的地、拒絕
   redirect、錯誤不得改走 shared key / 不安全連線。HMAC **不加密**
   request、response，也不能防止攔截者搶先送出同一 assertion。
4. 同主機可評估限定本機通道（loopback/Unix socket，明確 process trust）；
   跨主機應以經驗證 HTTPS、反向代理或其他已獨立驗證的加密通道保護。
   不能僅因 RFC1918 IP 就視為可信，也不允許驗證失敗自動降級。
   不要求改變 OpenWebUI 原對外 TLS：可另行配置 SRAF backend 通道。
5. 正常授權轉換、瀏覽器 status/download 登入衔接仍需獨立設計。
   不把 assertion 放入 URL，也不使用長效 token 作為瀏覽器跳轉。
   一般報告不受交接功能 disabled/invalid 影響；深度提交明確拒絕。
6. 真實 0.13.4 版 OpenWebUI 與跨 host/subnet 端到端驗收、獨立
   Security Review 完成前，不安裝接收端或開啟 pilot。

本契約是具體候選，不宣稱已取代正式登入或完成部署。


## 第二步候選：持久防重放及帳號映射（尚未接入 API）

HandoffReplayStore 必須由操作者明確 initialize；一般驗證使用 SQLite mode=rw，
不可因 DB 不存在而自動建立。單交易內使用 issuer/audience 雜湊、
nonce 雜湊、到期時間、非遞減時鐘 watermark，保證共用同一 DB 的程序
只能消耗一次。容量有限，滿載或 DB 錯誤拒絕，不記錄問題、Token 或帳號。
不同節點不能各用獨立 replay DB；跨主機遷移須停止接受舊 assertion、
等待有效期結束或保留同一 DB，不能在可接受舊簽章時復原舊 DB。

顯式不可變 subject map 以 issuer/audience/subject 指向真實 SRAF 帳號
及 account_created_at，禁止同一安裝對應重複 subject 或共用帳號。
讀取目前 AuthStore active/role，不授予同名者權限、不自動建立使用者。
映射結果只是內部 observation；未建立 AuthPrincipal、JWT、路由、正式
replay DB 配置或瀏覽器登入。最終接收端仍須重新驗證 scope、grant、
帳號 generation、適用 transport 及 OpenWebUI 已登入 context。


## 第三步候選：明確傳輸策略（未接入 adapter 或接收端）

- local_http：只接受 literal 127.0.0.1 或 ::1，不接受 localhost/DNS、RFC1918、
  Docker bridge IP 或 wildcard。僅同一受信任 network namespace 且確認本機
  listener 不對外暴露時適用；不同容器的 loopback 通常不是同一服務。
- verified_https：配置可變 HTTPS origin（DNS 或 IP），系統 CA 或指定 CA 檔，
  嚴格 hostname/SAN 驗證，無 proxy、redirect、重試或不安全 fallback。
  可使用獨立 SRAF HTTPS ingress，不要求變更既有 OpenWebUI 前端 TLS。
- 可信後端 helper 發送精確簽署的 JSON bytes；單一 POST endpoint，
  response <=8 MiB，非 200/非 JSON 拒絕。socket timeout 不是全程 deadline；
  未完成 adapter 的總時限、取消、實際 TLS ingress 及 listener 配置驗證。
- 合成測試實際在 loopback HTTP/TLS listener 交換資料，錯誤 CA、SAN 不匹配、
  redirect 必須失敗。這不是真實部署或完整 API 驗收。
- 接收端尚未安裝；不得把 X-Forwarded-Proto、Host、IP 或由 reverse proxy
  轉送的 loopback client address 當成 TLS 或個人身分證明。須確認真正 ingress
  信任邊界與 header 剝離；其他普通 API 不因本功能改動。


## Chat-only request context 候選（未安裝 HTTP 接收端）

驗證 raw header 的唯一 assertion，拒絕 Authorization/Cookie/其他
session 或 idempotency headers 並禁止 query string；不能回退成一般登入。
經簽章、防重放、顯式 mapping 後，只在可信內部產生限縮 Chat scopes 的
AuthPrincipal（不含 admin 或一般登入 token）。携帶確切 account generation，
在 deep policy 與 scoped session 綁定重新核對；同名重建帳號不繼承舊 context。
session/turn token 由 logical issuer/audience/external subject/chat/message
衍生，重試與輪替保持穩定，跨 chat/subject 不混用。已准入 context 仍需在
實際執行前和後續深度派送前重驗，不能放入 public dependency 或跨 request 使用。
本模組不信任 HTTP header 作為 transport 證明、不安裝 API、不簽發使用者 Token。


## 獨立私有 Chat ingress 候選（未啟動）

提供 build_private_ingress，回傳專用 Uvicorn Config；沒有啟動任何 listener，
也不掛入原本公開 SRAF app。loopback HTTP 綁 literal loopback，跨主機
使用另設的直接 TLS listener（需合法 cert/key），關閉 proxy header 信任、
拒絕 forwarded headers、禁止 query/路由變形及混用一般 credential。
TLS listener 與 OpenWebUI 既有對外 HTTPS 是不同設定。只接單一 POST Chat、
單一文字 user message、非串流 Markdown，不靜默捨棄 system/history/附件；
其他請求拒絕。原公開 Chat bearer 路徑不接受 assertion。
使用相同 SRAF app.state、相同 Agent/普通報告/深度派送，沒有第二組 Worker、
沒有另一份 AuthStore。要求明確 PUBLIC_API_BASE 以免 private Host 污染 Word URL。
執行及回傳前重驗 mapping/generation/role，深度任務保持原 policy。
合成 ASGI + 真 SQLite 驗證，不是實機通道認證。後續須做 operator config、
single-process listener supervision/start/stop、OpenWebUI 實際 adapter、browser
登入銜接、完整跨主機 acceptance 與獨立 Security Review 才可開啟。


## 可移植 receiver operator manifest（候選）

SRAF_HANDOFF_ENABLED 未設定或 0：不讀 manifest、key 或 replay DB。
1 時必須提供 SRAF_HANDOFF_CONFIG_FILE 與明確 PUBLIC_API_BASE；
目前只有 local preflight 讀取，**尚未掛入正式 lifespan 或啟動 listener**。
範例（全部為合成示例，不能當成實機帳號/金鑰）：

```json
{
  "schema": "sraf_handoff_receiver_v1",
  "issuer": "webui-installation",
  "audience": "sraf-installation",
  "keys": [{"id": "current", "secret_file": "issuer.key"}],
  "bindings": [{"external_subject": "external-id", "owner_id": "sraf-user",
                "account_created_at": "actual-account-generation"}],
  "replay_db": "replay.sqlite",
  "replay_max_active": 10000,
  "listener": {"mode": "local_http", "bind_host": "127.0.0.1", "port": 19002}
}
```

相對路徑以 manifest 所在資料夾為準（可在不同主機以同樣資料夾結構部署）。
signing key 檔是 32–128 bytes 隨機資料的 unpadded base64url，POSIX 需
service-only 0600/0400；其他 OS 使用受限 ACL。金鑰不寫 JSON、環境值、
Git、UserValves 或 URL。verified_https listener 額外提供 cert_file/key_file，
本地檢查 cert/key 配對，不代表 CA/SAN 或現場通訊驗證。
replay DB 需既存且 schema/primary-key/index 正確，不能自動重建。

```bash
# 僅首次明確初始化新 DB（已存在即拒絕；不可用作修復/重置）
python -B tools/sraf_handoff_preflight.py --initialize-replay
# 本地唯讀 configuration/schema 檢查
python -B tools/sraf_handoff_preflight.py --check
```

INITIALIZED/exit 0 僅指新 DB 建立成功。PASS_PARTIAL/exit 2 只指本地設定
與 replay schema，尚未驗證帳號映射、TLS、listener、OpenWebUI、ES/LLM 或 Word。
遷移需先停止接受舊 assertion、保存一致且最新的 replay DB/identity mapping，
或停用舊 key 並等待所有舊 assertion 過期；不得用舊 backup 重置防重放。
本 PR 不讀取現場設定、不啟動任何服務、不產生正式金鑰。


## 私有 listener 生命週期（候選；預設不啟用）

正式啟動時只支援 `python -m api.run_api --port <public-port>` 的單程序
launcher。實際 public port 由 launcher 傳入，不由另一個易誤填的 env 指定；
私有 port 與公開 port 相同時拒絕，直接 uvicorn / serverless / 多 worker
啟動不建立私有 listener。SRAF_HANDOFF_ENABLED 未設或 0 時不讀 manifest
亦不建立 socket。顯式啟用且設定合法時，原 Worker 啟動後才在同一 event
loop 啟動獨立 Uvicorn server；無自己的 signal handlers、proxy trust 或
Worker。原 API 保留其原有 Port 和路由。配置錯誤、port 已被佔用或
私有 listener 啟動失敗，記錄固定狀態並維持原 API；不改用其他 port、
HTTP 或 shared key。無自動重啟。未知核心錯誤仍由原 startup 規則處理。

關閉時先停止私有接收新任務並 drain 已准入的呼叫，再關閉共享 Worker。
同步 Agent 執行不保證可立即取消，graceful stop 可能需要等待；不要在
仍執行時搬動 replay DB 或啟動第二個程序。RUNNING 只證明本機 socket
server 已啟動，不是 TLS/遠端/實機 ES 或完整報告驗收。
此候選有實際 loopback socket 測試；尚未實機部署或獨立 Security Review。


## OpenWebUI 0.13.4 backend Pipe 候選

依 upstream tag v0.13.4 的 functions.py、main.py、models/users.py、
models/chats.py、models/chat_messages.py、utils/plugin.py 核對 async
API 與保留參數。版本不符直接拒絕，不宣稱已在安裝的容器驗證。
管理員在 SRAF checkout 執行：
```bash
python tools/build_sraf_openwebui_backend_pipe.py --output sraf_backend_pipe_bundle.py
```
輸出單一可匯入 Function 的檔案，簽章/transport 取自同一份 canonical
SRAF 程式碼，不複製整套 SRAF 安裝進 OpenWebUI。預設 ENABLED=False。
不需要 UserValves、個人 Token、WEBUI_SECRET_KEY 修改或 Valve 加密。
OpenWebUI 管理員需掛載受限 sender manifest 與獨立 issuer key，設定
SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE 為容器內絕對路徑。
sender manifest 示例（非正式部署值）：
```json
{
  "schema": "sraf_openwebui_sender_v1",
  "issuer": "webui-installation",
  "audience": "sraf-installation",
  "key_id": "current",
  "secret_file": "issuer.key",
  "transport": {
    "mode": "verified_https",
    "origin": "https://sraf-backend.example.test:19002",
    "ca_file": "receiver-ca.pem",
    "timeout_seconds": 300
  }
}
```
相對檔案以 manifest 目錄解析。issuer/audience/key ID 與 receiver 一致，
key 為受限檔案，跨主機用 verified_https；同 network namespace 可顯式
local_http。絕不接受 user valve/body/metadata 選擇目的地或憑證。
只接受真正已儲存、owner-private、root user 文字與尚未完成的
assistant row：查 live Users、Chats、ChatMessages normalized rows，
檢查 account、chat、parent、model、完整原文、角色；不信任 raw metadata。
拒絕未儲存／臨時聊天、背景任務、history/system、工具／附件及不明版本；
不將歷史與系統提示剝除後假裝相容。實際新 chat 是否有額外 system/features
需用 0.13.4 安裝版驗收，現有普通模型不受影響。
逾時不是保證取消，可能仍在後端執行；不自動重試、不退回 shared key。
候選合成 upstream row fixtures + 真 socket/HMAC 測試，未安裝 Function、
未配置正式 key 或容器、未完成瀏覽器登入銜接或實機 Security Review。


## 自動深度派送的 scoped-turn fence（候選）

自動深度派送只接受已驗證 account-generation-scoped session（私有
handoff 或已登入的 scoped Chat header），不接受舊 raw session。
一般 Chat/Word 行為不變；legacy Chat 不自動建立深度 Job。
Idempotency key 的 hash 增加 scoped session 與 domain version；
同帳號不同 chat 即使 message token 相同也不能讀取/沿用彼此的 Job。
ordinary receipt 的 session_id 必須與 admission context 完全一致。
既有舊 hash 的 Job 保留並可由本人歷史清單及進度頁存取，
不會嘗試用不明 legacy session 自動認領或重新遷移舊 Job；
若以新版重送舊訊息，需先核對是否已有歷史任務。深度顯式 API 不變。


## Sender 部署前／遷移後唯讀診斷（候選）

在實際 OpenWebUI 容器／sender namespace 內執行新生成的單檔 bundle：
```bash
python sraf_backend_pipe_bundle.py --check-config
python sraf_backend_pipe_bundle.py --probe-transport
```
第一條只讀 sender manifest、受限 key 與 CA 路徑，不連線。
第二條對同一 operator origin 執行 GET /v1/chat/completions，無 body、
assertion、Token、帳號或問題，不提交 Chat 或 Job；只觀察 405 Allow: POST。
HTTPS 使用與正式 sender 同一直接 CA/hostname 驗證實作，不使用 proxy、
redirect 或降級。socket timeout 5 秒（不是 DNS / 全程硬 deadline）。
只輸出固定分類、不顯示網址、路徑、key 或 upstream response。
PASS_PARTIAL / exit 2 不代表實際私有 listener 身分、帳號映射、金鑰配對、
OpenWebUI API 版本或報告成功。普通 Chat port 亦可能回 405；務必對照
receiver manifest 的私有 port 與 topology，不能只憑此判定上線。
FAIL / exit 1 時先核對配置、DNS/SAN/CA、容器網路與 port，不放寬驗證。
未指定 operation 不執行，回 NOT_TESTED/exit 2。


## 既有 Linux supervisor 相容性（候選）

既有 run_sra_api.sh 預設直接執行 Uvicorn HTTP，不會啟動可選私有 listener。
新增明確 shell-only opt-in，不改原本預設或 .env.local 解析：

```bash
# 只在已核准的維護窗口，所有執行中工作已排空，並完成部署前檢查後。
SRAF_HANDOFF_SUPERVISED_LAUNCH=1 bash run_sra_api.sh
```

使用同一 supervisor、Port、PID 身分、Schedule/Handoff Worker 與 log，
只把 API child 改成 `python -m api.run_api --public --http --port "$PORT"`。
--http 保留原本公開 HTTP listener；不改獨立私有 listener TLS。
SRAF_HANDOFF_ENABLED=1 仍由實際 Python runtime config 控制；
shell flag 本身不開啟 listener。非 0/1 在 bootstrap/lock 前拒絕。
不要將 supervisor 與另一個手動 api.run_api 程序一起啟動。
既有公開 HTTP 不自動升級也不代表可以在不受保護的跨主機通道傳送登入資訊。
注意 supervisor 原本具有有限 SIGTERM 後 SIGKILL 時限（預設 10 秒）；
停機前須先停止新提交、排空所有 in-flight 呼叫與 running jobs。
不要在仍執行工作時為遷移強制 restart。無法排空先停止本次遷移。
正式環境未變更；本 PR 的測試為實際 shell spawn 片段及 Python launcher
參數契約（stub child/uvicorn），不是完整私有 Linux supervisor 實測。


## Admin manifest path and pilot runbook (candidate)
- Pipe admin Valve CONFIG_FILE stores only an absolute local path; no UserValves or key. Existing env path remains supported; two paths must resolve to the same manifest. Standalone diagnostics accept --config-file. Avoid container recreation solely to add an environment variable when an existing restricted persistent mount is suitable. See [staged pilot and rollback runbook](sraf_deep_openwebui_pilot_runbook.md); independent review and real acceptance remain required.
