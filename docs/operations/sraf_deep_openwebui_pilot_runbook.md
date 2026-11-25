# SRAF 深度報告與 OpenWebUI：分階段試行、遷移及回退手冊

狀態：工程候選操作手冊，不是上線核准。開始啟用前須確認 #413 的實際最新主線、
#519 整合雙 Python CI、#521 supervisor 相容性、本文件所屬 PR、獨立 Security Review
與現場維護許可。任何未通過的 gate 均不得被當作完成。本手冊不要求更動 OpenWebUI
既有登入金鑰、Valve 加密開關或網頁 TLS；不使用 #505 個人 Token 方案。

## 1. 三個入口分開

| 入口 | 選擇原則 |
| --- | --- |
| 深度 ES | SRAF_DEEP_ES_URL；嚴格 CA/SAN；不改既有 ES_URL |
| OpenWebUI 後端 → SRAF 私有 listener | 同一受信任 network namespace 才可 literal loopback HTTP；不同容器/主機使用經驗證 HTTPS |
| 使用者瀏覽器 → SRAF | PUBLIC_API_BASE 為既有可達、受保護的瀏覽器入口；不能用私有 listener 作替代 |

不同 Docker 容器的 127.0.0.1 不是同一服務。私有 listener port 必須不同於公開 API，
先盤點容器網路、實際 port mapping、路由、ACL、防火牆及 SAN；不得從容器名稱推斷
可達性，也不要把臨時 bridge IP 寫死成長期身份。若使用 DNS，需由實際 sender 解析
且與憑證匹配。不要擴大既有暴露範圍或對整個 LAN 無條件開放；不要用 -k、
verify=False、代理 header 或共享 API key 取代驗證。瀏覽器的登入與 signed Word URL
也不可經未受保護的跨主機 HTTP 傳送；現有前端 HTTP 不會被本功能自動改成 HTTPS。

## 2. 停機前唯讀盤點

在 Windows 端取得經審查的 commit，以既有 7z 增量方式送到 Linux。
部署清單只包含核准程式檔；不從 Git bundle 覆寫 .env.local、部署 SQL registry、
AuthStore、API state、Report Job DB/reports、issuer keys、CA 或 replay DB。
Linux 不需 git fetch。核對來源 commit 與實際文件版本，保留可回退的程式版本。

Docker host 以 docker inspect 的明確欄位檢查已存在的容器、port、mount 與 network
（不要直接 dump 完整 inspect、環境值或 secret）。確認 OpenWebUI 已安裝版本，
例如 docker exec open-webui curl -fsS --max-time 5 http://127.0.0.1:8080/api/version。
版本必須是 0.13.4；其他版本不放行。本機 topology 與路徑不應貼到公開 issue。

若同一 ES/CA/namespace 曾獲嚴格 TLS 與 Event/Timeline mapping/date/paging
PASS_PARTIAL，不需要因本功能重發憑證或重測完全相同配置；遷移或 CA/endpoint
改變才重新核對。已知 loopback 可用時可在該 SRAF 容器單次覆寫 ES_URL 執行
scripts/sraf_event_time_readonly.sh。該舊診斷使用自己的預設 CA 路徑，
不是任意 SRAF_DEEP_ES_CA_CERT 或 DNS 配置的驗收工具。不要修改全域 ES_URL。
若 CA 鏈正確但 SAN 不匹配，先選擇與 SAN 一致的入口或由管理員處理憑證。

## 3. 單一試行帳號及模型

由管理員透過既有帳號管理介面/授權 API 確認 OpenWebUI 不可變 user ID 與
SRAF 現有 active 帳號。SRAF 管理員的 GET /v1/auth/users 可取得該帳號
username、created_at、status、role；只讀必要欄位，不複製整個 response，
不要分享 bearer 或其他帳號資訊。mapping 的 account_created_at 必須原樣等於
當前 SRAF created_at，不是自己填入今天日期。禁止同名自動映射或共用帳號。
先給一名既有授權使用者及單一確切索引；不應為試行提升角色。

確認指定的 Ollama 是已核准的本地服務，模型已安裝、context/GPU 資源可用。
SRAF_DEEP_OLLAMA_ENDPOINT 目前需要明確的 private IP 與 port；無雲端 fallback。
模型值必須是實際可用名稱，不能只依範例填寫。初次建議最多 1 個 active deep job。

在本機受限 .env.local 中準備（REPLACE 全是待替換值，不可直接使用）：
~~~dotenv
SRAF_DEEP_REPORT_ENABLED=1
SRAF_DEEP_CHAT_AUTO_ENABLED=1
SRAF_DEEP_STARTUP_FAILURE_POLICY=ordinary_only
SRAF_DEEP_ES_URL=https://REPLACE_ES_SAN:REPLACE_ES_PORT
SRAF_DEEP_MAX_ACTIVE_JOBS=1
SRAF_DEEP_OWNER_GRANTS_JSON='[{"owner_id":"REPLACE","account_created_at":"REPLACE","indexes":["REPLACE"]}]'
SRAF_DEEP_OLLAMA_ENDPOINT=http://REPLACE_PRIVATE_IP:REPLACE_PORT
SRAF_DEEP_PLANNER_MODEL=REPLACE
SRAF_DEEP_SEMANTIC_MODEL=REPLACE
SRAF_DEEP_REPORT_MODEL=REPLACE
SRAF_DEEP_NUM_CTX=REPLACE
PUBLIC_API_BASE=https://REPLACE_BROWSER_ORIGIN
SRAF_HANDOFF_ENABLED=1
SRAF_HANDOFF_CONFIG_FILE=/REPLACE/receiver.json
~~~
ES_CA 若與預設 agent/certs/http_ca.crt 不同才明確配置 SRAF_DEEP_ES_CA_CERT；
原 ES_USERNAME/ES_PASSWORD 仍由既有安全配置提供。模型 context 為 16384–262144
的明確整數；先核對設備與實際模型。只修改此次必要 keys，不刪除原配置。
若 browser 使用已核准的其他受保護通道，PUBLIC_API_BASE 依實際受保護入口；
不以 HTTP 字串本身證明安全。OS environment 優先於 .env.local；注意舊值覆蓋。

## 4. 獨立信任設定：不更動 OpenWebUI 原有登入金鑰

只在批准後準備受限的 receiver/sender 目錄，首次建立一個高熵 issuer key
（至少 32 bytes；base64url 無 padding；POSIX 權限 0600/0400）。
本地管理員可使用以下方式在已建立且只允許服務帳號存取的目錄產生一次；
不輸出 key，不覆寫，勿在 Git checkout 或公開共享目錄執行：
~~~bash
umask 077
python - <<'PY'
import base64, secrets
from pathlib import Path
with Path("issuer.key").open("xb") as out:
    out.write(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=") + b"\n")
PY
~~~
將同一 issuer key 以核准的受保護方式交付 sender；兩端 issuer、audience、key ID 一致。
跨容器使用專用 receiver TLS cert/key 和 sender CA；TLS private key 不交給 sender。
logical issuer/audience 不依 IP/port，遷移時保持不變。不得共享其他安裝的 issuer key。
完整 JSON schemas 見 sraf_backend_identity_handoff.md；receiver listener TLS 需
mode=verified_https、bind_host、port、cert_file、key_file，sender transport
mode=verified_https、origin、timeout_seconds、可選 ca_file。相對路徑以各自
manifest 目錄為準。replay.sqlite 需持久保存、不得用舊備份復原以重置 nonce。

若 OpenWebUI 已有可用的持久掛載（例如其 data volume），在其管理員控制的
受限子目錄內安全準備 sender manifest、issuer key、CA，驗證服務帳號可讀
且不在靜態檔案/使用者上傳或可下載範圍內。新 Pipe 的 admin-only CONFIG_FILE
只儲存容器內絕對路徑，不儲存 key；因此不必只為新增環境變數重建容器。
若已有 SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE，兩者必須解析至同一檔案或只設其中一項。
如果沒有安全可用的既有掛載，先規劃核准的 volume 更新、持久化原有登入秘密與回退，
不要直接 docker compose down/up。檢查實際容器檔案權限，不要輸出原有秘密。

## 5. 分階段快檢與啟動

先在 SRAF checkout 使用準備好的有效配置執行：
~~~bash
python -B tools/sraf_deep_local_preflight.py --check --require-auto
# 只在全新 replay DB 尚未建立時才明確執行一次：
python -B tools/sraf_handoff_preflight.py --initialize-replay
python -B tools/sraf_handoff_preflight.py --check
python tools/build_sraf_openwebui_backend_pipe.py --output sraf_backend_pipe_bundle.py
~~~
本地快檢 PASS_PARTIAL/exit 2 是預期的部分結果，不能視為 live PASS；初始化成功
才為 INITIALIZED/exit 0。既有 DB 不初始化、不刪除修復；任何 FAIL 先停在本階段。
bundle 工具拒絕覆寫，若有舊檔先保留並選新的檔名。無需安裝整個 SRAF 到 OpenWebUI。

在 OpenWebUI 容器內可先執行（使用實際已安全放置的 bundle/manifest 路徑）：
~~~bash
python /REPLACE/sraf_backend_pipe_bundle.py --check-config --config-file /REPLACE/sender.json
~~~
不需設定 WEBUI_SECRET_KEY 或 ENABLE_VALVE_ENCRYPTION。

只有在獨立 Security Review、現場維護許可及所有 in-flight/queued/running
工作已妥善處置後，才以原 supervisor 於維護窗口啟動：
~~~bash
SRAF_HANDOFF_SUPERVISED_LAUNCH=1 bash run_sra_api.sh
~~~
shell flag 必須由這個命令的環境傳入，不是僅寫進 .env.local。
保留原 port（預設 9002）及原 Schedule/Handoff Worker；不另起第二套 API。
本指令可能觸發原 supervisor 的停機/接管；不要在執行中任務尚未排空時使用。
既有 supervisor 10 秒預設停機限制可能強制終止仍在執行的呼叫。
先確認原本公開 API、一般報告、排程正常，再確認私有 listener 實際 port。
RUNNING 是 socket readiness，不是 live report PASS。失敗不要放寬 TLS 或自動重試。

在 sender namespace 檢查：
~~~bash
python /REPLACE/sraf_backend_pipe_bundle.py --probe-transport --config-file /REPLACE/sender.json
~~~
預期 PASS_PARTIAL 且 TLS_CA_HOST_VERIFIED（跨容器）與 GET_405_ALLOW_POST。
405 只證明 method observation；公開 API 也可能回 405。另核對實際私有 port。
無需 assertion/問題/登入，不能證明 mapping 或 key pair 可用。

## 6. 實際報告驗收：一次、受控

經安全核准後，由管理員匯入新 bundle 作獨立 Function/模型，先保持 ENABLED=False，
設定 CONFIG_FILE，僅開放指定試行帳號。確認既有普通模型未被替換。
啟用後在正常瀏覽器中建立已儲存的新對話、單一文字問題、無附件/工具/system/history；
例如「請分析2023年8月期間，聯合國的外交回應、合作進展。」僅在實際資料與授權
符合時使用。普通結果須為真實檢索報告；一般 scope receipt 必須與深度原題詞、
索引與日期契合才允許自動派送。不能只憑語法就保證入隊。

| 驗收門檻 | 必須觀察 |
| --- | --- |
| 普通報告 | 真實 Agent/ES/LLM，正文與可用 Word，無假結果 |
| 自動深度任務 | 同一初始回覆、實際 Job ID/queued、進度網址；若未入隊記錄固定原因 |
| 進度登入 | 原 SRAF 登入；未登入需登入，不宣稱跨應用 SSO |
| 所有權 | 以另一本來授權的測試帳號驗證不暴露該私人 Job、Word |
| 多輪及 Word | 真實 round checkpoint、合理停止理由、已完成 DOCX 可下載及開啟；檢查日期/主題/引用 |
| 容錯 | 任務失敗/不滿足不捏造完成；未完成 Word 拒絕；普通服務仍可用 |
| 遷移 | 核准的 quiescent relocation，保留 account generation、replay/Job state、issuer/audience；更新 origin/CA/SAN，先快檢再試行 |

觀察並記錄實際運行時間、輪數、候選/證據數、資源占用及結束理由；使用者有實際
報告時才能驗證可用性，不用合成測試取代。勿把原文、token、簽章、signed URL、
key、使用者 ID、私有路徑/位址貼到 GitHub 或聊天。逾時可能仍執行，先查 Job
歷史與服務狀態，不連續重送。初版只有保存的 root text，不支援其他版本或多輪
對話、工具附件、自訂 system；相容性不足時回報限制而非刪除 context。

## 7. 停用／遷移／回退

先禁用新 Pipe，停止新提交。等待已准入呼叫與 running jobs 結束；若要取消，
只走既有授權 queued cancellation，不直接改 DB。備份所有持久 state 並驗證一致性，
包括 Job/Checkpoint/Word、AuthStore、issuer config/key、replay DB、API state；
禁止活躍寫入時用檔案複製宣稱一致備份。若無法排空則暫停遷移。
在核准窗口將 SRAF_HANDOFF_ENABLED=0、SRAF_DEEP_CHAT_AUTO_ENABLED=0，
需暫停深度執行時 SRAF_DEEP_REPORT_ENABLED=0 且 failure policy=ordinary_only
以保留 queued adaptive rows。去掉 shell opt-in 後依原 supervisor 重啟，
確認原一般報告、排程、Word 可用。不要刪除 replay 或 Job DB。
保留已安裝新版程式比盲目回退舊程式更安全；程式回退須先核對舊版 worker 是否會
誤認新 adaptive rows，使用受審查的相容版本與已核准的備份策略。
遷移至新主機禁止兩套不同 replay DB 同時接受舊 key 的 assertion。
若無法保留最新一致 replay DB，先撤銷舊 key、停收並等待所有舊 assertion 過期；
不還原舊 DB 讓舊 nonce 再次可用。停用舊 sender 後才啟用新 sender。
任何未知行為回到部分驗收/停止狀態，不宣稱上線完成。
