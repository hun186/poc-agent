# SRAF OFF-1A — 第一批非破壞性依賴探測（可執行、非正式驗收）

追蹤 Issue #290；繼承 OFF-0 契約。OFF-1A 只提供**獨立、受限的單項探測器**，並不修改 OFF-0 安全報告建構函式，也不代表 OFF-1 整體或 OFF-3 統一 Runner 完成。

## 已實作的狹義探測

| CLI --check | 對應 OFF-0 ID | 模式 | 實際檢查 | 無法由此宣稱 |
| --- | --- | --- | --- | --- |
| sys-disk | SYS-01 | quick | 執行目錄所在磁碟空間（門檻 512 MiB）及 CPU 邏輯數 | 完整主機、GPU、時間同步、輸出目錄權限 |
| odbc-library | ENV-02 | quick | 對少量固定本機 Unix 安裝路徑檢查 ODBC 函式庫檔案是否存在，不執行 helper／dynamic loader | 已裝 SQL Server driver、能連線 |
| api-health | API-01 | quick | 匿名 GET 127.0.0.1:PORT/healthz HTTP 200 | Auth/RBAC、SQL/ES/LLM、完整 API 可用性 |
| es-transport | ES-01 | diagnose | 匿名 GET / 回 HTTP 200 且包含 cluster_name + version.number | ES 認證、Mapping、檢索、叢集健康 |
| llm-inventory | LLM-01 | diagnose | 匿名 GET Ollama /api/tags 或相容 /v1/models，列出完整指定名稱 | 模型可載入、GPU/context、推論成功 |

每次的 **PASS 只代表表列狹義子測項通過**，輸出固定 mode=PARTIAL_ONLY_NOT_ACCEPTANCE，不可映射成 OFF-0 主 ID 的 PASS 或 FULL_LIVE。對 ES 的 HTTP 401/403 記為 SKIP(es_credentials_not_probed)，不是連線／認證通過。

## 使用方式（部署主機上由操作人員執行）

    python tools/sraf_airgap_off1_probes.py --check sys-disk
    python tools/sraf_airgap_off1_probes.py --check odbc-library
    python tools/sraf_airgap_off1_probes.py --check api-health --api-port 8000
    python tools/sraf_airgap_off1_probes.py --check es-transport --mode diagnose --es-port 9200
    python tools/sraf_airgap_off1_probes.py --check llm-inventory --mode diagnose --llm-port 11434 --llm-backend ollama --model-name 'local-model-name'
    python tools/sraf_airgap_off1_probes.py --check llm-inventory --mode diagnose --llm-port 11435 --llm-backend openai --model-name 'local-model-name'

Port 和 Model Name 為參數範例，**非已驗證的正式部署配置**。沒指定 model-name 時 LLM probe 直接 SKIP，不呼叫服務。CLI 必須明確選擇一個 --check，不會預設執行全套。一切輸出固定 JSON 類型 sraf_airgap_off1_partial_probe_v1、狹義 aspect 與 executed 欄。退出碼 0=該子項 PASS、1=FAIL/WARN、2=SKIP。

## 安全邊界

- HTTP 僅送匿名 **GET** 到字面固定的 IPv4 loopback 127.0.0.1 和明確限制的埠（1..65535）；不使用 Proxy、不自動追隨 3xx、不登入、不加入 Bearer/Basic/Cookie，使用全請求共用的單調時鐘**絕對截止時間 3 秒**（連線、送出、回應標頭、回應本文皆受限；不是每次 recv 重設的 3 秒），Body 最多 64 KiB + 1 byte。持續慢速傳送字節也會在截止時中止；超時分類為對應子探測的 transport unavailable。
- 不支援任意內網 DNS/IP 和 TLS；如 SRAF 依賴在不同主機，後續須另設經核准的遠端 allowlist/TLS 及秘密配置安全界面，不能藉不受限的任意 URL 放寬探測邊界。
- 不輸出 HTTP 原始內文、例外、headers、URL、模型名稱、檔案路徑、連線字串、機敏值；僅固定 reason codes + 有界整數／布林證據。
- HTTP 接受結果前先以暫時性、具上限的原始行讀取器驗證狀態行與每一行 HTTP 標頭皆以 `CRLF` 正確結尾（不接受僅 LF 或 EOF 行尾），同時驗證每個最終及 `100 Continue` 暫時回應的**原始狀態行**符合受限的 HTTP/1.0/1.1 版本、三位數狀態碼與不含 NUL/控制字元的合法原因文字，並驗證原始標頭欄位名稱為合法 HTTP token、標頭值不含 NUL／控制字元、不允許無冒號或舊式折行；只有 `HTTP/1.0` 與 `HTTP/1.1` 原始狀態版本可進入任何本文解析模式（chunked 進一步限 `HTTP/1.1`）。標頭驗證後復原原始緩衝串流，供有界本文讀取使用，再檢查 HTTP 標頭解析器所記錄的任何語法缺陷（包含有空白分隔的 `Content-Length : -1`，避免不合法標頭被解析器丟棄後誤認為未指定長度）；再比對 Content-Length 已解析標頭值，拒絕非十進位、負數、重複長度標頭，以及 Content-Length 與 Transfer-Encoding 同時存在的歧義格式；單獨、唯一且由 http.client 確實辨識的標準 Transfer-Encoding: chunked，僅限原始狀態行版本字串精確為 `HTTP/1.1`（不只信任 Python 正規化後的 response.version）、且沒有 Content-Length 時使用受限分塊解碼；改由嚴格讀取函式逐塊檢查尺寸、分塊本文後的 CRLF、最後 0-size chunk 與完整 trailer 終止 CRLF，必要的 trailer 也須格式合法；其他編碼、重複編碼、HTTP/1.0 chunked、損壞 CRLF 與截斷分塊全部拒絕。對長度宣告回應，仍核對宣稱長度與實際收到的本文長度；提前 EOF、截斷的 JSON 即使語法有效，也不得 PASS。Elasticsearch 基本身分 JSON 的 cluster_name 與 version.number 不可為空白字串。這仍不構成認證或 Mapping 驗收。
- 不讀取 secrets、不執行 SQL、不登入、不啟停 Worker、不寫入資料、不得呼叫會建索引的 prepare_requirement_elasticsearch、不執行 LLM completion 或 E2E。
- SYS、ODBC 都只是局部檢查；ODBC library 存在不等於 SQL Server ODBC driver 可用。ODBC 只用事先審查的固定 Unix 本機路徑進行檔案存在性檢查，不呼叫 ctypes.util.find_library（Linux 上可能啟動無時間限制的 ldconfig/compiler 子程序）；未知自訂路徑可能產生 WARN 假陰性、非 POSIX 平台回報 SKIP，絕不冒充驅動可用。API /healthz HTTP 200 不等於完整 SRA 或其依賴都可用。
- OFF-0 安全 make_report_record 函式仍僅允許 SKIP(check_not_implemented)，因為沒有可信 execution-bound 報告路徑。**OFF-1 子探測結果不經 OFF-0 正式報告邊界**；不可宣稱正式通過。
- CI 中本機 HTTPServer 是可重現的安全負面/正面測試；若在 GitHub runner 執行主機 probe，僅量測 GitHub runner，**不是使用者封閉網路的 FULL_LIVE SQL/ES/LLM 驗收**。

## OFF-1 剩餘缺口（不可標記完成）

1. SQL-01/02：使用事前核准的 read-only SQL account/DSN、資料庫層權限、有限超時進行 SELECT 1 與 catalog/schema 查核，不得叫 initialize()、migration 或寫入。分類 driver／DNS／登入／權限／schema drift，不顯示連線字串。
2. ES-01 認證與 ES-02 Mapping：經核准的內網 TLS、既有憑證安全界面、GET-only mapping/alias，重用 agent/external_capabilities.py::mapping_compatibility，追查原有 mapping_incompatible blocker。
3. LLM-01 服務：核准遠端 allowlist，模型 metadata、GPU/記憶體/context 有界驗證；模型小型真實推論留給獲授權的 Acceptance。
4. SYS/ENV：CPU/GPU、時鐘、TLS/CA、磁碟實際輸出目錄、依賴鎖定 wheelhouse、真正 ODBC driver 及原生函式庫。
5. OFF-3/4：把真實執行 provenance 綁到完整 Parent Check 後，才能產生正式 PASS/FAIL/WARN，且必須涵蓋 mode、依賴鏈、脫敏、Auth 和隔離環境 Gate。

這是第一批 **OFF-1A 增量工作**。GitHub Actions 和 Codex Review 需要在獨立 PR 上通過；未取得使用者明確 merge 指令不得合併。
