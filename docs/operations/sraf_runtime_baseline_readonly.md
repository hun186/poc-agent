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

## 2026-11-17：高負載 FD churn 時的匿名健康檢查

Linux 實機上 PR #453 的單次補掃已確認部署；新診斷連續三次
都在第一次、第二次全域 FD 掃描發生 `fd_disappeared`。
每次需檢查數十萬個執行緒 FD，不能把完整掃描的間歇性失敗
推斷為 API 不能回應，也不能因此放寬有憑證請求的安全閘門。

為了**分別**提供匿名 HTTP 可達性與嚴格 Socket 身分證明，
新增明確 opt-in 的 `--independent-anonymous-health`：

```sh
cd /mntCZJ/TopicClassification/poc-agent
PYTHONDONTWRITEBYTECODE=1 python tools/sraf_runtime_baseline_readonly.py \
  --project-root "$PWD" --api-port 9002 --independent-anonymous-health
```

此選項僅在已有合法 Linux root/port 驗證後，允許獨立執行
OFF-1A 現有的 numeric 127.0.0.1、匿名、無重導向 `GET /healthz`
（3 秒絕對期限、64KiB 上限）。不需要任何憑證，也不傳送 bearer。
如果 OFF-1S 前置 Listener 檢查不通過，
`API-HEALTH=SKIP` 和 `API-LISTENER=SKIP` **仍維持原判**；
只有新增的 `API-HEALTH-ANONYMOUS` 可能獨立得到
`PASS/anonymous_healthz_http_200_unattributed`，僅表示該 Port
對匿名 GET 回應 HTTP 200，**不**表示可把回應歸屬於 launcher
紀錄所指 API 程序，更不表示具備任何認證／Report Job 權限。

`--no-network` 仍優先，任何模式都不會送出 HTTP。
不指定新選項時，原有行為、三個檢查名稱與 v1 schema 不變；
指定後採 v2 schema，並只多出一個明確標示匿名且不可歸屬的
檢查結果。`overall` 仍要求原來的嚴格證明成功，不會因
匿名 200 而變成 PASS；所有外部服務、LLM、SQL/ES、正式報告驗收
仍是 NOT_TESTED。不能拿此結果解除 OFF-1S 的 bearer 安全閘門。

後續獨立執行 SQL、ES 的唯讀驗收與 N-round pytest；
不要靠無限制地增加掃描重試次數，將高負載主機轉成額外的 CPU 壓力。
