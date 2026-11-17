# SRAF N 輪：固定查詢計畫執行與完整性證明（隔離階段）

## 緣由

Linux 已完成 N 輪協調器、ES PIT adapter、分頁完整性、Evidence 覆蓋度
與 checkpoint 的 100 項離線測試。然而之前的
`search_fenced_es_round` 只證明**單一 PIT 分頁鏈**完整，
無法排除上層漏掉某個預定 ES 查詢分支，就把部分結果誤當整輪。

本工項建立 `agent/adaptive_retrieval/round_query_execution.py`：
`FrozenSingleQueryPlan` 只支援 SRAF 目前既有的
**一條 canonical main query**，固定從原始 `QueryConstraints`
及協調器確實核准的第二輪策略組成，不接受使用者或 Planner 自選的
ES DSL、索引、日期，也不允許假裝包含第二條隱藏查詢。

## 成功條件

- 每輪一次性 claim，拒絕在同輪已經執行其他未列入計畫的 ES IO
  之後，再宣稱這是唯一 canonical 查詢。重複呼叫同一或另一份
  manifest 都不能繼續花費 ES/LLM 額度。
- claim 另外核發**不公開的同輪執行權杖**；PIT open 和每一個
  `search_after` 分頁扣預算時，都必須帶相同權杖。
  claim 後即使另一段程式試圖直接透過舊 ES adapter 執行（未帶
  權杖），也必須立即標記 `UNTRACKED_QUERY_ADMISSION` 並中止
  目前執行中的 canonical 查詢；不可繼續回報 query_plan_complete。
  未 claim 的舊離線單輪測試仍沿用不帶權杖的既有路徑。
- 使用既有 `search_fenced_es_round` 真正執行受信任 client
  注入的 Elasticsearch PIT open → 全部分頁 search_after → close。
  每次 ES 開啟與分頁照舊由 request-local 預算及分頁完整性閘門控制。
- 僅當 PIT adapter 已回傳
  `complete_page_chain=True`、`failed=NONE`、
  與目前 round 相符、頁面數有效、已接受的來源數與實際 hit 數一致，
  且 coordinator 仍在該輪 SEARCHING 時，才輸出
  `CompletedSingleQueryRound(query_plan_complete=True)`。
- 若任一頁被拒、缺少 PIT、分片不全、逾時、close 失敗、重複執行、
  分頁回覆不一致：永不回傳局部 Evidence，取消協調器的後續准入。
  只公開固定理由碼，不帶出 PIT、文章、查詢、Index 或憑證資訊。
- 公開 `safe_audit` 只有分頁數、來源數、固定狀態與「未接 Report Job」。
  所有私人 hit 只在函式回傳給可信的記憶體上層，並非可公開報告。

## 嚴格限制

`query_plan_complete=True` **只代表目前固定的一條
canonical main query 及它的所有 PIT 分頁完整**。
不代表所有可能 ES 策略、使用者問題的所有子題、所有必要實體、
ES 查詢真實授權、Event 語意關係與 Evidence 內容都已充分。
因此 `CompletedSingleQueryRound.request_wide_attested`
永遠是 `False`，不能直接拿來呼叫
`coordinator.complete_round(request_wide_attested=True)`；
未來必須由可信 Worker 完成整個使用者需求的查詢計畫及語意覆蓋驗證後
才可給出正式的 request-wide attest。

本工項未修改正式的單輪 API、Report Job Worker、SQL、
私人 ES 設定、OpenWebUI 或 Word。是否由可信 Worker 確認
該題真的只需這一條查詢分支，以及 RBAC、必要欄位 mapping／分析日期，
依然是後續明確的開發要求；不得藉此提前將 N 輪設為預設啟用。

## 部署及離線驗證

當 PR 已通過最新 CI、Codex Review 並合併到 main，才使用 Windows
打包 7z 的方式增量部署 Linux。執行：

```bash
cd /mntCZJ/TopicClassification/poc-agent
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_round_query_execution.py \
  tests/test_sraf_nround_es_pit_adapter.py \
  tests/test_sraf_nround_es_page_fence.py \
  tests/test_sraf_nround_coordinator.py
```

測試只有合成 ES client，不會連線私人 ES／LLM／SQL，
不觸發 Report Job／Word，不代表真實 N 輪端到端驗收。
