# OFF-1W — Ollama 候選程序被動資源取樣（Linux procfs）

OFF-1U 先前已在實機成功取得 SRAF API 低負載 202.5 MiB / 70 threads、既有高負載 199.3 MiB / 70 threads，各 3 筆。這是 API Process 資源的局部觀測，不能推論 Ollama/GPU/SDK timeout 根因。

## 操作者指令

在原本已運作的 Linux/Ollama 主機且程式已部署的專案內：

    python tools/sraf_ollama_proc_passive.py --samples 3 --interval 5

在既有、另經核准的忙碌批次工作期間，可以使用**相同參數**再執行一次。操作員自行安全保存兩份輸出；OFF-1V 僅能解析 OFF-1U API schema，**不能**解析 OFF-1W。

## 觀測方式及驗證界線

- 工具只遍歷當前 PID Namespace 可見、最多 20,000 個 Linux procfs 數字目錄，讀取每個程序的少量 comm 名稱；固定只比對 ollama 或截斷形式 ollama_llama_se。最多 16 個候選。只讀取符合名稱的程序少量 status/stat 數字。不讀取 cmdline、environ、token、工作目錄、模型/權重、GPU 資料或其他 Process 的 FD。
- 名稱比對只是**候選**，不是 Ollama Endpoint 身分認證，可能被其他 Process 偽裝。服務在另一個容器/PID Namespace 時可能完全不可見。不要為了提高可見性改權限、掛載 host procfs 或重啟服務。
- 每筆輸出候選數量、RSS sum MiB、Threads sum、相對第一筆的程序 CPU 累計秒差。RSS 的 sum 可能重複計算共享記憶體，不是物理 RAM 或 VRAM；CPU 秒數不是牆鐘經過時間、負載百分比、token/s、首 token 延遲或請求逾時。
- 每次採樣前及結尾重新掃描程序集合和啟動時間，任何 Process churn、不穩定指標、候選過多/不見、讀取失敗會清空所有數值並回報 INCOMPLETE/exit 2。
- 完全**不發 HTTP**（不查 Ollama /api/ps，也不呼叫 /api/generate 或 /api/chat）、不觸發模型推論、不發 SQL/ES 請求、不建立子程序、不建立鎖檔、不寫磁碟或更動任何既存服務。
- 單行 JSON 固定 schema=sraf_ollama_proc_passive_v1, mode=PARTIAL_ONLY_NOT_ACCEPTANCE, feature_acceptance=NOT_TESTED，可能 overall=PARTIAL_OBSERVATION/exit 0；這只是候選程序採樣成功，絕非模型服務身分/延遲、跨 Process 覆蓋、FULL_LIVE 或封閉網路驗收。
- GPU、真正 Ollama 請求 latency、timeout、模型身分、候選完整性及報告 E2E 均標示 NOT_TESTED，且不輸出 PID、host、model、UID、socket 或 raw procfs。
- 建議正常與忙碌工作都採樣並以人工確認當時服務和工作負載，再獨立考慮受控的 request-level timing 診斷；不能從程序指標推斷因果。

Hosted CI 使用合成 /proc fixture，不是實機 Ollama/GPU/ES 成果；需操作者部署後的兩組正常/忙碌結果。
