# SRAF 現有服務唯讀基線（非完整驗收）

目的：針對 PR #319 分離啟動與驗收後的 SRAF，在 **已正常執行的 Linux 主機** 重複觀察三項最小證據。不能重啟、觸發 Report Job、寫入 SQL/ES、呼叫 LLM 或變更設定。

由執行 `run_sra_api.sh` 的相同 Linux 使用者進入已部署的 SRAF repo 根目錄後：

```bash
python tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002
```

完全不發送 HTTP 的版本：

```bash
python tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002 --no-network
```

- **API-LISTENER**：驗證既有 OFF-1S launcher identity、procfs、監聽 socket 與 thread FD owner。HTTP 後再次驗證 **相同 PID、start tick、port、socket inode**；變更即視為未驗證。
- **API-HEALTH**：只在 listener 被驗證後向 numeric IPv4 loopback 127.0.0.1 發出一個匿名、無 redirect 的 `GET /healthz`；重用 OFF-1A 的 3 秒 monotonic 絕對期限及 64KiB body 上限。無法驗證就 SKIP/FAIL，不能推論 LLM/ES/SQL 健康。
- **WORKER-IDENTITIES**：重用 OFF-1H Schedule/Handoff identity 與 /proc 檢查。只證明兩個程序當下的身份，不證明工作已完成。

輸出固定-schema、去識別 JSON：`mode=PARTIAL_ONLY_NOT_ACCEPTANCE`、`feature_acceptance=NOT_TESTED`；不包含 PID、port、IP、根目錄、例外、模型或憑證。三項皆 PASS 時退出碼 0，其餘 2（不是正式驗收失敗）。`loopback_http_attempts` 是探測器呼叫次數，不代表封包確實送達。

建議保存正常負載及已存在高負載期間各一次 JSON 比對；不以診斷為由產生高負載，不主動重啟。這些非原子快照不能確定原 90 秒啟動逾時的根因，也不能認證真實 Agent/LLM/ES、Report Job、DOCX、SQL Server 或封閉網路狀態。

**尚未在私人 Linux 主機實際執行，不能宣稱完成 live acceptance。**
