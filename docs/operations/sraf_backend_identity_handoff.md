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
