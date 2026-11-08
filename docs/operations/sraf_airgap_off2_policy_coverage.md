# SRAF OFF-2 — 發行政策最小操作入口覆蓋率（唯讀預檢）

在預先安裝完成的 SRAF Python 環境、SRAF 專案根目錄執行：

```bash
python tools/sraf_airgap_off2_policy_coverage.py
```

這個工具只檢查既有 `tools/deployment_manifest_policy.json` 是否**明確列管**目前必要的三個根目錄 Shell 操作入口與六個 OFF-1／OFF-2 Python 入口；用 no-follow 開啟必要檔案，只回傳固定狀態與數量，不列印檔名、路徑、憑證、原生例外，也不修改 Manifest、檔案或服務。退出碼 0 是 `PASS_PARTIAL`，2 是 `INCOMPLETE`。

- `required_operator_tools_unlisted`：至少一個入口尚未納入相應 `managed_files`／`release_tool_files` 明確選擇；`unlisted_count` 表示缺口數量。以本次已更新、經 Review 的發行政策執行應不再缺列上述九個入口；舊版或部署缺檔仍必須顯示 INCOMPLETE，不得忽略。
- `policy_or_tool_unverifiable`：政策內容、大小或至少一個必要入口無法安全驗證；不輸出具體檔名或私有路徑。
- `minimum_policy_selection_only`：政策只達到「九個最低必要操作入口有明確列管」，仍只為 `PASS_PARTIAL`，未檢驗位元組 Hash 或套件內容。

**重要可信界線：**目前政策與必要檔案是*本機唯讀觀察*，本檢查沒有獨立可信 Digest／簽章，也沒有核對發行套件完整性。它不取代 `scripts/diagnostics/run_sraf_airgap_off2_verify.sh` 的外部 Manifest pin、`tools/deployment_manifest.py` 的 Git reviewed-commit 契約，也不意味 wheelhouse、Python/native ODBC、models、TLS、SQL/ES/LLM、真實空網環境、OFF-3 全鏈路或 OFF-5 Restore 驗收成功。

這個工具不會自動將缺漏入口加入發行政策，因為修改政策必須另外依 Git-reviewed release manifest 流程重新建立信任，不可把一份本機新建清單當成合法發行包。下一階段應制定完整可重建的發行清單與簽章／依賴鎖，再進行可信套件驗收。

## 受控政策更新（2026-11-01）

目前發行政策已新增三個根目錄 Shell 腳本至 `managed_files`，六個既有診斷／發行檢查 Python 模組至 `release_tool_files`，皆以**明確路徑**列管（不是遞迴將整個 `tools/` 視為可信）。
`tools/deployment_manifest.py` 仍強制要求 source 與 independently reviewed manifest commit 的政策 **Git blob 完全一致**；任何更早版本的 package/receipt/manifest 不會因為修改政策而自動變為新版本可信。發行者必須先完成獨立 Review，使用相符的已審核 Commit，另建立完整套件並產生可信 manifest digest，再透過既有驗證流程檢驗。

**仍未完成**：全面依賴閉包、模型權重／pip wheelhouse／ODBC native library、真正的檔案套件完整性、簽章及公開可信 pin 傳遞、封網實機業務 E2E、OFF-5 Restore。不能用 `release-policy` 的 `PASS_PARTIAL` 宣稱它們完成。
