# SRAF Linux 既有負載／鎖檔拓樸唯讀觀測（OFF-1U）

此工具是**準備實機高負載驗收的被動觀測器**，不是壓力產生器、E2E acceptance、跨 Worker 鎖共享證明或物理氣隙驗收；不讀取密碼、API Key、SQL Registry、環境設定檔，也不發出 HTTP／ES／Ollama／SQL 請求。絕不呼叫 E2E 預檢、建立測試 Job、觸發排程、重啟服務、建立 lock/改寫 lock generation 或進行 DB/ES mutation。

## 在已安裝、已啟動的 Linux SRAF 主機執行

使用 launcher owner 的既有 Linux shell，在實際部署根目錄：

```bash
python tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002 --no-network
python tools/sraf_linux_load_topology_readonly.py --project-root "$PWD" --api-port 9002 --samples 3 --interval 5
```

以上兩者**不進行任何網路請求**。第二條命令觀察已啟動的 API Listener 所屬 Process 3 個時間點的 `rss_mib` 與 `threads`；不讀取 PID、模型名稱、ES URL、儲存路徑或憑證進輸出。允許 `--samples` 2～5，`--interval` 0～20 秒，預設 2 次／1 秒，最多 80 秒觀測。等待期間不製造負載。PID/start tick 和 socket/process ownership 的前後檢核均重用既有 OFF-1S 嚴格實作；若 Process 被替換或資料讀取不可信，丟棄**整組**數值，回報 `INCOMPLETE`。

## 比對現有工作負載與部署差異

可在**既有** Ollama 高負載批次工作執行期間再做一次完全相同的唯讀觀測，將 idle 與 busy 的輸出分開留存於操作者自己的安全管理位置。本工具不會主動製造忙碌狀態，不量測 Ollama token/s、不推論模型 timeout 原因，也不等同伺服器 SDK 取消或報告完成。若要比較實際模型 request latency、Elasticsearch 索引 Mapping／Fixture 恢復、SQL/Word／report job，須另以隔離測試索引、嚴格 TLS、最低權限帳號並經個別授權執行。

輸出是單行 JSON，固定 `schema=sraf_linux_load_topology_readonly_v1`、`mode=PARTIAL_ONLY_NOT_ACCEPTANCE`、`feature_acceptance=NOT_TESTED`。即使 Listener 與 API Process 資源快照可信，`overall` 也只會是 `PARTIAL_OBSERVATION`（exit 0），而非 FULL_LIVE、production_ready 或 airgap PASS。失敗或缺資料為 `INCOMPLETE`（exit 2）。固定網路／憑證／DB／模型／寫入／生成 Process 計數皆為 0。

## 鎖檔與 Worker 判斷的限制

- `API-MOUNT-NAMESPACE=OBSERVED` 只表示**被驗證的單一 API Listener Process** 與觀測 CLI 位於相同 Mount Namespace，不表示所有 Uvicorn/API Worker 相同。
- `LOCAL-LOCK-CANDIDATE=OBSERVED` 只表示 CLI 根據本機 TMPDIR 候選路徑觀察到符合 Owner／0700 Directory／0600 一般檔／單一 hardlink 的鎖檔。只用 `O_RDONLY|O_NOFOLLOW` 開啟**既存**檔案，沒有 O_CREAT、flock 或 read epoch，更不表示 API Worker 一定使用同一 TMPDIR。
- `CROSS-WORKER-LOCK-SHARING` 始終 `NOT_TESTED`；若容器、UID、Mount Namespace、Tempdir 或專案真實路徑不同，PR #328 的 Linux flock + epoch 不能被當成已跨 Worker 驗證。需要各 Worker 自己的受信任身分證據和受控重驗，而不是閱讀其他 Worker 的 `/proc/<pid>/environ`（可能洩漏秘密）。
- 若 OFF-1S 無法驗證 Listener（含多 socket owner 或 procfs 權限限制），不強行透過任意 PID 或 URL 取樣；回報 `SKIP/INCOMPLETE`。這是正確的不確定結果。
- 工具不會送任何 bearer，也不包含或列印內部 exception/PID、UID、host path、port、namespace ID、lock inode 等可能增加攻擊面之資訊。

## 後續仍需明確授權的正式驗收

1. 證明部署容器／全部 API Worker 共享受保護鎖的 canonical project path、UID、temp mount，並測試跨 Worker 的 operator preflight 409 / epoch invalidation；不可拿 CLI 部分快照當作這項證明。
2. 對隔離的 Ollama、LiteLLM/smolagents 和 ES 專用 Fixture 進行經核准的受控忙碌／逾時實測；記錄 request vs whole-operation deadline、SDK 是否可取消、部分 ES create-only 復原，不更動正式生產索引。
3. 另外完成 SQL Version/Schedule/Handoff/Report Job/Agent/DOCX digest 全鏈路驗收、OFF-2～5 和物理氣隙證據。

所有未驗證事項保留在 `.codex/known_issues.md` 與 `.codex/backlog.md`。Hosted CI 模擬 `/proc`、Listener 和鎖檔，不是部署主機觀測成果。
