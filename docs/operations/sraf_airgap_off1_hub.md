# SRAF OFF-1 統一離線驗收／Debug 入口（operator only）

這是已合併 [PR #336](https://github.com/hun186/poc-agent/pull/336) 後，整合**既有** OFF-1 安全探針的一條指令入口，**不是** OFF-2～5 完整斷網驗收、發行證明、SQL/ES/LLM 功能已通過的宣告。

## 前提

1. 在**已部署的 SRAF 專案根目錄**操作。必須使用與 `./run_sra_api.sh` 相同、依 `requirements.txt` 安裝完成的 Python venv/Conda；不是無依賴、純標準函式庫的系統 Python。
2. 離線現場**不會**執行 pip、Node、網際網路、Docker 下載或自動重啟服務。
3. 請使用可信、操作員本人擁有的本機私有輸出路徑，且所有父目錄不允許其他人任意替換；例如 `--output-dir "$HOME/sraf-acceptance-results"`。符號連結、不安全權限與可疑父目錄會拒絕驗收，不能為求方便關閉檢查。

## 一鍵執行（直接複製）

最常用的**只讀 quick**，不提交任何報告、不登入、不查 SQL／ES、不呼叫 LLM：

```bash
python tools/sraf_airgap_off1_hub.py --output-dir "$HOME/sraf-acceptance-results"
```

增加既有 OFF-1B 設定範圍內的 API／ES／LLM **TCP 可達性診斷**；成功建立 TCP 連線不代表 TLS 身分、認證、模型或資料庫功能已驗收：

```bash
python tools/sraf_airgap_off1_hub.py --suite diagnose --output-dir "$HOME/sraf-acceptance-results"
```

**完全不開任何 HTTP/TCP socket** 的設定／本機磁碟／ODBC 庫檔案檢查：

```bash
python tools/sraf_airgap_off1_hub.py --suite diagnose --no-network --output-dir "$HOME/sraf-acceptance-results"
```

**僅獲得明確授權後**，透過原本 PR #336 的 OFF-1S 嚴格 listener 身分檢查與 Report Job CLI 執行**一筆真實報告**（會消耗 Agent、LLM、ES 工作資源，不可當成單純只讀診斷）：

```bash
python tools/sraf_airgap_off1_hub.py --live-report --output-dir "$HOME/sraf-acceptance-results"
```

若使用已有、最小權限且可撤銷的受控 Token，僅提供**環境變數名稱**，不要在指令列、版本庫或操作紀錄中放入明文：

```bash
python tools/sraf_airgap_off1_hub.py --live-report --token-env SRAF_TEST_BEARER --output-dir "$HOME/sraf-acceptance-results"
```

如需指定最長觀察時間：`--max-seconds 1200`（範圍 30～3600），只是觀測等待上限，**不會取消**已被 API 接受的 Job，不會盲目重送 POST。缺少 OFF-1S 嚴格證明時一律不發送憑證、回傳 INCOMPLETE。

## 實際跑了什麼

| 自動項目 | 既有實作 | 安全邊界 |
| --- | --- | --- |
| host_disk | OFF-1A `probe_disk` | 本機磁碟剩餘量觀察；不足為 WARN |
| host_odbc_library | OFF-1A `probe_odbc_library` | 只看已知本機函式庫檔案，不連 SQL；屬提醒不代表 SQL 通過 |
| api_health／UI／靜態資源 | PR #336 `_quick`／OFF-1A | 預設只在本機 127.0.0.1 有界匿名 GET |
| api_listener | OFF-1S `attest_api_listener` | Linux launcher 身分認證；只讀結果可能 SKIP |
| tcp_api／tcp_es／tcp_llm | OFF-1B `tcp_observe` | 只有選 `--suite diagnose` 才檢查，僅私有數字 IPv4；不碰資料／模型 |
| 真實 Job＋DOCX | PR #336 `_live` | **僅限** `--live-report`，嚴格 listener guard、單筆 POST／輪詢／Word 完整性 |

統一 JSON 只含固定 `check/status/reason`、無敏感資訊的觀察結論、模式、離線／授權旗標、統計以及 **8 個永遠保留 NOT_TESTED 的獨立人工門檻**。它不輸出密碼、Token、連線字串、SQL、Job ID、原始回應或文件內容。若啟動器證明不足、連線不到、尚未驗證，請先看 JSON 的原因碼，不要一律當作模型故障。

- `exit 0 / PASS_PARTIAL`：本次選定的**部分營運探測**通過；ODBC advisory 或未驗證手動門檻不能據此宣稱整套正式驗收成功。
- `exit 1 / FAIL`：有被選中的必要檢查明確失敗，或真實報告驗證失敗。
- `exit 2 / INCOMPLETE`：缺少證據、不能合法執行、無網路模式、API listener 未認證或輸出路徑不可信。

輸出 `off1-hub-<UTC時間>-<隨機>.json`，檔案權限 0600，受既有 `_secure_output_dir` 的 O_NOFOLLOW/dirfd 保護。只有被授權且完成的 `--live-report` 才另外留下私有 DOCX（0600）。若輸出目錄無法安全驗證，**不會嘗試向該目錄寫入任何證據**。

## 仍待獨立實機驗收：不會偷偷執行

`es_tls_ca_san_mapping`、`sql_schema_source_permissions`、`schedule_handoff_workers`、`real_agent_llm_es`、`browser_visual`、`package_release_provenance`、`backup_restore_off5`、`physical_airgap` 會保留為 `NOT_TESTED`。若未來把 OFF-1P／1Q、OFF-1 SQL／Handoff 的只讀證據接入，須依它們自身所需的 SQL 身分、schedule ID、owner-bound Token、Listener Guard 等另訂安全範圍及取得授權，不可把單純 TCP PASS 轉換為 SQL／報告功能 PASS。

Hosted pytest／OFF-0 schema-only／Node 靜態流程僅是**開發驗證**。真正 Linux、Ollama 分離容器、Elasticsearch HTTPS/IP SAN、SQL Server、Worker 行為、Word、真實瀏覽器以及物理斷網／備份還原等均須現場以各自獨立的證據驗收。若要驗證原本的單一 Report Job 工具，仍可使用 `tools/sraf_airgap_report_jobs_acceptance.py`；統一入口不替換、不修改它的正式行為。
