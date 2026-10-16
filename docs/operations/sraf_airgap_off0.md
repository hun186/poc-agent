# SRAF Air-Gap OFF-0 — 盤點、驗收契約與實作邊界

> 工作追蹤：[Issue #290](https://github.com/hun186/poc-agent/issues/290)。本文件與 [機器可讀檢查清單](sraf_airgap_off0_checks.v1.json) 只是 **OFF-0 規格基線**，不是已完成的離線一鍵驗收工具。Product API P2.2 仍獨立開發。

## 一、何時收集與何時整合

**現在開始盤點和積累，不等所有功能完成才收集。**

1. OFF-0 設定每個檢查的唯一 ID、來源、執行模式、權限與副作用；目前這些欄位放在 JSON 契約中。先確立不可互相冒充的證據類型。
2. OFF-1 逐項補上真正的依賴檢查（SQL/ES/LLM/OS 等）與故障模擬測試；只增加小而有界的 probe，不建立另一個 Agent/Worker。
3. OFF-2 把完整部署包、所有離線原生套件、模型、索引/資料與配置操作納入受檢清單；增量更新必須另有來源與目標基線驗證。
4. OFF-3 才正式提供一個可執行的統一入口；OFF-4 加上標準報告及中文操作手冊；OFF-5 做真實封閉網路移機與故障注入。各階段可重複使用前階段的成果。

## 二、現有程式盤點（不重複造輪子）

| 現有路徑／界面 | 可重用的能力 | 限制與整合動作 |
| --- | --- | --- |
| `shared/runtime_provenance.py`、`REQUIREMENT_E2E_PROVENANCE.json` | release 管理檔案的雜湊、載入模組與選定配置的可信度檢查 | 不把 Git HEAD 當成部署成功；manifest 所列檔案要驗證實際位元組；部署地祕密 SQL registry 故意不披露 |
| `tools/requirement_e2e_provenance.py`、`tools/deployment_manifest.py` | Git anchored manifest 生產/驗證工具 | 建包端可能需要 Git，不可假設斷網主機可存取 GitHub；執行端用封存的可信 manifest 自查 |
| `run_sra_api.sh`、`config/deployment_bootstrap.py` | 受監管的 API、Schedule/Handoff 起停與部署憑證 bootstrap | 可能重啟進程或改寫保護狀態；**Quick/Diagnose 絕不能執行 launcher/bootstrap 來「檢查」** |
| `sra_api/routers/operator_e2e.py` | 已登入 superuser 可讀的 Runtime Evidence / DOCX 領取，支援 worker 身分和 artifacts | 需要已有的 superuser user-session Bearer；不可把 Service Key 當作有同等權限 |
| `operator_e2e/test_requirement_schedule_e2e.py`、`operator_e2e/requirement_e2e_support.py` | 既有來源驗證＋SQL/排程/Handoff/真報告/DOCX 核驗，並寫入結果 JSON | **會建立/更新 fixture、啟動排程、觸發工作、清理/停用排程**；只能在 Acceptance 且明確授權下執行 |
| `agent/external_capabilities.py` | ES Mapping checker、實際 ES/LLM probes、獨立 FULL_LIVE/HYBRID/OFFLINE 分類 | `prepare_requirement_elasticsearch()` **會建立/寫入**測試索引，不能拿來做唯讀健康檢查；`offline` 是測試替身，不是正式生產離線推論 |
| `sra_api/routers/requirement_tasks.py`、`tests/test_requirement_product_api.py` | Product API P2.1 查詢/Preview 及 FastAPI 模擬測試 | pytest ≠ 真實 SQL/服務；Task/Run 清單為空不能冒充實資料詳情與跨帳號 RBAC |
| `operator_e2e/p21_api_smoke.py`（先前在部署主機人工使用） | 使用者已跑過 13/13，包含核准 Profile 及三筆 Excel Preview | **目前 Hosted main 找不到該檔案**；應先正式版控、審核及避免日常檢查自動登入／寫入 Auth audit |
| `operator_e2e/test_phase0_api_routing_evidence.py` | Phase-0 API 身分／授權與 Service Key 行為驗證 | 需額外許可與測試身分，先盤點實際副作用，再納入 Acceptance |

**已發生、可供規格設計參考的觀察（不是 OFF-0 新執行的測試）：**
- 在使用者的 Linux 部署主機，PR #288 P2.1 API Smoke 得到 13 PASS、0 FAIL、0 SKIP，使用核准 XLSX Profile Preview 3 accepted/0 rejected。
- P2.1 focused pytest 先得到 64 PASS、1 FAIL；有一個 URL-encoded 表單的 HTTP 400/422 測試預期錯誤，已有 PR #289 提案，尚未 Merge；用 `-k` 排除該案例的執行結果是 64 PASS、1 deselected。
- 既有三筆 Requirement E2E 在使用者提供的執行紀錄中完成 3/3 產出、DOCX 與 SHA-256 PASS。該紀錄不能代替新環境的 FULL_LIVE、SQL 競爭、ES Mapping、斷網重建或品質驗收。
- 前述觀察不可被 OFF-0 規格檔自動轉換為最新部署的 PASS。

## 三、執行模式與副作用矩陣

| 模式 | 允許的操作 | 禁止的操作 | 人員準備 |
| --- | --- | --- | --- |
| `quick`（預設，無參數亦採用） | 本地檔案雜湊、硬體/空間/時鐘、API GET/health、無憑證匿名權限負測 | 登入、Task/SQL 變更、模型推論、E2E、啟動/重啟/殺除程序、修改設定/索引 | 不應需要管理員密碼；對不可驗證者明示 SKIP |
| `diagnose`（唯讀） | 已授權的 SQL SELECT、ES GET/ping/mapping、模型與工作程序 metadata、帶現有 bearer token 的 API GET | 任何 migration、索引建立/寫入、模型推論、登出/重新登入、Report Job 建立、啟停 Workers | 允許獨立授權 Session；**禁止把 Token 寫入報告或記錄** |
| `acceptance`（明確選用） | 隔離測試資料集及明確限定的 E2E；可進行模型推論、經許可的 fixture 匯入/清理、產物生成 | 未授權的生產資料更新、默默更換 ES 索引、跨帳號存取、將 mock 當 FULL_LIVE | 事前列出會寫的資源、fixture ID、權限／影響範圍、可復原方式、測試模型、封閉網路准入 |
| `upgrade`（未規劃為 OFF-0 runner） | 另由安全更新流程處理預檢、備份、變更與復原 | 從任何唯讀模式隱式觸發 | 單獨維運 SOP |

機器可讀清單的 `readiness=existing_component` **僅指既有程式有可重用能力**，不代表 OFF-3 runner 已存在或該現成函式可直接在 Quick 執行。尤其 `initialize()`、`prepare_requirement_elasticsearch()`、`run_sra_api.sh` 的副作用須在整合時避開。

### HTTP Auth 稽核例外

`POST /v1/auth/login` 有登入稽核/節流寫入，不能宣稱完全唯讀。Quick 只做不需登入的項目；Diagnose 需要登入態資料時應使用既有有效 user-session token，否則報 `SKIP(auth_session_unavailable)`，**不得私自呼叫登入**。若正式 Acceptance 設計要新增登入測試，需標明安全稽核副作用。

## 四、統一輸出契約與故障歸因

預定輸出一份 bounded JSON 和一份人員易讀報告，檢查記錄包含：
`check_id`、`component`、`status`（PASS/FAIL/WARN/SKIP）、`severity`、`error_code`、`summary`、`evidence`、`remediation`、`dependency`、`duration_ms`。

約束：

- `PASS`：真實 probe 執行且滿足明確條件；**「程式存在」、「HTTP route registered」、「mock PASS」與「有資料的正常寫/讀流程」不同**。
- `FAIL`：已執行且有可重現的失敗證據；使用穩定代碼（如 `mapping_incompatible`、`sql_unreachable`、`worker_identity_unverified`），不可把祕密例外訊息原樣回傳。
- `WARN`：已執行但屬可用性/容量/可觀測性風險，不可遮掩重大安全失敗。
- `SKIP`：因模式不允許、沒有資料/憑證、前置依賴未過或檢查尚未實作；報告要列確切原因，**絕不能當 PASS**。
- 若 `ES-02` Mapping 失敗，`ES-03` 應 SKIP，`RUN-01` 依賴的 FULL_LIVE 驗收亦 SKIP，而不是形成一串假的連鎖 FAIL。
- `OFFLINE` / `HYBRID` / `FULL_LIVE` 是外部依賴證據分類，不等同 quick/diagnose/acceptance 的執行模式；斷外網但使用真實內部 ES+LLM 才有資格朝 FULL_LIVE 判定。

### 機器可驗證的輸出白名單（Codex P2 修正）

- JSON Registry 的 `report_policy` 有固定 schema，不允許 `allow_raw_exceptions=true`、`allow_unstructured_evidence=true`、私自加上停用脫敏的 root 欄位，或擴增未核准的 Evidence Key。
- `tools/validate_sraf_airgap_off0_contract.py::make_report_record` 是預定 OFF-3/4 報告產生器必須使用的**唯一安全紀錄建構邊界**：`summary` 取已審查的檢查標題，`remediation` 取已審查的處理指引，`error_code` 只能為該檢查預定代碼或固定系統代碼。
- `evidence` 僅接受 12 欄以下白名單數值/布林/64 位 SHA-256/固定 FULL_LIVE-HYBRID-OFFLINE 分類；未知 Key、路徑、Bearer、連線字串、原始例外與任意字串皆拒絕，**不能先原樣序列化、再試圖事後把秘密遮掉**。
- **Codex 第二輪 P2 防護**：報告 `title` 長度最多 96 字元、`remediation` 最多 200 字元，拒絕換行/控制字元、URL、明顯祕密欄位（如 `Password=`、`Token=`）、Bearer、Traceback、典型系統絕對路徑等；`error_code` 僅可使用小寫英數底線，最長 64 字元；`component` 也有格式/長度約束。以上用於報告的靜態文案仍必須經 GitHub 程式碼審查，不可讓執行期錯誤文字代入。
- 契約 CLI 針對 JSON 語法錯誤及 Python 3.11 超長整數解析採固定錯誤碼 `contract_json_invalid`，不印出 Traceback 或原始輸入。
- 目前只有安全輸出建構函式和回歸測試，**還沒有 OFF-3 統一 Runner/報告檔輸出功能**。之後每個真實 probe 只能將經過安全分類的數值交給此邊界；不得直接 `json.dump(exc/response/headers/logs)`。
- 依賴圖已將 `WORK-01` 連到 `PKG-01`：Runtime Evidence 需要已通過的 provenance，若來源驗證失敗，Worker 只能 `SKIP(blocked_by_dependency)`，不可產生誤導的第二個故障。

### 日誌及敏感資料最小化

不得在報告中出現登入密碼、Token、Session、密鑰、SQL connection string/registry 內容/路徑、報告全文、使用者個資、未授權 SQL 查詢、私有模型提示、原始 Excel 內容。來源身份以安全的雜湊/版本/代碼表示；長文字和例外設長度上限。報告放在獨立、權限受控的工作區，預設不自動上傳任何服務；失敗時不直接打包整份主機日誌。

## 五、斷網與離線部署完成門檻

第一次移機必須交付**完整可重建部署包**：原始程式/可執行依賴、Python wheelhouse/locked versions、OS native/ODBC libraries、模型權重與雜湊、必要內網服務版本/配置/索引/遷移手冊、憑證分離與核發流程、受控測試資料及驗收工具。後續既有 BAT 可保留增量更新用途，但必須有安全底版、變更清單、原子套用/復原與目標系統驗證；不能只用檔案 mtime 當成 Git 內容差異。

**OFF-0 的完成條件**是規格與盤點經審查、19 個檢查 ID/模式/依賴可機器解析且沒有環狀依賴；**尚不是**全環境健康檢查程式、Full Live 驗收或正式離線移機完成。

## 六、下一個可獨立合併的小階段：OFF-1

優先實作 **唯讀** `PKG-01`、`SYS-01`、`ENV-01/02`、`API-01`、`SQL-01/02`、`ES-01/02`，每個 probe 都要有 timeout、穩定錯誤代碼、假服務/錯誤注入回歸測試和禁止副作用驗證。LLM 推論 `LLM-02`、ES 真實檢索 `ES-03`、完整 `RUN-01` 應保持在授權 Acceptance。P2.2 不因 OFF-1 排程受阻。

### 第三輪安全界線補強（2026-10-15）

- 報告的 `title` 與 `remediation` 不僅限制長度、敏感關鍵字與路徑，還必須與 `tools/validate_sraf_airgap_off0_contract.py` 中的**已審查固定文字白名單**逐字相同；不能從改寫的 registry 靜默引入新文字。未來正式修改文案必須同時修改受審程式及測試。
- 報告文字會拒絕 Unicode 控制/格式字元及行、段分隔符 U+2028/U+2029，也涵蓋 `client_secret=`、`access_token=` 等常見鍵名與一般 Unix 絕對路徑。驗證是 fail-closed，不能視為能安全輸出任意使用者原始字串。
- 契約 JSON 只可從常規檔案的已開啟 descriptor 讀取，不跟隨 symlink；採非阻塞開啟，**實際只讀最多 256 KiB + 1 byte**，拒絕特殊裝置與超大內容，不依賴可競爭的預讀檔案大小。深層巢狀資料引發的 `RecursionError` 與過大整數等解析錯誤都歸類為固定 `contract_json_invalid`，不輸出 Traceback。
- 以上只保護 OFF-0 契約檔的驗證及安全紀錄建構函式。正式 Runner 尚未實作，不能宣稱系統已具備完整報告脫敏與離線診斷能力。

### 第四輪報告語意與 JSON 相容性修正（2026-10-16）

- **完整清單是成功條件**：不允許只留下 18/19 項甚至更少仍回報 OFF0_CONTRACT PASS；驗證器強制檢查完整 19 個已審查的 Check ID，若缺少則使用固定碼 `contract_incomplete_check_inventory`。
- **FAIL／SKIP 不可交換**：FAIL 必須回報該檢查專屬的真實失敗代碼；SKIP 只能使用 `blocked_by_dependency`、`check_not_implemented`、`auth_session_unavailable` 或 `mode_not_enabled`；WARN 只能為專屬警示代碼或不帶代碼。禁止把「因依賴失敗未執行」假裝成真正功能失敗。
- **版本無關的 JSON 深度限制**：在 `json.loads` 前，使用不解析字串內 `[]{}` 的掃描器拒絕超過 128 層巢狀結構；不依賴 Python 3.10～3.14 的遞迴行為。惡意過深 JSON 固定回報 `contract_json_invalid`，正常 JSON 字串內的括號不影響深度。
- 以上屬於 OFF-0 規格與 safe record constructor 的回歸防護，不代表正式封閉網路 Quick/Diagnose/Acceptance Runner 已完成。

### 第五輪 Review：未實作項目不可偽裝成已執行（2026-10-16）

- 若 Check 的 `readiness=planned`，報告產生器只允許 `status=SKIP` 且 `error_code=check_not_implemented`；即使被要求標記 FAIL、WARN、PASS，或用 `blocked_by_dependency` 等其他 SKIP 理由，都必須拒絕。不能對從未執行的探測器報告故障或警告。
- 已有可重用元件的 Check 仍可在未來真正執行後回報檢查專屬 FAIL/WARN；**此欄位並不代表 OFF-3 統一 Runner 已完成或這些檢查已在目標主機執行**。

### 第六輪 Review：實作狀態不能由 JSON 自我升級（2026-10-16）

- `readiness` 原先只需符合合法列舉，可能透過修改 JSON 將 `SYS-01` 由 `planned` 偽裝成 `existing_component`，再產生假 PASS。現在在程式中明確維護 19 項的 `APPROVED_CHECK_READINESS`，逐一與契約 JSON 對照，失配時拒絕並回傳 `contract_check_readiness_unapproved`。
- 未來 OFF-1 的真實 probe 實作完成時，必須經程式碼審查並同步修改固定實作狀態與測試；改一份外部 JSON 不構成實作或驗收。此防護只涉及 OFF-0 靜態契約，不代表已完成實機診斷。
