# SRAF OFF-2 — 發行政策最小操作入口覆蓋率（唯讀預檢）

在預先安裝完成的 SRAF Python 環境、SRAF 專案根目錄執行：

```bash
python tools/sraf_airgap_off2_policy_coverage.py
```

這個工具只檢查既有 `tools/deployment_manifest_policy.json` 是否**明確列管**目前必要的三個根目錄 Shell 操作入口與六個 OFF-1／OFF-2 Python 入口；用 no-follow 開啟必要檔案，只回傳固定狀態與數量，不列印檔名、路徑、憑證、原生例外，也不修改 Manifest、檔案或服務。退出碼 0 是 `PASS_PARTIAL`，2 是 `INCOMPLETE`。

- `required_operator_tools_unlisted`：至少一個入口尚未納入相應 `managed_files`／`release_tool_files` 明確選擇；`unlisted_count` 表示缺口數量。現有發行政策仍有此缺口；這是預期應被顯示的待辦，不可改以忽略檢查通過。
- `policy_or_tool_unverifiable`：政策內容、大小或至少一個必要入口無法安全驗證；不輸出具體檔名或私有路徑。
- `minimum_policy_selection_only`：政策只達到「九個最低必要操作入口有明確列管」，仍只為 `PASS_PARTIAL`，未檢驗位元組 Hash 或套件內容。

**重要可信界線：**目前政策與必要檔案是*本機唯讀觀察*，本檢查沒有獨立可信 Digest／簽章，也沒有核對發行套件完整性。它不取代 `run_sraf_airgap_off2_verify.sh` 的外部 Manifest pin、`tools/deployment_manifest.py` 的 Git reviewed-commit 契約，也不意味 wheelhouse、Python/native ODBC、models、TLS、SQL/ES/LLM、真實空網環境、OFF-3 全鏈路或 OFF-5 Restore 驗收成功。

這個工具不會自動將缺漏入口加入發行政策，因為修改政策必須另外依 Git-reviewed release manifest 流程重新建立信任，不可把一份本機新建清單當成合法發行包。下一階段應制定完整可重建的發行清單與簽章／依賴鎖，再進行可信套件驗收。
