# SRAF OFF-3 — 封閉網路操作員統一入口（目前僅安全唯讀子集）

> **這是現有 OFF-1 與 OFF-2 工具的薄層派送器，不是完整 OFF-3 Acceptance runner，也不代表 OFF-2/4/5 已完成。** 已部署的 SRAF Python 環境必須事先可用，這個腳本不執行 pip、npm、GitHub、ChatGPT、資料庫修改、Agent 生成、重啟、程序終止或還原。

在 SRAF 根目錄執行；也可以在其他目錄用絕對路徑呼叫：

```bash
bash run_sraf_airgap_offline.sh
bash run_sraf_airgap_offline.sh quick
bash run_sraf_airgap_offline.sh diagnose
bash run_sraf_airgap_offline.sh no-network
bash run_sraf_airgap_offline.sh release-files
```

| 模式 | 唯一執行路徑 | 效果和限制 |
| --- | --- | --- |
| 預設／`quick` | `tools/sraf_airgap_off1_hub.py --suite quick` | 唯讀本地／匿名 API Health/靜態 UI 觀察；**可能開啟本機 HTTP**，但不登入、不觸發 SQL／ES Basic、LLM 或 Report Job；證據寫入既有安全 JSON/TXT |
| `diagnose` | `run_sraf_airgap_off1_diagnose.sh` | 既有唯讀 API／ES／LLM TCP 及本地 Worker 觀察；不登入、生成或寫 SQL；部分檢查不能視為 E2E |
| `no-network` | `run_sraf_airgap_off1_diagnose.sh --no-network` | 完全不發起 HTTP/TCP 探針，保留本地資源與可見的 Worker /proc；連線項目正確地 SKIP/INCOMPLETE |
| `release-files` | `run_sraf_airgap_off2_verify.sh` | 須另以 `SRAF_OFF2_TRUSTED_MANIFEST_SHA256` 提供外部可信 Manifest 摘要；只核對列管檔案 SHA-256，不能推論發行完整性、簽章、模型／wheelhouse |

此統一入口只接受零個或一個固定模式名稱（`--help` 除外），**拒絕** `acceptance`、`upgrade`、`restore`、額外參數與任何探針憑證旗標，不提供由 Quick 自動升級到真正 Job／SQL／ES 探測的方式。需要專用 SQL/ES 授權時，另依既有 OFF-1 原始操作手冊使用明確 opt-in，不能透過統一入口隱式觸發。

`quick`、`diagnose` 與 `no-network` 都保留可選 `SRAF_OFF1_OUTPUT_DIR` 私有絕對路徑及 `SRAF_PYTHON` 的既有應用環境；Python 仍強制 no-follow／0700 目錄與 0600 JSON/TXT 檔案限制。安全輸出位置或環境不符合要求，應如實失敗，禁止自動將證據改存至不安全的暫存路徑。

現階段完成的是 **OFF-3 唯讀模式派送**。正式 Acceptance 仍需要獨立超級使用者授權、隔離 SQL/ES fixture、Schedule/Handoff/LLM/Report Job/DOCX 真實鏈路、明確可恢復狀態及物理封網證據；Upgrade/Restore 也尚未實作，不得聲稱完成。
