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

## L3：真實 Report Job，或完整 Requirement 自動排程 E2E（互斥授權）

~~~bash
# Token 需由管理員預先以環境變數安全供應，不能貼到指令或 Git
# 事先建立可信、私有、通過 no-follow 祖先檢查的證據目錄
bash 1_完整診斷驗收_SRAF.sh --level L3 --live-report \
  --token-env SRAF_TEST_BEARER \
  --output-dir /path/to/trusted-private-evidence
~~~

L3 要求 L0 六項可觀察、L1 匿名 API 健康與 ES／LLM TCP 成功，並使用**現有** OFF-1 Report Job 驗收程式。後者先嚴格驗證 API9002 所屬程序／獨占 Socket，再用測試 Token 建立**一筆真實** Report Job、輪詢並校驗 DOCX；原有防護包含不盲目重送 POST、有限等待、可信輸出路徑與 0600 證據檔。L3 可能消耗模型資源並寫入 Report Job 及 DOCX；需事先授權、使用隔離資料，**不可視為唯讀**。


### 真實 Requirement → Schedule → Handoff → Report Job → DOCX

先由部署操作員依照既有 [Requirement Automatic Operator E2E 手冊](requirement-automatic-operator-e2e.md) 設定部署專用的 operator_e2e/e2e.env.local（必須是目前執行使用者擁有的**一般檔案**，0600、非空、最大 64 KiB），並確認來源 XLSX、Runtime Provenance 與部署中的模式正確。這個檔案包含正式權限設定，**絕不可上傳或貼到對話裡**。

~~~bash
# 這會建立真實測試 Requirement／Schedule，並由現有 Worker 自動執行
# 需要部署上的 REQUIREMENT_E2E_EXTERNAL_MODE=live，否則會拒絕
bash 1_完整診斷驗收_SRAF.sh --level L3 --full-e2e \
  --verification release \
  --output-dir /path/to/trusted-private-evidence
~~~

完整 E2E **不會**使用其他 L3 Report Job 選項的 Token；它沿用原本 E2E Harness 受控的 e2e.env.local，明確要求 **--external-mode live**（程式固定傳入）。如果正式運行中的環境不是 live，原有 Harness 會在實際修改資料前拒絕。驗證路徑包括真實 XLSX 匯入、Requirement Snapshot、Schedule 版本建立／啟用、等待 Worker 自動認領、Handoff、Report Job、Agent／LLM／ES、DOCX／持久化狀態對帳及 Harness 清理。它有**實際 SQL／ES／報告寫入**與模型資源消耗，不適合日常巡檢；不可與 --live-report 同時選用。

如果只想確認功能流程，亦可明確改用 --verification functional，但即使流程成功也必須回報 SOURCE_ATTESTATION 不一定等於 VERIFIED、DEPLOYMENT_ACCEPTANCE=NOT_ESTABLISHED，不能當成 Release 驗收。若使用預設 --verification release，原 Harness 仍會嚴格檢查 Source/Runtime Provenance。此一層成功最多回報 PASS_PARTIAL／OBSERVED_PARTIAL，**不等於**實機物理斷網、完整可重現發行包或備份還原驗收；其他驗收門檻仍由 Issue #290 管理。專案原始 Harness 的私人 result.json、summary.txt 才是 E2E 細節的正式證據；統一入口僅輸出固定狀態與原因碼，不列印 PID、憑證、任務 ID、檔案路徑和錯誤內容。

如果僅選 --live-report，則 L3.requirement_schedule_handoff_e2e 維持 NOT_TESTED；兩者是不同驗收範圍。


## 結果與分享方式

每項回傳 PASS、PASS_PARTIAL、FAIL、SKIP、INCOMPLETE 或 NOT_TESTED，以及固定去識別原因碼、耗時毫秒。最後一行 SRAF_DIAGNOSTICS_JSON=... 可分享，包含選定層級、結果、個別檢查，並固定 production_release_ready=false，即使現有 E2E Harness 在 release 模式通過亦不把 physical_airgap 變成 PASS。原 OFF-1 Job 證據寫到**可信私人目錄**，但新終端摘要不包含 Token、密碼、PID、主機／SQL 連線、Job ID、私有輸出路徑。

CLI PASS_PARTIAL 退出碼 0、FAIL 退出碼 1、INCOMPLETE 退出碼 2；只是**所選診斷子集**狀態，不是正式 Release Gate。安全驗證缺失時，禁止停用 TLS、放寬目錄權限、跳過 Listener 保護。原 OFF-1/OFF-2 工程診斷工具保留；根目錄舊 0_一鍵快檢_SRAF.sh 已由統一入口 --level L0 取代並停止發行。

單向增量更新須一併同步根目錄 Shell 與 tools/sraf_operator_diagnostics.py，以及它依賴的既有模組，無需在部署機執行 Git。Hosted CI 不代表部署機 SQL／ES／LLM 或真實 E2E 證據。

若部署 API 使用自訂 shell PORT，分層入口會以啟動前選定的 PORT 執行 L0 六項 Listener 前置檢查並保留該 Port 供 L3 驗收；舊的 OFF-3 canonical deploy-check 仍固定檢查 9002，統一入口 L0 可觀察啟動時選定的 PORT。磁碟不足會保留獨立 WARN 與其餘元件結果，而非覆蓋為全部 INCOMPLETE。未量測耗時的項目顯示 not_measured，不能當成 0ms。

## 內網維護人員：中文診斷與離線報告

預設執行仍然是原本的安全 L0／L1 模式，不登入、不查 SQL、不呼叫模型或建立 Job：

~~~bash
bash 1_完整診斷驗收_SRAF.sh
~~~

新版終端報告直接顯示：每項實際觀察與驗證範圍、中文狀態、是否未測、依嚴重程度排序的待釐清項目與維護建議。ES／LLM TCP 可達不能被寫成搜尋／推論功能正常；API /healthz HTTP 200 也不等於整套報告業務鏈通過。Worker `worker_process_identity_unverified` 只表示程序身分證據不足，首個 Schedule 身分不符時會停止、不能用 0／2 推論兩個 Worker 都壞掉。避免手動改身份紀錄／權限或重啟服務。

要在沒有外網的內網**留存 TXT＋JSON**，可指定額外的私人診斷目錄：

~~~bash
bash 1_完整診斷驗收_SRAF.sh --report-dir /trusted/private/maintenance-reports
~~~

這個 `--report-dir` 與 L3 原有的 `--output-dir` 不同。指定時，既有 OFF-1 no-follow 安全檢查會先驗證所有祖先目錄及目前使用者獨佔的 0700 最終目錄，之後才執行探針。兩份報告以 `sraf-diagnostics-UTC時間-隨機碼.txt`／`.json` 寫入，使用 O_EXCL、O_NOFOLLOW、0600。輸出 `REPORT_SAVE=PASS` 才表示雙檔已寫入；`REPORT_SAVE=INCOMPLETE` 表示保存未完成且結束碼為 2。不得因共享掛載目錄拒絕而放寬權限或轉存至不可信路徑。終端不會顯示任何私人輸出路徑、Token、密碼、IP、PID 或原始例外資訊。

末行 `SRAF_DIAGNOSTICS_JSON=` 仍保留供原有程式解析。預設模式**不寫入診斷檔案**；只有明確選用 `--report-dir` 才保存。此中文判讀與本機報告不需要 Internet，也不需要回傳給 ChatGPT。即使元件觀察通過，`production_release_ready=false`、物理斷網／Wheelhouse／備份還原依舊不成立。

## 統一入口的純離線 L0 模式與省事保存方式（2026-11-09）

新版同一個根目錄入口可以做**真正零網路**的 L0 六項本機快檢，不啟動 API／ES／LLM TCP，也不執行 SQL、模型或 Job：

~~~bash
bash 1_完整診斷驗收_SRAF.sh --level L0
~~~

預設不帶參數仍是 L1（會使用有界的本機／私有 TCP 和匿名 /healthz）。L0 的中文診斷摘要只報告六項被動觀察，其餘項目均為 NOT_TESTED。即使 L0 或 L1 PASS_PARTIAL，也不是正式部署或全功能驗收。

**最簡單的離線報告保存方法：**

~~~bash
bash 1_完整診斷驗收_SRAF.sh --save-report
# 如需完全不連網且保存診斷
bash 1_完整診斷驗收_SRAF.sh --level L0 --save-report
~~~

選用 --save-report 時，程式會從 Linux 帳號資料庫判定目前使用者的**真正主目錄**，在該目錄下建立最終子目錄 .sraf-maintenance-reports（若尚未存在，僅會建立這一層，權限 0700）。原有 OFF-1 no-follow 安全檢查仍會逐層驗證目錄所有權及祖先權限；TXT/JSON 以 O_EXCL、O_NOFOLLOW、0600 寫入。這與 SRAF 的專案根目錄或共用掛載目錄無關，不會自動 chmod、更不會將正式敏感憑證寫入報告。**只有明確選擇 --save-report 或 --report-dir 才會寫入檔案。**

若指定 --report-dir，仍須是存在可信祖先的**絕對路徑**。例如命令中的 /trusted/private/... 只是範例，主機不會預先產生該目錄；傳入相對路徑（如 maintenance-reports）會明確顯示 report_dir_relative 和 --save-report 的修正提示。若共享掛載、祖先所有權或 0700 最終目錄不符合要求，會明確拒絕並提供固定安全指引；切勿 chmod 777。終端不輸出主目錄、帳號身分或私人完整檔案路徑。

根目錄舊 0_一鍵快檢_SRAF.sh 已由 --level L0 取代並停止隨新版發行；如更新器僅單向複製新增／修改檔案，GitHub 的刪檔可能不會移除 Linux 上的舊腳本。維護人員應先確認新入口 L0 的私有主機結果，再清理已不再使用的舊路徑。原 OFF-3 deploy-check 核心診斷工具繼續保留供工程師使用。
