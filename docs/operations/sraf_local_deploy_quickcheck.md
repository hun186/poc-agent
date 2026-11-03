# SRAF 落地部署一鍵快檢測（Local Deploy Quickcheck）

## 目的

原本 SRAF OFF-1／OFF-2 已有安全、逐項的唯讀檢測器，但操作員在 Linux 上不得不持續複製貼上不同的 Python 指令，且既有 `quick`／`no-network` 為了把報告寫到安全目錄，可能在共享掛載下因 `output_dir_unverified` 提早停止，沒有產出真正需要的 API／Worker 診斷。

本工具把**已審閱的同一批既有探測器**整合成**一次執行、一次回報**，無需寫入報告目錄，也不取消任何原本的安全約束。它是已運作的 SRAF 系統之「安全本機快檢測」，**不是完整 airgap 驗收或 Release Gate**。

## 唯一推薦指令

```bash
bash run_sraf_airgap_offline.sh deploy-check
```

使用既有的 SRAF Python；確實需要指定直譯器時：

```bash
SRAF_PYTHON=/path/to/actual-sraf-python bash run_sraf_airgap_offline.sh deploy-check
```

這個模式不會要求你先逐項執行 `runtime-deps-user-site`、`runtime-launchers`、Worker Identity Python heredoc，或 API Socket 前置檢查。所有檢查會依序執行；即使單項 `INCOMPLETE`，仍收集其他安全可執行項目，並以固定、去識別化的狀態回報。

## 6 個本機唯讀檢查

| 項目 | 重用既有功能 | 可確認什麼 | 不代表什麼 |
| --- | --- | --- | --- |
| `target_platform` | OFF-2 Linux Target `observe()` | Linux、Python ABI、ODBC18 登錄與 ELF/DT_NEEDED 中繼資料是否可安全讀取 | ODBC 本機動態載入或 SQL TLS 已成功 |
| `direct_distribution_metadata` | OFF-2 `runtime-deps-user-site` | 指定 Python 的直接相依 METADATA 總數、scheme 與已啟用 user-site 來源分開計數 | 需求版本範圍滿足、匯入成功、transitive closure、可信 Wheelhouse |
| `static_launchers` | OFF-2 `runtime-launchers` | 當下 shell 的 PATH Python／Uvicorn 啟動腳本是否指向同一個環境 | 正在執行的 API/Worker Python、venv、UID、user-site 一定相同 |
| `host_disk` | OFF-1 Disk Probe | 本機磁碟預設最低空間門檻 | 全部產出／儲存目的地容量均足夠 |
| `worker_process_identity` | OFF-1H Canonical Worker Identity | Schedule／Handoff 兩個已記錄程序的 PID 重用防護、角色、啟動時間、有效 UID、工作目錄一致性；只輸出計數 | Worker 已成功認領任務或 Agent/LLM/Handoff 結果完整 |
| `api_listener_preflight` | OFF-1S 6 個既有函式 | API9002 根路徑／啟動記錄、程序身份、單一 IPv4 監聽資訊、記錄 PID 擁有該 Socket、/proc 非過濾前置條件 | **完全沒有執行**全程序 Socket 獨占性及最後重驗；不是 OFF-1S 正式 API Listener 身分證明 |

所有欄位都會保留 `production_release_ready=false`、`full_live_acceptance=NOT_TESTED`。即使六個本機項目都可觀察到，最高只能回 `PASS_PARTIAL`；有缺項、警告、失敗則 `INCOMPLETE`，不杜撰成功或猜測原因。

## 範例輸出格式

以下僅為**輸出格式示意，不是真實機器的測試結論**：

```text
SRAF LOCAL DEPLOY QUICKCHECK | PASSIVE NO-NETWORK NO-WRITE
target_platform=PASS_PARTIAL reason=target_platform_metadata_observed
direct_distribution_metadata=PASS_PARTIAL reason=all_direct_metadata_observed_only
static_launchers=PASS_PARTIAL reason=current_shell_launcher_identity_only
host_disk=PASS reason=disk_threshold_met
worker_process_identity=PASS_PARTIAL reason=recorded_schedule_handoff_process_identity_only
api_listener_preflight=PASS_PARTIAL reason=six_api_listener_prerequisites_observed_only
RESULT=PASS_PARTIAL production_release_ready=false
SRAF_DEPLOY_CHECK_JSON={...}
```

只需要分享最後一行 `SRAF_DEPLOY_CHECK_JSON=` 就能取得摘要；不需貼全套內網參數或進程資訊。JSON 只包含固定狀態、布林和已驗證的有限計數，不會包含 PID、命令、路徑、帳號、憑證、私有 IP、套件名稱／版本或原始異常文字。

## 不應混淆的安全界線

- 不發出 HTTP/TCP、SQL/ES/LLM 呼叫，不啟動 Agent／Report Job／Scheduler，不重啟、不殺死程序、不安裝套件，不寫入任何診斷檔；只用標準輸出。
- OFF-1S 前置條件通過仍只能 `PASS_PARTIAL`；絕不會因為 `_exclusive_socket_owner` 未執行就推導 API Listener 全部驗證通過。真正需要正式 API Listener 排他證據時，應由已授權的嚴格驗證流程個別執行，不會在日常快檢測中隱式啟動全域程序／執行緒 FD 掃描。
- 之前 `no-network` 的 `output_dir_unverified` 是當時**安全報告目錄無法使用**，不是 Worker 故障。這個新模式不呼叫 `_secure_output_dir`，也不放寬既有報告目錄的逐層 no-follow、0700 檢查。
- `PASS_PARTIAL` 不代表實際 `smolagents`、`pyodbc` 匯入、ODBC18 Native Load、可信 transitive cp310 Wheelhouse、SQL/ES TLS 與憑證、Report Job 完整業務鏈、OFF-4 升級、OFF-5 還原或物理封網。
- 舊的 `quick`／`diagnose`／`no-network` 保持不變，留給有安全輸出目錄、且需要擴充報告或匿名 API 檢查的操作；新模式是日常的優先入口。
