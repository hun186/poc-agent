# SRAF OFF-2 — Linux / Python ABI / ODBC 18 目標相容性盤點

此命令只收集**部分、唯讀**的非敏感目標資訊，以便後續建立離線 Wheelhouse；不安裝套件、不下載、無網路探針、不查 SQL/ES、不重啟服務或執行 Agent/LLM。

在 SRAF 根目錄以**正式 SRAF Python**執行：

```bash
SRAF_PYTHON=/path/to/sraf-venv/bin/python bash run_sraf_airgap_offline.sh target-platform
```

未指定 SRAF_PYTHON 時使用 PATH 中的 python；這個結果可能不是正式 venv 的 ABI 證據。

結果只印到 stdout 一行固定欄位 JSON，**不寫入任何檔案**。從經白名單限制的 Linux ID/版本、CPU 架構、CPython major.minor/SOABI、glibc 或 musl 版本、ODBC Driver 18 的預設設定登錄資訊，協助後續人工鎖定 Linux/Python ABI。輸出不包含主機名稱、IP、登入名稱、檔案路徑、設定值、環境變數、ODBC 驅動實際路徑、帳密或 SQL 連線資料。

僅以 no-follow + 固定上限讀取 /etc/os-release（若為連結可改試 /usr/lib/os-release）及 /etc/odbcinst.ini（最多 16 KiB、32 KiB）。不跟隨指定檔案的 symlink，不讀取 .env.local 或 SQL Registry。若 ODBCSYSINI 或 ODBCINSTINI 有環境覆寫，ODBC 登錄會回 CONFIG_OVERRIDE_UNVERIFIED，不能假設預設檔案代表真實配置。

- PASS_PARTIAL / linux_python_target_and_odbc_config_observed：白名單 Linux、CPU、CPython SOABI、libc 皆可讀，預設 ODBC 登錄有名為 ODBC Driver 18 for SQL Server 的非空 Driver 設定。**不代表實際 .so 存在、可載入、可連線或符合 ODBC ABI。**
- INCOMPLETE / odbc18_registration_unverified：核心目標資訊可讀，但 ODBC 18 登錄不可獨立確認。
- INCOMPLETE / target_identity_unverifiable：目標資訊不符合可驗證的 Linux、CPython 或 libc 欄位；不可輸出原始異常值。
- INCOMPLETE / linux_target_required：不是 Linux。
- INCOMPLETE / application_python_unavailable：沒有指定或可用的 Python 環境，未執行任何探針。

odbc_binary_load、wheelhouse_compatibility、full_live 一律 NOT_TESTED，production_release_ready 一律 false。PASS_PARTIAL 僅表示可用於下一階段規畫的本機 OS/Python/ODBC 設定觀察，**不是**數位簽章、相依閉包、封網部署、原生 ODBC 驗收或真實業務 E2E。

可直接複製該行 JSON 供後續審核；**不需要**提供 .env.local、密碼、token、SQL registry、主機日誌或內網路徑。
