# SRAF 進階部署與離線診斷腳本

## 平常只需要一鍵快檢

在 **SRAF 專案根目錄** 執行 `bash 1_完整診斷驗收_SRAF.sh --level L0`。這是純本機、唯讀、無網路、無輸出檔的六項被動觀察；中文報告與末行 `SRAF_DIAGNOSTICS_JSON=...` 可供現場維護。即使得到 `PASS_PARTIAL`，**也不是正式 FULL_LIVE、空網安裝或 Release 驗收**。

## 僅供工程師明確選用的進階入口

以下指令均從 **SRAF 專案根目錄** 執行：

```bash
bash scripts/diagnostics/run_sraf_airgap_offline.sh --help
bash scripts/diagnostics/run_sraf_airgap_offline.sh deploy-check
bash scripts/diagnostics/run_sraf_airgap_offline.sh quick
bash scripts/diagnostics/run_sraf_airgap_offline.sh diagnose
bash scripts/diagnostics/run_sraf_airgap_offline.sh no-network
bash scripts/diagnostics/run_sraf_airgap_offline.sh release-policy
bash scripts/diagnostics/run_sraf_airgap_offline.sh release-deps
bash scripts/diagnostics/run_sraf_airgap_offline.sh release-files
```

`quick`（不帶模式時的舊預設）與 `diagnose` **可能進行本機匿名 HTTP/TCP 觀察並寫入受保護的報告資料夾**，和一鍵 `deploy-check` 完全不同；`release-files` 需要另一可信管道核實的 Manifest SHA-256；`wheel-files` 也需要獨立可信 Wheel 摘要。**不會因整理資料夾而取消任何輸出路徑、憑證、檔案或允許參數的驗證。**

直接呼叫進階工具時，路徑現在是：

```bash
bash scripts/diagnostics/run_sraf_airgap_off1_diagnose.sh --no-network
bash scripts/diagnostics/run_sraf_airgap_off2_verify.sh
```

`run_sraf_airgap_off1_diagnose.sh` 的 `--probe-sql-read` 與 `--probe-es-tls-mapping` **會明確啟動有授權的唯讀遠端探針**；只在取得授權、審閱原本的 [OFF-1 操作說明](../../docs/operations/sraf_airgap_off1_hub.md) 後使用。不可在 `--no-network` 下偷啟用它們。離線檢測子模式與安全界線見 [OFF-3 模式手冊](../../docs/operations/sraf_airgap_off3_runner.md)，發行檔案的外部 pin 規則見 [OFF-2](../../docs/operations/sraf_airgap_off2_provenance.md)。

### 搬遷相容性

舊的 `bash run_sraf_airgap_offline.sh ...`、`bash run_sraf_airgap_off1_diagnose.sh ...` 和 `bash run_sraf_airgap_off2_verify.sh` **根目錄路徑已移除**。若有外部部署排程、自訂指令或腳本直接呼叫舊路徑，請先更新為 `scripts/diagnostics/...`；**不提供與整理目的衝突的根目錄隱藏轉接腳本**。正式 API 啟動 `run_sra_api.sh` 不變；日常診斷已統一為 `1_完整診斷驗收_SRAF.sh`，純離線使用 `--level L0`。根目錄舊 `0_一鍵快檢_SRAF.sh` 已停止隨版本發行，但單向增量同步的部署主機可能仍殘留；請先確認新 L0，再由維護人員進行一次性舊檔清理。
