# SRAF OFF-2：Python 直接相依版本鎖定預檢（純唯讀）

在專案根目錄：

```bash
bash run_sraf_airgap_offline.sh release-deps
```

或直接：`python tools/sraf_airgap_off2_requirements_audit.py`。

僅使用 Python 標準函式庫與既有 OFF-2 本地安全檔案開啟器，透過 no-follow、64 KiB 上限及固定的解析白名單檢查 `requirements.txt`。不使用 pip、不下載、不執行、不安裝、不向任何網路發送請求，也不修改環境或檔案。輸出只含固定原因碼與項目數，不輸出套件名稱、私有路徑、環境變數或依賴內容。

- `INCOMPLETE / direct_versions_unpinned`：仍有 `>=`、`~=` 或 `==1.*` 等未精確鎖定的直接相依。
- `INCOMPLETE / requirement_syntax_unsupported`：遇到 `-r`、URL、VCS、editable、extras、環境 marker、行接續等，不能默默認定已鎖定。這個預檢不是完整的 PEP 508 requirement parser。
- `INCOMPLETE / requirement_input_unverifiable`：輸入缺失、連結、大小／編碼或安全讀取無法確認。
- `PASS_PARTIAL / direct_versions_pinned_only`：**只**代表支援的直接相依行表面上全部採用精確 `==` 版本；不驗證這些版本真可安裝、來源可信、合法完整 PEP 440 版本、平台相容或 transitive closure。

目前 SRAF 既有的 `requirements.txt` 使用開放版本範圍，因此預期此預檢回報 `INCOMPLETE`。它指出下一階段需要真正建立並審核特定 Python/作業系統/架構下的完整 lock file、transitive wheels 和 SHA-256、ODBC 18 native libraries，以及離線可重現安裝和回復試驗；不可直接把現有範圍文字改成猜測版本，也不可把本地即時生成的 hash 當成獨立信任錨。

**驗收邊界**：本工具不驗證整個 bundle 的 Hash/簽章、外部可信 release manifest、wheelhouse、模型、SQL Server、ES、Ollama、Agent、DOCX 或實體封網環境。既有 `release-files` 可信摘要比對與 `release-policy` 選取檢查必須另外執行；三者的 `PASS_PARTIAL` 不能合成 FULL_LIVE／OFF-3／OFF-5 驗收通過。
