# SRAF OFF-2 — Python／Uvicorn 啟動入口靜態一致性（唯讀、非實際程序驗收）

## 目的與已知實機背景

2026-11-03，實機以 `runtime-deps-user-site` 取得 `PASS_PARTIAL`：直接套件 METADATA 15/15，其中 sysconfig scheme 13、互動帳號 user-site 2。已辨識 `smolagents` 與 `pyodbc` 的 Metadata 在 user-site，但**不代表正式 API／Schedule／Handoff Worker、Report Job Worker 以同一 Python 或同一帳號／site 設定執行**。

現有 `run_sra_api.sh` 的 API 啟動以 PATH 的 `uvicorn api.main:app`，Schedule 與 Handoff Workers 使用 `python -c`，API lifespan 中另啟動 Report Job Worker。因此需要先區分 PATH 入口一致性及**真實程序驗證（本工具不做）**。

## 使用方法

在 SRAF 根目錄以與原先唯讀 Metadata 診斷相同的 Python／shell 環境執行：

```bash
bash run_sraf_airgap_offline.sh runtime-launchers
```

若指定 SRAF 的 Python：

```bash
SRAF_PYTHON=/path/to/actual-sraf-python bash run_sraf_airgap_offline.sh runtime-launchers
```

此工具由選定 Python 呼叫並進行以下**靜態**檢查：

1. 使用 `shutil.which("python")` 解析目前 PATH 的 `python`，透過 regular-file device/inode 跟 `sys.executable` 比對，不執行可執行檔。
2. 使用 `shutil.which("uvicorn")` 選取 console script。只有在目錄與檔案通過逐層 `O_NOFOLLOW` 且單一 regular-file 大小不超過 64 KiB 時，才讀取 shebang。接受單一絕對直譯器 shebang（不含 flags），或明確的 `#!/usr/bin/env python/python3/python3.10/python3.11` 且由當下 PATH 解析。其餘 shebang、shell wrappers、符號連結／異常來源都以 `UNVERIFIABLE` 等安全狀態處理；不因此啟動任何程序。
3. 另回報選定 Python 的 `site.ENABLE_USER_SITE`、`sys.flags.no_user_site` 與 user-site 是否出現在 `sys.path` 的**布林值**，不是檢查服務帳號的 user-site。

## JSON 與安全界線

`schema=sraf_off2_static_launcher_interpreter_v1`。固定值／布林欄位包括：

- `path_python_identity=MATCH|MISMATCH|UNVERIFIABLE`
- `uvicorn_shebang_identity=DIRECT_MATCH|ENV_MATCH|MISMATCH|UNAVAILABLE|UNVERIFIABLE`
- `selected_python_user_site_active=true|false`
- `api_worker_runtime_verified=false`、`actual_service_uid_verified=false`、`running_process_verified=false`
- `package_imports=NOT_TESTED`、`native_odbc_load=NOT_TESTED`、`production_release_ready=false`

`status=PASS_PARTIAL` 只表示**當下 PATH 的 Python**與選定 Python 的檔案 identity 相同，且所選 Uvicorn console script 的可安全解析 shebang 指向同一個直譯器檔案。否則 `status=INCOMPLETE`。即使 PASS_PARTIAL 也不確認這個 shell 就是啟動服務時的 PATH、程序目前是否仍存活、`uvicorn` 由何種權限執行、API/Worker Python 進程是否不同或是否啟用 user-site。

工具不會產生或回傳真實主機／帳號／PID、執行檔路徑、PATH 字串、shebang 內容、版本、環境變數、服務 Token、`/proc/<pid>/cmdline` 或 `/proc/<pid>/environ`；不呼叫 pip、import smolagents/pyodbc、建立連線、重啟服務、觸發 SQL/ES/LLM 或變更檔案。

如果結果為 `INCOMPLETE`，勿藉此重裝或重啟；先確認是在**正式服務啟動時的同一個 UID、PATH、SRAF_PYTHON／Python venv**下執行。後續正式發行仍需獨立證明完整轉遞鎖定、可信 Wheelhouse、pyodbc/ODBC18 原生載入、SQL TLS、封網安裝與還原和 FULL_LIVE E2E。
