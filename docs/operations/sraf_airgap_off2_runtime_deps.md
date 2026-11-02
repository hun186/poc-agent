# SRAF OFF-2 — 實際 Python 環境直接相依安裝中繼資料盤點（唯讀）

用途：針對 **真正用於啟動 SRAF 的 Python**，只觀察 `requirements.txt` 中直接相依套件是否有對應的已安裝 Distribution Metadata。這是建置 CPython 3.10 離線 Wheelhouse 前的輔助盤點，**不是**完整版本解析、相依閉包、平台 ABI、原生 ODBC 或 signed release 驗收。

在 SRAF 根目錄執行，優先使用實際 SRAF 的 Python 環境：

```bash
SRAF_PYTHON=/path/to/actual-sraf-python bash run_sraf_airgap_offline.sh runtime-deps
```

未指定 `SRAF_PYTHON` 時使用 `PATH` 的 `python`；所見結果只能代表這個 Python，不代表 Worker 的另一個虛擬環境。

工具採用標準函式庫 `importlib.metadata.distributions(path=...)`，限定目前選取 Python 安裝方案的 `purelib`／`platlib`，不 import FastAPI、pyodbc 或其他目標套件、不執行 entrypoint、不呼叫 pip、無網路、無任何安裝或資料庫/LLM 動作。它透過既有的 bounded/no-follow Reader 讀取專案根目錄 `requirements.txt`，支援最保守的直接需求文字格式（沒有 `-r`、marker、extras、VCS、URL 或行續接），嚴格拒絕重複的正規化名稱。已安裝套件 Metadata 是**一般本機唯讀觀察**，並非受獨立簽章驗證的 provenance，也不能當成未經審核的環境可信證明。

一行 JSON 只報固定枚舉、數字及真假值，不輸出安裝版本、套件名稱、私有路徑、使用者、主機/IP 或憑證。欄位包含 `requirements_checked`、`installed_direct_count`、`missing_direct_count`、`unlocked_direct_count`、`exact_text_matches`。`==` 比對也只對相同版本字串做文字比對，**不**聲稱符合 PEP 440 的完整版本語義。對 `>=`、`~=`、`!=` 等開放條件並**不驗證**實際版本是否滿足。

- `PASS_PARTIAL / direct_distribution_metadata_observed_only`：所有可支援的直接相依在所選 Python 的已安裝 Metadata 都找到，且所有明確的 `==` 版本字串一致。**未做開放條件版本符合性、套件 import、OS/ABI 或遞迴相依驗證。**
- `INCOMPLETE / direct_distribution_metadata_missing`：有一個或多個直接需求在所選 Python 的 `purelib`／`platlib` Metadata 中缺少。
- `INCOMPLETE / exact_direct_version_text_mismatch`：明確 `==` 版本字串不一致。
- `INCOMPLETE / requirements_input_unverifiable`：需求檔缺失、符號連結、過大、編碼或格式不支援。
- `INCOMPLETE / installed_distribution_metadata_unverifiable`：無法安全觀察安裝 Metadata、重複相同正規化名稱、異常版本欄位或分佈總量超過上限。

一律輸出 `transitive_closure=NOT_TESTED`、`wheelhouse_compatibility=NOT_TESTED`、`package_imports=NOT_TESTED`、`production_release_ready=false`。即使 `PASS_PARTIAL`，也沒有取得可攜式 wheels、完整 lock file、venv 可移植性、原生 ODBC/pyodbc ABI、隔離封網安裝或 OFF-5 還原證據。

**2026-11-02 的實機 v3 ODBC 觀察：** Ubuntu 22.04、x86_64、CPython 3.10、glibc 2.35；ODBC 18 ELF 檔案的 `DT_NEEDED` 名稱引用數量為 **10**，但 `odbc_dependency_resolution`、`odbc_binary_load` 仍 `NOT_TESTED`。新 `runtime-deps` 只盤點 Python Metadata，不會驗證上述 10 個原生依賴是否可以連結。
