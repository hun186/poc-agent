# SRAF OFF-3 — 封閉網路操作員統一入口（目前僅安全唯讀子集）

> **這是現有 OFF-1 與 OFF-2 工具的薄層派送器，不是完整 OFF-3 Acceptance runner，也不代表 OFF-2/4/5 已完成。** 已部署的 SRAF Python 環境必須事先可用，這個腳本不執行 pip、npm、GitHub、ChatGPT、資料庫修改、Agent 生成、重啟、程序終止或還原。

忘記模式與指令時，日常本機六項唯讀快檢請從專案根目錄執行 **`bash 1_完整診斷驗收_SRAF.sh --level L0`**；此模式不連網、不寫檔、不呼叫 SQL／ES／LLM／Report Job。注意統一入口不帶參數的預設是 L1，會進行有界 TCP 與匿名 /healthz；若要完全不連網，請務必選 `--level L0`。既有 OFF-3 `deploy-check` 工程診斷仍可使用，參考 [一鍵落地快檢測](sraf_local_deploy_quickcheck.md)。

進階腳本已移至 `scripts/diagnostics/`，避免擁擠根目錄；在 SRAF 根目錄執行以下工程師模式，也可以從其他工作目錄使用指向完整檔案的絕對路徑：

```bash
bash scripts/diagnostics/run_sraf_airgap_offline.sh deploy-check # 推薦：一次輸出本機安全快檢測，不寫檔、不連網
bash scripts/diagnostics/run_sraf_airgap_offline.sh
bash scripts/diagnostics/run_sraf_airgap_offline.sh quick
bash scripts/diagnostics/run_sraf_airgap_offline.sh diagnose
bash scripts/diagnostics/run_sraf_airgap_offline.sh no-network
bash scripts/diagnostics/run_sraf_airgap_offline.sh release-files
bash scripts/diagnostics/run_sraf_airgap_offline.sh release-policy
bash scripts/diagnostics/run_sraf_airgap_offline.sh release-deps
bash scripts/diagnostics/run_sraf_airgap_offline.sh wheel-files
bash scripts/diagnostics/run_sraf_airgap_offline.sh target-platform
bash scripts/diagnostics/run_sraf_airgap_offline.sh runtime-deps
bash scripts/diagnostics/run_sraf_airgap_offline.sh runtime-deps-user-site
bash scripts/diagnostics/run_sraf_airgap_offline.sh runtime-launchers
```

| 模式 | 唯一執行路徑 | 效果和限制 |
| --- | --- | --- |
| 預設／`quick` | `tools/sraf_airgap_off1_hub.py --suite quick` | 唯讀本地／匿名 API Health/靜態 UI 觀察；**可能開啟本機 HTTP**，但不登入、不觸發 SQL／ES Basic、LLM 或 Report Job；證據寫入既有安全 JSON/TXT |
| `diagnose` | `scripts/diagnostics/run_sraf_airgap_off1_diagnose.sh` | 既有唯讀 API／ES／LLM TCP 及本地 Worker 觀察；不登入、生成或寫 SQL；部分檢查不能視為 E2E |
| `no-network` | `scripts/diagnostics/run_sraf_airgap_off1_diagnose.sh --no-network` | 完全不發起 HTTP/TCP 探針，保留本地資源與可見的 Worker /proc；連線項目正確地 SKIP/INCOMPLETE |
| `release-files` | `scripts/diagnostics/run_sraf_airgap_off2_verify.sh` | 須另以 `SRAF_OFF2_TRUSTED_MANIFEST_SHA256` 提供外部可信 Manifest 摘要；只核對列管檔案 SHA-256，不能推論發行完整性、簽章、模型／wheelhouse |
| `release-policy` | `tools/sraf_airgap_off2_policy_coverage.py` | 本機唯讀核對九個最低必要入口是否被發行政策明確列管；若有缺列則回報 `INCOMPLETE`；現有明確列管已補齊，但也只能回 `PASS_PARTIAL`，**不**驗證簽章、Hash、wheelhouse 或實際 airgap |
| `release-deps` | `tools/sraf_airgap_off2_requirements_audit.py` | 本機唯讀檢查直接 Python 相依是否固定版本；現有 `>=` 應回 `INCOMPLETE`，即使全部 `==` 仍僅為 `PASS_PARTIAL`，不驗證 wheelhouse／ABI／transitive closure |
| `wheel-files` | `tools/sraf_airgap_off2_wheel_files.py` | 需要獨立取得外部可信 Wheel Manifest SHA-256；只核對列管 Wheel 位元組、拒絕未列管檔案；無法證明 Python 依賴閉包、簽章、ODBC 或封網安裝 |
| `target-platform` | `tools/sraf_airgap_off2_linux_target.py` | 只用指定的 SRAF Python 和本機唯讀 OS/ODBC 驅動註冊檔，盤點 Linux 發行版、CPU、Python SOABI 與 glibc；輸出固定清單，不讀憑證或測試原生 ODBC；最多 `PASS_PARTIAL` |
| `runtime-deps` | `tools/sraf_airgap_off2_runtime_deps.py` | 使用所選 Python 唯讀取得直接相依套件安裝中繼資料，僅回報數量及固定狀態；無 pip、import、網路或寫入；不代表需求版本範圍、遞迴相依或 Wheelhouse 相容 |
| `runtime-deps-user-site` | `tools/sraf_airgap_off2_user_site.py` | **明確選用**：在原本 scheme `.dist-info` 未找到的直接相依中，額外唯讀檢查已啟用、且確實出現在 `sys.path` 的 Python user-site。保留分開計數與 `production_release_ready=false`，不等於服務 UID 可用或正式離線部署驗收 |
| `runtime-launchers` | `tools/sraf_airgap_off2_runtime_launchers.py` | **明確選用的靜態環境檢查**：只比較目前 shell PATH 的 `python` 是否與所選 Python 相同、`uvicorn` 安全讀取的 shebang 是否指向相同直譯器，不執行 `uvicorn`／API／Worker 或讀取正在執行程序與 `/proc`；不輸出私有路徑，最多 PASS_PARTIAL |
| `deploy-check` | `tools/sraf_local_deploy_quickcheck.py` | **推薦的一鍵落地快檢測**：在目前 SRAF Python 下整合平台及 ODBC 靜態中繼資料、15 項直接相依 Metadata、Python／Uvicorn 入口、磁碟、現有 Schedule/Handoff Worker 身分及 API 9002 的六項安全前置檢查。免先建輸出目錄、只印摘要與一行可分享的去識別 JSON、不連網、不啟動 Job／服務、不安裝；**不**執行完整 Socket 獨占掃描或宣稱 release-ready |

此統一入口只接受零個或一個固定模式名稱（`--help` 除外），**拒絕** `acceptance`、`upgrade`、`restore`、額外參數與任何探針憑證旗標，不提供由 Quick 自動升級到真正 Job／SQL／ES 探測的方式。需要專用 SQL/ES 授權時，另依既有 OFF-1 原始操作手冊使用明確 opt-in，不能透過統一入口隱式觸發。

`quick`、`diagnose` 與 `no-network` 都保留可選 `SRAF_OFF1_OUTPUT_DIR` 私有絕對路徑及 `SRAF_PYTHON` 的既有應用環境；Python 仍強制 no-follow／0700 目錄與 0600 JSON/TXT 檔案限制。安全輸出位置或環境不符合要求，應如實失敗，禁止自動將證據改存至不安全的暫存路徑。

現階段完成的是 **OFF-3 唯讀模式派送**。正式 Acceptance 仍需要獨立超級使用者授權、隔離 SQL/ES fixture、Schedule/Handoff/LLM/Report Job/DOCX 真實鏈路、明確可恢復狀態及物理封網證據；Upgrade/Restore 也尚未實作，不得聲稱完成。

`release-policy` 不需外部 Manifest pin，僅做本機政策選取檢查；其意義、限制與安全輸出參見 [OFF-2 發行政策覆蓋率](sraf_airgap_off2_policy_coverage.md)。若希望檢查真實列管檔案的可信 SHA-256，仍必須另外執行 `release-files` 並提供外部可信 pin，不得以 `release-policy` 取代。

`release-deps` 的固定狀態與限制參見 [OFF-2 Python 直接相依版本鎖定預檢](sraf_airgap_off2_requirements_audit.md)；絕不可用這項結果代替 `release-files` 的外部 pin 或線下實際安裝／還原驗證。

`wheel-files` 的外部 Pin 格式、Manifest Schema 與安全界線見 [OFF-2 Wheelhouse 位元組驗證](sraf_airgap_off2_wheel_files.md)。所有缺少信任錨的情況均回 `INCOMPLETE`，不得自動產生本機 PIN。

`target-platform` 只觀察執行腳本當下的 Python ABI 與 Linux/ODBC 登錄配置，不會收集完整套件/ODBC 原生 library 版本，也不是封網或實機業務 E2E。使用與正式 SRAF 相同的 Python 環境，例如 `SRAF_PYTHON=/path/to/venv/bin/python bash scripts/diagnostics/run_sraf_airgap_offline.sh target-platform`；詳細欄位與安全界線見 [OFF-2 Linux 目標環境盤點](sraf_airgap_off2_linux_target.md)。

`runtime-deps` 的操作方式與證據界線見 [OFF-2 Python 直接相依安裝中繼資料盤點](sraf_airgap_off2_runtime_deps.md)。

若 `runtime-deps` 只在 user-site 有缺項，使用獨立的 `runtime-deps-user-site`；**不會悄悄擴充預設的 scheme-only 驗證**。詳情見 [OFF-2 runtime-deps 操作文件](sraf_airgap_off2_runtime_deps.md)。

`runtime-launchers` 只代表執行當下 shell PATH 與可驗證 `uvicorn` 腳本的靜態比對；即使 PASS_PARTIAL 也 **完全不代表** 執行中的 API／Schedule/Handoff/Report Job 程序使用相同 Python、UID 或 user-site，也沒有驗證套件匯入與原生 pyodbc。詳見 [OFF-2 runtime launcher 靜態比對](sraf_airgap_off2_runtime_launchers.md)。

**一般日常部署快檢測請優先用 `deploy-check`**，不是先跑多項手動 Python heredoc。當專案位於共享掛載、既有 `quick`/`no-network` 報告路徑因安全上層目錄而回 `output_dir_unverified` 時，`deploy-check` 仍能直接用終端機完成唯讀診斷，且不會更改既有 report 的 nofollow／0700 保護。它保留原 `quick`／`diagnose` 模式相容性；使用方式及輸出範圍見 [一鍵落地快檢測](sraf_local_deploy_quickcheck.md)。
