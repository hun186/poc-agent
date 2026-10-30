# SRAF Ollama/LiteLLM 等待診斷 — 共用 call_llm 的安全耗時紀錄

## 背景

2026-10-30，操作者指出 SRAF 在大量 LLM 批次作業執行時曾啟動/生成報告變慢，而暫停重負載後又恢復。OFF-1U 實機取得短時 SRAF API RSS 202.5 MiB／70 threads（低負載）與 199.3 MiB／70 threads（高負載），都只是 API process 部分觀測；OFF-1W 在 SRAF container 未找到 Ollama process，後續確認 Ollama **運行於另一個 container**。以上支持共享 LLM 服務競爭的假說，但 **尚未證實 GPU 排隊、Ollama 內部 queue、VRAM 飽和或任何具體 timeout 根因**。

## 範圍

本增量僅修改現有 `agent/llm_utils/ollama_client.py::call_llm` 的傳輸周邊低敏感度計時與錯誤分類，並由既有 caller 傳入受白名單約束的 stage。**不新增 API endpoint、不改 timeout 數值、不改 retry/併發設定、不建立佇列/新 Job、不連線模型做開發測試、不改普通 production 或 E2E 的成功／失敗契約。**

- 固定 stage 僅允許 `router`、`query_refiner`、`report`、`pure_llm`；未知或不合法輸入一律標 `unspecified`。
- 成功時 `logger.info` 記 `[llm_call] stage=... outcome=success category=none elapsed_sec=... requests_timeout_sec=...`；單次總等待 >=30s 改 `logger.warning`，以便一般 warning 級別日誌能觀察長時間等待。
- 傳輸或 JSON 解碼失敗以 `logger.warning` 記 `outcome=error` 和有限分類：`connect_timeout`、`read_timeout`、`transport_timeout`、`connection_error`、`request_error`、`http_429`、`http_503`、`http_4xx`、`http_5xx`、`http_error`、`invalid_response`、`unexpected_error`。只有錯誤類別，不記錄 exception message/URL、完整 traceback、Prompt、模型名稱或回應內容。
- DEBUG_CALL_LLM 預設 OFF；即使使用者明確設成 `DEBUG_CALL_LLM=1`，現在也**僅在 INFO level 記 system_chars/user_chars**，不再輸出任何 Prompt preview。
- `requests_timeout_sec` 表示傳入 Requests 的 timeout 設定（非串流 Request 的 socket 等待語意），**不是絕對的 whole-call monotonic deadline**。未由 caller 指定時記 `default`，不猜測實際 client 設定。
- `elapsed_sec` 是在進入共用 `client.chat()` 到結束或例外之間觀察到的單次**阻塞牆鐘耗時**；不包含整份 Report 的 ES/SQL/Word／DataAgent smolagents 行程。不具備 first-token timestamp，無法將 queue wait、模型載入、生成分離。HTTP 503/429 只代表服務層回應，**不能**直接判定 GPU/Ollama 已排隊。
- `agent/data_agent/builder.py` 的 `smolagents.LiteLLMModel` 不經這個共用 `call_llm` 路徑，仍未有相同 telemetry；任何整份報告階段結論需將此缺口標示為 NOT_MEASURED。
- 失敗仍沿用既有 `RuntimeError("llm_runtime_failure")` 或經授權 E2E live 的 `RuntimeError("e2e_live_llm_runtime_failure")`，不將逾時轉成空字串假成功、不自行重試；分類日誌不代表真正 provider cancellation。

## 使用與判讀

部署更新且日誌器支援 Python logging INFO/WARNING 的 SRAF 後，在正常工作/既有經核准的大量 LLM 批次工作期間**觀察既有日誌**中 `[llm_call]` 項目即可。不要新增 LLM inference 流量作診斷。

例（僅解釋欄位的示意，不是實機觀測）：

    [llm_call] stage=router outcome=error category=read_timeout elapsed_sec=120.025 requests_timeout_sec=120.0

若大量長時間 `outcome=success`，只表示請求的總阻塞時間增加；若 `http_503`，可能是服務忙碌，但仍需 Ollama Server 端排程、GPU 和容器診斷另行佐證。持續在報告中區分「observed timing」與「inferred queue」。

目前所有新測試均為 synthetic `requests`/fake Client，Hosted CI 不接觸私有 Ollama、ES 或 SQL，不能證明 Linux 實機等待行為或模型首 token 進度。下一輪才考慮對獨立 `LiteLLMModel` 觀測和受控的 Report Job status；不得先加入全域佇列、任意 sleep/retry 或直接修改 Ollama queue 設定。
