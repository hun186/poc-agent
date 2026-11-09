# SRAF 分層診斷與驗收（L0–L3）

## 入口與預設安全邊界

從 Linux 部署目錄執行：

~~~bash
bash 1_完整診斷驗收_SRAF.sh
bash 1_完整診斷驗收_SRAF.sh --help
~~~

**預設 L1**：沿用原有六項唯讀 L0 快檢，再使用既有有界探針確認 API／Elasticsearch／LLM 私網 TCP 可達性，並向本機 API 發送**匿名** GET /healthz。不登入、不執行模型、不查 SQL、不建立 Job、不寫檔、不重啟服務、不改動正式資料。L0 全部通過時仍最多回報 PASS_PARTIAL，不是正式部署／發行簽章／物理斷網證明。L1 的 ES／LLM TCP 可達並不代表服務認證、模型推論或索引查詢已正常。

## L2：需逐項選用的元件功能測試

~~~bash
# 專用最小權限 SQL 帳號須預先以 SRAF_OFF1G_SQL_* 設定
bash 1_完整診斷驗收_SRAF.sh --level L2 --probe-sql-read

# 須預先配置可信 ES CA、Basic 憑證、私有 IP、既有索引
bash 1_完整診斷驗收_SRAF.sh --level L2 --probe-es-tls-mapping

# 僅適用本機 Ollama，需指定已核實的 Ollama serve PID
bash 1_完整診斷驗收_SRAF.sh --level L2 --probe-llm-inference --ollama-server-pid 12345
~~~

可一次選用多個 L2 選項；**未選的不執行，標記 NOT_TESTED**。L2 SQL 始終是 OFF-1G 的一次 TLS 驗證後固定常數 SELECT，不檢查真實資料表、Schema v4、帳號只讀性。ES 使用 OFF-1B 嚴格 CA＋IP SAN 的唯讀根身分、認證與 Mapping GET；既有 Hub 未執行獨立錯誤憑證控制，不能以觀察到 Mapping 推論完整認證已證實，因此保守標記 SKIP。LLM 僅支援既有 OFF-1D 本機無雲 Ollama /api/tags＋一次有界推論，必須驗證程序、Socket、OLLAMA_NO_CLOUD；遠端／OpenAI 相容端點不會假裝通過。

以上沿用既有安全函式，不修改資料庫、ES、排程，也不呼叫正式 API POST。L2 缺少全部 opt-in 時回報 INCOMPLETE。

## L3：一次真實 Report Job 與 DOCX

~~~bash
# Token 需由管理員預先以環境變數安全供應，不能貼到指令或 Git
# 事先建立可信、私有、通過 no-follow 祖先檢查的證據目錄
bash 1_完整診斷驗收_SRAF.sh --level L3 --live-report \
  --token-env SRAF_TEST_BEARER \
  --output-dir /path/to/trusted-private-evidence
~~~

L3 要求 L0 六項可觀察、L1 匿名 API 健康與 ES／LLM TCP 成功，並使用**現有** OFF-1 Report Job 驗收程式。後者先嚴格驗證 API9002 所屬程序／獨占 Socket，再用測試 Token 建立**一筆真實** Report Job、輪詢並校驗 DOCX；原有防護包含不盲目重送 POST、有限等待、可信輸出路徑與 0600 證據檔。L3 可能消耗模型資源並寫入 Report Job 及 DOCX；需事先授權、使用隔離資料，**不可視為唯讀**。

目前 L3 **沒有**建立 Requirement → Schedule → Handoff 工作鏈，也沒有檢查完整 Source／Schema v4 權限、真實 ES 檢索來源、Worker 自動認領、正式瀏覽器；固定 L3.requirement_schedule_handoff_e2e=NOT_TESTED。完整 E2E、升級回滾、封網驗收仍需 Issue #290 另行完成，Report Job 成功不會被誤標成 FULL_LIVE。

## 結果與分享方式

每項回傳 PASS、PASS_PARTIAL、FAIL、SKIP、INCOMPLETE 或 NOT_TESTED，以及固定去識別原因碼、耗時毫秒。最後一行 SRAF_DIAGNOSTICS_JSON=... 可分享，包含選定層級、結果、個別檢查，並固定 production_release_ready=false。原 OFF-1 Job 證據寫到**可信私人目錄**，但新終端摘要不包含 Token、密碼、PID、主機／SQL 連線、Job ID、私有輸出路徑。

CLI PASS_PARTIAL 退出碼 0、FAIL 退出碼 1、INCOMPLETE 退出碼 2；只是**所選診斷子集**狀態，不是正式 Release Gate。安全驗證缺失時，禁止停用 TLS、放寬目錄權限、跳過 Listener 保護。原 0_一鍵快檢_SRAF.sh 和其他 OFF-1/OFF-2 工具不變。

單向增量更新須一併同步根目錄 Shell 與 tools/sraf_operator_diagnostics.py，以及它依賴的既有模組，無需在部署機執行 Git。Hosted CI 不代表部署機 SQL／ES／LLM 或真實 E2E 證據。

若部署 API 使用自訂 shell PORT，分層入口會以啟動前選定的 PORT 執行 L0 六項 Listener 前置檢查並保留該 Port 供 L3 驗收；原本獨立的 0_一鍵快檢_SRAF.sh 仍固定檢查 9002，行為不變。磁碟不足會保留獨立 WARN 與其餘元件結果，而非覆蓋為全部 INCOMPLETE。未量測耗時的項目顯示 not_measured，不能當成 0ms。
