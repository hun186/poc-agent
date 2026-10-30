# OFF-1V — 安全離線比較 SRAF Linux 正常／既有高負載觀測

本工具是 OFF-1U 的**離線數值整理器**，只讀取兩份既有的 JSON 快照，驗證它們都符合 `sraf_linux_load_topology_readonly_v1` 的**部分觀測**契約，計算 RSS MiB 與 API Process 執行緒數的描述性差異。

不連線到 API/Ollama/ES/SQL、不進行模型推論、不產生額外負載、不讀取憑證、不修改原始檔案、不啟動/重啟任何服務，也不建立 E2E 工作。**不能**由兩份快照證實同一台主機、同一 PID、同一 Uvicorn Worker、相同採樣間隔、使用者所稱的「忙碌」狀態、共同鎖檔或模型超時原因。

## 準備已核准的原始觀測資料

在既有 Linux SRAF 主機使用相同工具參數，分別在自然正常負載及**已經存在**的忙碌工作期間進行唯讀觀測。以下僅示範操作者自行保存命令標準輸出，不主動製造工作負載：

```bash
python tools/sraf_linux_load_topology_readonly.py --project-root "$PWD" --api-port 9002 --samples 3 --interval 5 > idle.json
# 只有在已經有其他核准的高負載工作時才執行第二次觀測
python tools/sraf_linux_load_topology_readonly.py --project-root "$PWD" --api-port 9002 --samples 3 --interval 5 > busy.json
python tools/sraf_linux_load_compare_offline.py --idle-file idle.json --busy-file busy.json
```

輸入檔由操作者自行保存於權限受控位置。OFF-1V 只使用 `O_RDONLY|O_NOFOLLOW|O_NONBLOCK` 讀取既有單硬連結的一般檔案，且限制每檔最多 **32 KiB**。拒絕符號連結、特殊檔案、過大輸入、重複 JSON Keys、NaN/Infinity、未知欄位或不符合 OFF-1U 契約的狀態。所有輸入錯誤皆以固定的 `snapshot_invalid` 類別輸出，不回顯檔案路徑、內容、例外或任何憑證。

## 輸出及解釋

輸出為固定的單行 JSON，`schema=sraf_linux_load_compare_offline_v1`、`mode=PARTIAL_ONLY_NOT_ACCEPTANCE`、`feature_acceptance=NOT_TESTED`。成功讀入兩份**均為 PARTIAL_OBSERVATION**、具有相同樣本數（每份 2–5）的快照時，`overall=DESCRIPTIVE_COMPARISON`，exit 0。此成功**不代表**效能改善、Ollama/ES timeout 排除、真正的 FULL_LIVE 或高負載測試合格。任何輸入不符、資料不足或樣本數不同，`overall=INCOMPLETE`、`comparison=null`，exit 2。

數值欄位只包含兩側每次 RSS 平均 MiB、busy 減 idle 的差值與百分比、兩側觀測樣本的最高執行緒數及差值；沒有 CPU/GPU 使用率、模型 token/s、HTTP 延遲、ES Mapping 或報告成功率。比較器不會從觀測數值反推「忙碌造成了某種失敗」。

- `comparability=UNVERIFIED_CROSS_RUN_IDENTITY` **永遠維持**，因 OFF-1U 的去識別化 JSON 不含可互相驗證的 Host/Process 身分、觀測時間或 workload marker。兩次觀測可能是不同 API Process。
- `cross_worker_lock_sharing=NOT_TESTED` 及 `ollama_es_timeout=NOT_TESTED` **永遠維持**。只有另經核准的多 Worker／Ollama／ES 實測才能回答。
- 樣本數不同會拒絕數值比較；樣本數相同**不能**證明實際時間間隔相同，請操作員手動用相同參數與可信紀錄確認。
- 如果任一原始 OFF-1U 快照為 `INCOMPLETE` 或 Listener 已變更，OFF-1V 必須拒絕統計，不得「補上」假成功。
- 只使用原始快照輸出的去識別化數值，不輸出輸入檔名、OS path、port、PID、UID、host、lock epoch、model URL 或任何原始 JSON 字串。

## 尚未完成的部署驗收

實際部署的 OFF-1U idle/busy JSON 尚未產生；Hosted CI 使用虛構的**測試 fixture** 驗證輸入拒絕與數值計算，不能作為真實 SRAF 效能數據。全體 Worker 共用的 canonical lock path/TMPDIR/UID/mount namespace、Ollama LiteLLM SDK timeout、ES 專用 fixture 的 create-only 部分寫入恢復、SQL/Handoff/Agent/DOCX 的端到端驗證，仍需另取得實機操作許可。

本工具沒有新增任何 HTTP API 或生產端依賴。
