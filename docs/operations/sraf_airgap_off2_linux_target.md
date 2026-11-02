# SRAF OFF-2 — Linux / Python ABI / ODBC 18 目標相容性盤點

此命令只收集**部分、唯讀**的非敏感目標資訊，以便後續建立離線 Wheelhouse；不安裝套件、不下載、無網路探針、不查 SQL/ES、不重啟服務或執行 Agent/LLM。

在 SRAF 根目錄以**正式 SRAF Python**執行：

```bash
SRAF_PYTHON=/path/to/sraf-venv/bin/python bash run_sraf_airgap_offline.sh target-platform
```

未指定 SRAF_PYTHON 時使用 PATH 中的 python；這個結果可能不是正式 venv 的 ABI 證據。

結果只印到 stdout 一行固定欄位 JSON，**不寫入任何檔案**。從經白名單限制的 Linux ID/版本、CPU 架構、CPython major.minor/SOABI、glibc 或 musl 版本、ODBC Driver 18 的預設設定登錄資訊，協助後續人工鎖定 Linux/Python ABI。輸出不包含主機名稱、IP、登入名稱、檔案路徑、設定值、環境變數、ODBC 驅動實際路徑、帳密或 SQL 連線資料。

僅以 no-follow + 固定上限讀取 /etc/os-release（若為連結可改試 /usr/lib/os-release）及 /etc/odbcinst.ini（最多 16 KiB、32 KiB）。在讀到 ODBC Driver 18 登錄後，額外只允許 `/opt/microsoft/msodbcsql18/lib64/` 下符合 `libmsodbcsql-18.*.so.*.*` 精確版本格式的原生檔案；從根目錄開始逐層以 `O_NOFOLLOW` 檔案描述符開啟，不追蹤任何 symlink，限制為 64 Byte ELF Header 與最大 128 MiB 普通檔案。只核對 ELF64、小端、共用庫與 x86_64／aarch64 Machine Header 相符，不載入 `.so`、不調用動態連結器／ODBC API、不驗證函式庫相依、簽章或版本相容性。不跟隨指定檔案的 symlink，不讀取 .env.local 或 SQL Registry。若 ODBCSYSINI 或 ODBCINSTINI 有環境覆寫，ODBC 登錄會回 CONFIG_OVERRIDE_UNVERIFIED，不能假設預設檔案代表真實配置。

- PASS_PARTIAL / linux_python_target_odbc_elf_header_observed：白名單 Linux、CPU、CPython SOABI、libc 都可讀；預設 ODBC Driver 18 有有效的登錄欄位；而且所指向的供應商目錄內普通檔案 ELF Header 與 CPU Machine 相符。**這僅是 64 Byte Header，不代表 .so 真的可以載入、版本正確、函式庫 ABI 可用、TLS 或 SQL Server 連線成功。**
- INCOMPLETE / odbc18_registration_unverified：核心目標資訊可讀，但 ODBC 18 登錄不可獨立確認。
- INCOMPLETE / odbc18_elf_header_unverified：ODBC18 雖然登錄，但指向非核准目錄、檔名異常、symlink、無法讀取、不支援 ELF 格式或架構不同。不能以登錄成功推論原生函式庫可用。
- INCOMPLETE / target_identity_unverifiable：目標資訊不符合可驗證的 Linux、CPython 或 libc 欄位；不可輸出原始異常值。
- INCOMPLETE / linux_target_required：不是 Linux。
- INCOMPLETE / application_python_unavailable：沒有指定或可用的 Python 環境，未執行任何探針。

odbc_dependency_resolution、odbc_binary_load、wheelhouse_compatibility、full_live 一律 NOT_TESTED，production_release_ready 一律 false。PASS_PARTIAL 僅表示可用於下一階段規畫的本機 OS/Python/ODBC 設定觀察，**不是**數位簽章、相依閉包、封網部署、原生 ODBC 驗收或真實業務 E2E。

可直接複製該行 JSON 供後續審核；**不需要**提供 .env.local、密碼、token、SQL registry、主機日誌或內網路徑。

**2026-11-02 首次實機觀察（用戶提供、不是完整發行證明）：** Ubuntu 22.04、x86_64、CPython 3.10、SOABI `cpython-310-x86_64-linux-gnu`、glibc 2.35、ODBC18 `REGISTERED_CONFIG_ONLY`。該 v1 證據沒有執行 ELF Header 檢查；只有本 PR 合併且部署新腳本後的 v2 重新執行，才能得到 `odbc_binary_header` 實機觀察。不同伺服器／Python venv 需分別盤點，不能假定一致。

### v3：ODBC ELF 動態相依名稱的唯讀解析（不載入、不解決相依）

你提供的 2026-11-02 **v2 實機結果** 已經是 Ubuntu 22.04、x86_64、CPython 3.10、glibc 2.35，且 `odbc_binary_header=ELF64_ARCH_MATCH_HEADER_ONLY`。此結果是單一內網環境的觀察，不代表發行包相容、依賴已可載入或其他機器也符合。

更新到 v3 後，仍使用原本的 `target-platform` 指令。現有 ODBC 18 無符號連結 FD 的 ELF Header 符合架構後，才額外在**同一個唯讀 FD** 上讀取有限的 ELF64 Program Header、PT_DYNAMIC、DT_NEEDED 的字串表引用。最多 64 個 Program Header、64 KiB 動態段、64 KiB 字串表、64 個相依名字；只輸出固定狀態與計數，不輸出或測試任何相依函式庫名稱、磁碟路徑或版本。

- `odbc_dynamic_needed=DT_NEEDED_REFERENCES_PARSED_ONLY` 且計數大於零：僅表示 ELF 內部的動態相依「名稱引用」經過有界檔案內靜態解析。整體依舊只回 `PASS_PARTIAL / linux_python_target_odbc_dynamic_metadata_observed`。
- `odbc_dynamic_needed=DYNAMIC_METADATA_UNVERIFIABLE`：Program Header、不安全/缺失的動態表或字串引用無法完整安全解析，總體回 `INCOMPLETE / odbc18_dynamic_metadata_unverifiable`。
- `odbc_dependency_resolution=NOT_TESTED`、`odbc_binary_load=NOT_TESTED` **永遠保留**。沒有呼叫 ld.so、ldd、dlopen、ctypes、unixODBC、連線或任何執行器，也不保證 DT_NEEDED 依賴在磁碟存在、具有正確版本、可載入或提供合法 ABI。

以上均**沒有實際執行在你的內網機器**，新增的回歸測試使用合成 ELF 和 GitHub Hosted Ubuntu22.04／Python3.10，不能取代下次你自己執行新版本並提供 JSON。
