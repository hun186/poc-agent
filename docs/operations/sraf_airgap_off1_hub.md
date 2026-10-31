# SRAF OFF-1 統一離線驗收／Debug 入口（operator only）

這是已合併 [PR #336](https://github.com/hun186/poc-agent/pull/336) 後，整合**既有** OFF-1 安全探針的一條指令入口，**不是** OFF-2～5 完整斷網驗收、發行證明、SQL/ES/LLM 功能已通過的宣告。

## 前提

1. 在**已部署的 SRAF 專案根目錄**操作。必須使用與 `./run_sra_api.sh` 相同、依 `requirements.txt` 安裝完成的 Python venv/Conda；不是無依賴、純標準函式庫的系統 Python。
2. 離線現場**不會**執行 pip、Node、網際網路、Docker 下載或自動重啟服務。
3. 請使用可信、操作員本人擁有的本機私有輸出路徑，且所有父目錄不允許其他人任意替換；例如 `--output-dir "$PWD/sraf-acceptance-results"`。符號連結、不安全權限與可疑父目錄會拒絕驗收，不能為求方便關閉檢查。

## 不需要再貼長指令：Linux Shell 啟動器

部署更新後，專案根目錄會有 `run_sraf_airgap_off1_diagnose.sh`。操作員只要執行：

```bash
bash run_sraf_airgap_off1_diagnose.sh
```

不論從哪個目錄呼叫，腳本會自動切換到自身所在的 SRAF 專案根目錄，並固定呼叫 `python tools/sraf_airgap_off1_hub.py --suite diagnose --output-dir "$PROJECT_ROOT/sraf-acceptance-results"`（`PROJECT_ROOT` 為腳本所在的 SRAF 專案根目錄）。**不會加上 `--live-report`**，因此不會建立真實任務。它保留 Python 驗收工具原本的退出碼，不依賴 `HOME`，缺少 Python 時明確失敗。證據存於專案下的 `sraf-acceptance-results/`，已有根目錄 `.gitignore` 排除；請勿將私有 JSON／DOCX 手動提交 Git。目錄及每層父目錄必須符合既有 O_NOFOLLOW／權限安全規則，若專案在其他使用者可寫的共享掛載下，可能因 `output_ancestor_writable` 而拒絕寫入；不要為求方便放寬權限檢查，改用前述原始 Python CLI 指定可信的私有輸出位置。若 API 與 Shell 的預設 Python 不同，指定已部署的應用 Python（不能依賴斷網現場再安裝套件）：

```bash
SRAF_PYTHON=/path/to/sraf-venv/bin/python bash run_sraf_airgap_off1_diagnose.sh
```

使用 `bash` 呼叫不需要另外 `chmod +x`；Linux 用 `.sh`，Windows `.bat` 不適用於 SRAF 的 Linux 容器。

## 額外選用：SQL Server TLS 唯讀連線／固定 SELECT（需操作員明確授權）

**預設一般診斷不會嘗試登入 SQL Server，也不會自動從正式 SRAF SQL Registry、.env.local 或 DB 設定檔擷取連線帳密。** 本增量重用已存在的 OFF-1G `probe_sql_constant_read`，只有操作員指定 `--probe-sql-read`，且明確提供 **獨立、專用、最小 SELECT 權限** SQL 帳號時，才會透過已安裝的 `ODBC Driver 18 for SQL Server` 連線並執行**唯一固定 SQL**：

```sql
SELECT CAST(1 AS int)
```

必須使用操作員事先在 Linux Shell 以安全方式提供的以下五個環境變數（這裡**不**填實際值）：`SRAF_OFF1G_SQL_HOST`、`SRAF_OFF1G_SQL_PORT`、`SRAF_OFF1G_SQL_DATABASE`、`SRAF_OFF1G_SQL_USER`、`SRAF_OFF1G_SQL_PASSWORD`。Host 必須是 RFC1918 或 Loopback 的數字 IPv4，Port 必須合法，資料庫與使用者名稱限制為安全字面值；拒絕額外 DSN 或連線選項注入。ODBC 連線使用 `Encrypt=Yes;TrustServerCertificate=No;ApplicationIntent=ReadOnly`，**不可**為連線方便改用略過憑證驗證。IP SAN／TLS 名稱不符合時可能回報 SKIP／INCOMPLETE，不應視為網路或帳號一定失效。

已取得操作員授權且設定好專用帳密後，在已部署 SRAF 根目錄執行：

```bash
bash run_sraf_airgap_off1_diagnose.sh --probe-sql-read
```

也可同時明確選擇 ES 的獨立驗證（兩個 flag 可以任意順序排列；未選擇的連線不會執行）：

```bash
bash run_sraf_airgap_off1_diagnose.sh --probe-es-tls-mapping --probe-sql-read
```

**只讀邊界：**不查使用者表、不讀表內容、不檢查或修改 Schema、不呼叫儲存程序、不建立資料庫、不寫入任何資料，只有一次 ODBC 連線及固定常數 SELECT，正常連線下各最多 3 秒登入與查詢 timeout；Driver/native SQLSTATE／IP／資料庫名稱／使用者／密碼／查詢內容都不會列印在 JSON。底層 Driver 行為與逾時取消效果仍需在真實 Linux 現場驗證。不可搭配 `--no-network`、`--suite quick` 或 `--live-report`。

輸出新增 `sql_constant_read`，`PASS` 代表只觀察到固定 SQL 回傳常數 1；`SKIP` 代表憑證／Driver／連線不確定（退出碼 2），`FAIL` 為已建立查詢但回應內容不符（退出碼 1）。不管 SQL 常數查詢是否 PASS，獨立的 `sql_schema_source_permissions` 手動驗收門檻仍**NOT_TESTED**；**不能**據此推論 Schema v4、正式資料來源、表格存取權限、SQL Registry 或 Schedule/Handoff 已驗證。真正 SQL Schema metadata／版本／權限診斷需後續另定固定查詢及權限規範，不會偷偷擴大本次授權。

## 額外選用：嚴格 Elasticsearch HTTPS／IP SAN／Mapping 診斷（需要操作員明確授權）

**預設的 `bash run_sraf_airgap_off1_diagnose.sh` 完全不會新增 ES Basic 認證要求**，只執行原本的 private TCP 觀察。當操作員已獲得權限，確認診斷會使用目前設定中的 `ES_USERNAME`／`ES_PASSWORD` 向 ES 發出**最多三個有界唯讀 HTTPS GET**（根識別、`/_security/_authenticate`、指定索引 `/_mapping`）時，才執行：

```bash
bash run_sraf_airgap_off1_diagnose.sh --probe-es-tls-mapping
```

或直接執行已部署 Python（需在 SRAF 根目錄）：

```bash
python tools/sraf_airgap_off1_hub.py --suite diagnose --probe-es-tls-mapping --output-dir "$PWD/sraf-acceptance-results"
```

這個選項強制使用既有 OFF-1B 的 **CA 驗證且不得關閉 hostname／數字 IP SAN 檢查**，僅允許私有數字 IPv4 的 HTTPS 根端點；固定 CA 位置為 `agent/certs/http_ca.crt`，且需有一個安全的字面 `ES_INDEX`，有效的 `ES_USERNAME`／`ES_PASSWORD`。缺少配置／CA／索引時為 SKIP／INCOMPLETE，絕不退回不驗證憑證模式，不使用 DNS／proxy、無搜尋查詢、無寫入、無刪除或套件安裝。**禁止**與 `--no-network`、`--live-report` 或 `--suite quick` 併用。

輸出增加 `es_strict_tls_mapping`，只記錄固定的 `https_probe`、`tls_validation`、`mapping_probe`、`auth` 狀態，不記載 IP／索引名稱／帳密／CA 路徑／HTTP 回應。嚴格 TLS 與 Mapping 均可觀察為 PASS，但**這個模式故意不送錯密碼負向對照**（可能觸發登入失敗稽核或帳戶鎖定），因此 `auth=NOT_VERIFIED` 時，整個新檢查仍為 SKIP，`SRAF_OFF1_HUB=INCOMPLETE`／退出碼 2，而非假裝正式認證 PASS。TLS、HTTPS 或 Mapping 的可判定失敗則為 FAIL／退出碼 1。只有普通未額外選用的診斷仍依原先檢查決定退出碼。正式 `es_tls_ca_san_mapping` 手動驗收門檻始終 `NOT_TESTED`。

ES 探針與本機 API 健康檢查分開執行：API 無法連線仍能留下已選用的 ES 診斷結果；但任何部分網路或 TLS 成功都**不是**完整 Agent／Elasticsearch 查詢能力或離線部署驗收。



## 一鍵執行（直接複製）

最常用的**只讀 quick**，不提交任何報告、不登入、不查 SQL／ES、不呼叫 LLM：

```bash
python tools/sraf_airgap_off1_hub.py --output-dir "$PWD/sraf-acceptance-results"
```

增加既有 OFF-1B 設定範圍內的 API／ES／LLM **TCP 可達性診斷**；成功建立 TCP 連線不代表 TLS 身分、認證、模型或資料庫功能已驗收：

```bash
python tools/sraf_airgap_off1_hub.py --suite diagnose --output-dir "$PWD/sraf-acceptance-results"
```

**完全不開任何 HTTP/TCP socket** 的設定／本機磁碟／ODBC 庫檔案檢查：

```bash
python tools/sraf_airgap_off1_hub.py --suite diagnose --no-network --output-dir "$PWD/sraf-acceptance-results"
```

**僅獲得明確授權後**，透過原本 PR #336 的 OFF-1S 嚴格 listener 身分檢查與 Report Job CLI 執行**一筆真實報告**（會消耗 Agent、LLM、ES 工作資源，不可當成單純只讀診斷）：

```bash
python tools/sraf_airgap_off1_hub.py --live-report --output-dir "$PWD/sraf-acceptance-results"
```

若使用已有、最小權限且可撤銷的受控 Token，僅提供**環境變數名稱**，不要在指令列、版本庫或操作紀錄中放入明文：

```bash
python tools/sraf_airgap_off1_hub.py --live-report --token-env SRAF_TEST_BEARER --output-dir "$PWD/sraf-acceptance-results"
```

如需指定最長觀察時間：`--max-seconds 1200`（範圍 30～3600），只是觀測等待上限，**不會取消**已被 API 接受的 Job，不會盲目重送 POST。缺少 OFF-1S 嚴格證明時一律不發送憑證、回傳 INCOMPLETE。

## 實際跑了什麼

| 自動項目 | 既有實作 | 安全邊界 |
| --- | --- | --- |
| host_disk | OFF-1A `probe_disk` | 本機磁碟剩餘量觀察；不足為 WARN |
| host_odbc_library | OFF-1A `probe_odbc_library` | 只看已知本機函式庫檔案，不連 SQL；屬提醒不代表 SQL 通過 |
| api_health／UI／靜態資源 | PR #336 `_quick`／OFF-1A | 預設只在本機 127.0.0.1 有界匿名 GET |
| api_listener | OFF-1S `attest_api_listener` | Linux launcher 身分認證；只讀結果可能 SKIP |
| worker_process_identity | OFF-1H `probe_worker_process_identities` | `--suite diagnose`（含 `--no-network`）額外讀取本機 Schedule/Handoff Worker 身分紀錄與 `/proc`，只做程序觀察，不查 SQL、不發送 HTTP、不建立工作 |
| tcp_api／tcp_es／tcp_llm | OFF-1B `tcp_observe` | 只有選 `--suite diagnose` 才檢查，僅私有數字 IPv4；不碰資料／模型 |
| es_strict_tls_mapping | OFF-1B ES HTTPS/Mapping `_observe` | **僅**在 `--suite diagnose --probe-es-tls-mapping` 下使用配置好的 Basic 身分發出有限的嚴格 CA＋IP SAN HTTPS 唯讀 GET；整體認證仍 NOT_VERIFIED |
| sql_constant_read | OFF-1G `probe_sql_constant_read` | **僅** `--suite diagnose --probe-sql-read`，獨立最小權限帳密與 ODBC Driver 18，固定常數 SELECT；不檢查 Schema／資料來源／帳號權限 |
| 真實 Job＋DOCX | PR #336 `_live` | **僅限** `--live-report`，嚴格 listener guard、單筆 POST／輪詢／Word 完整性 |

**OFF-1H 新增部分觀察：** `bash run_sraf_airgap_off1_diagnose.sh` 現在會在原有 HTTP/TCP 診斷之外，讀取兩個既有 Worker 的啟動器身分記錄與 `/proc`，輸出 `worker_process_identity=PASS/SKIP` 和去識別化的 `verified_role_count`（0～2）。本檢查不會修改 Worker、取得租約、觸發 Schedule、查詢 SQL，不能證明完整 Handoff E2E，因此固定 `schedule_handoff_workers=NOT_TESTED`。Worker 不在同一 PID namespace、未部署或證明不足時 SKIP；屬輔助診斷，不改變原本 Report Job／TCP 必要檢查的退出碼，也不會被當成放行的 PASS。真正的 Linux 容器環境還需操作員實測。

統一 JSON 只含固定 `check/status/reason`、無敏感資訊的觀察結論、模式、離線／授權旗標、統計以及 **8 個永遠保留 NOT_TESTED 的獨立人工門檻**。它不輸出密碼、Token、連線字串、SQL、Job ID、原始回應或文件內容。若啟動器證明不足、連線不到、尚未驗證，請先看 JSON 的原因碼，不要一律當作模型故障。

- `exit 0 / PASS_PARTIAL`：本次選定的**部分營運探測**通過；ODBC advisory 或未驗證手動門檻不能據此宣稱整套正式驗收成功。
- `exit 1 / FAIL`：有被選中的必要檢查明確失敗，或真實報告驗證失敗。
- `exit 2 / INCOMPLETE`：缺少證據、不能合法執行、無網路模式、API listener 未認證或輸出路徑不可信。

輸出 `off1-hub-<UTC時間>-<隨機>.json`，檔案權限 0600，受既有 `_secure_output_dir` 的 O_NOFOLLOW/dirfd 保護。只有被授權且完成的 `--live-report` 才另外留下私有 DOCX（0600）。若輸出目錄無法安全驗證，**不會嘗試向該目錄寫入任何證據**。

## 仍待獨立實機驗收：不會偷偷執行

`es_tls_ca_san_mapping`、`sql_schema_source_permissions`、`schedule_handoff_workers`、`real_agent_llm_es`、`browser_visual`、`package_release_provenance`、`backup_restore_off5`、`physical_airgap` 會保留為 `NOT_TESTED`。若未來把 OFF-1P／1Q、OFF-1 SQL／Handoff 的只讀證據接入，須依它們自身所需的 SQL 身分、schedule ID、owner-bound Token、Listener Guard 等另訂安全範圍及取得授權，不可把單純 TCP PASS 轉換為 SQL／報告功能 PASS。

Hosted pytest／OFF-0 schema-only／Node 靜態流程僅是**開發驗證**。真正 Linux、Ollama 分離容器、Elasticsearch HTTPS/IP SAN、SQL Server、Worker 行為、Word、真實瀏覽器以及物理斷網／備份還原等均須現場以各自獨立的證據驗收。若要驗證原本的單一 Report Job 工具，仍可使用 `tools/sraf_airgap_report_jobs_acceptance.py`；統一入口不替換、不修改它的正式行為。


## OFF-4：自動產生中文 TXT 診斷摘要（不新增網路／資料庫操作）

執行相同的一鍵診斷命令後，除了原有的私有 `off1-hub-<UTC時間>-<隨機>.json`，也會在**同一已驗證目錄**寫入相同前綴的 `.txt`，權限同為 **0600**。命令列將印出 `EVIDENCE_FILE=` 與 `TXT_FILE=`。兩份輸出由原本的 `_secure_output_dir` 驗證、同一個已 pin 的 Linux dirfd 配合 O_NOFOLLOW/O_EXCL 寫入，**不會**重新解析不可信任路徑。

TXT 包含：時間、Quick／Diagnose、部分結果、已執行檢查的中文名稱與 PASS/FAIL/WARN/SKIP、各項非 PASS 的保守處置建議，以及固定 8 個完整驗收門檻 **NOT_TESTED**。TXT 只透過受限白名單轉換狀態與名稱；不複製 JSON 的原始 `reason`、例外訊息、觀察 payload、主機、帳密、Job ID、SQL 字串、Token 或任何其他未知欄位。更詳細但同樣脫敏的固定原因碼保留在 JSON，供授權工程師查閱。

TXT 產生是**純本機格式化**，不發送第二次健康檢查、SQL、ES、LLM，也不建立 Report Job。若 TXT 寫入失敗，CLI 會回報 `evidence_write_unavailable`／exit 2；已完成的 JSON 可能仍留在私有目錄，其檢查結果必須與「TXT 報告未完整寫出」分開看待。這不是交易式雙檔提交，也不是物理斷網或完整功能驗收證明。

## OFF-4 固定原因碼的分流建議

中文 TXT 在原本的固定檢查項目建議之外，針對**特定 check／status／reason 三欄完全吻合**的已審查組合，提供更精準的離線排除方向，例如專用 SQL ODBC 18 驅動缺失、SQL TLS／IP SAN 無法確認、Elasticsearch TLS 身分或 Mapping 失敗、嚴格 API Listener 無法認證、Worker PID Namespace 未可見等。**原因碼本身仍不寫入 TXT**，僅從程式內固定中文白名單選一條處置建議。未知、格式錯誤或互相矛盾的原因碼一律使用既有保守一般建議，不推論或補寫連線字串、Exception、SQLSTATE、使用者名稱、主機位址、憑證或 Token。完整的固定原因碼保留在私有 JSON。

本增量只改**純本機報告格式化**，既有檢查、退出碼、輸出檔案、權限、SQL/ES Opt-in、LLM/Job 不受影響。任何建議不代表實際修復，所有八項手動驗收門檻仍為 `NOT_TESTED`，實際斷網及業務 E2E 須分別驗收。


## 共用掛載環境的安全輸出位置（Shell 一鍵指定）

預設仍寫入 SRAF 根目錄下的 `sraf-acceptance-results/`。如果專案位於 group-writable 或可疑的共用掛載，既有 `_secure_output_dir` 可能因 `output_ancestor_writable` 拒絕寫檔。**不可透過 chmod 放寬原有驗證**；可在可信、操作員獨占的絕對路徑下另行選擇證據目錄（示例使用事先確認可信的私人父目錄）：

```bash
SRAF_OFF1_OUTPUT_DIR="$HOME/sraf-private-evidence" bash run_sraf_airgap_off1_diagnose.sh
```

若有需要，`SRAF_PYTHON` 與 `SRAF_OFF1_OUTPUT_DIR` 可以同時設定，診斷的 ES／SQL 旗標仍須由操作員另外明確加上。此 Shell 設定只決定 `--output-dir` 的字串：必須是非空、單行的絕對路徑，拒絕相對路徑；**不建立任何目錄、不改變權限、不嘗試備援輸出、不繞過 Python 的 Linux O_NOFOLLOW／private dirfd／UID/0700 檢查**。新路徑的每層父目錄仍須符合原有安全條件，否則工具應回傳 INCOMPLETE／退出碼 2，不得顯示假成功。輸出的 JSON/TXT 仍是 0600。不要把私人輸出目錄加入版本控制或公開檔案分享。預設命令與所有檢查結果不變；這不是實際完整離線驗收。
