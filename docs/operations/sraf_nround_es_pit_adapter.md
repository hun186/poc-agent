# SRAF N 輪：可實際執行 ES PIT 分頁的隔離式傳輸介面（尚未接正式 Job）

## 本 PR 的實作範圍

新增 `agent/adaptive_retrieval/es_pit_adapter.py` 的 `search_fenced_es_round`。
與先前只有離線契約的 `RoundESPageFence` 不同，可信的上層 Worker **明確注入**
已授權 Elasticsearch client 後，這個函式可呼叫 ES 的
`open_point_in_time`、`search`、`close_point_in_time`，
取回同一 PIT 的完整分頁鏈。模組 import **不**連線或初始化 ES。
目前**沒有接上正式 API、ReportJobWorker、OpenWebUI、SQL 或 Word**，
不會默認執行 N 輪檢索，也不代表完成端到端上線。

## 安全限制

1. 強制接收同一份可信 `QueryConstraints` 物件和由上游授權後傳入的
   `authorized_indexes`；索引不在授權範圍時不會連線。**注意：傳入 allowlist
   不等於真正完成 RBAC**；呼叫端仍必須對使用者與租戶權限作獨立驗證，
   且不得採用 LLM 直接給出的 ES index/DSL。
2. 透過現有 `build_main_query_body` 構造具 nested
   `Event.time_iso`／`Event_Timeline.time_iso` 精度保留的候選查詢。
   Event 日期由可信 `constraints.event_date` 固定；新一輪策略只加入
   原有主題下的 *optional/SHOULD* 召回詞，不得改寫日期、索引或必要詞。
   真正合格 Evidence 仍須再經 canonical parser 的日期與 Topic Match 驗證。
3. 第一階段尚不能獨立證明 `fixed_fields`、`required_entities` 與
   `analysis_date` 的硬限制已在 ES DSL 中落實；遇到這些條件將
   **明確拒絕執行**，不能靜默忽略，後續必須實作可信 mapping/驗證才可放行。
   因此目前仍不是完整可供一般用戶使用的 N 輪查詢介面。
4. PIT 開啟也先經 coordinator 的 ES 准入；每次實際搜尋頁面透過
   `RoundESPageFence.begin_page` 取得獨立一次性配額。預設
   `page_size=50`、`max_pages=20`、單次 request timeout 20 秒，
   且每次使用剩餘的 30 分鐘檢索截止額度縮短 timeout。
   取得 `search_after` 後在同一 PIT 接續搜尋，額外
   `_shard_doc` 排序作穩定 tie-breaker。禁止 `ignore_unavailable`、
   `allow_no_indices`、`allow_partial_search_results` 的寬鬆模式。
5. 僅完整、無逾時、無重複來源、無失敗分片且符合所有頁面／來源數上限的
   結果才可透過 `take_complete_hits` 輸出；部分結果一律拒絕，
   `coordinator.cancel()`，並使用固定錯誤代碼不暴露文章、索引、
   PIT ID、例外或機密。PIT close 於 finally 釋放，即使搜尋途中失敗。
6. `FencedESRound.request_wide_attested` 永遠為 `False`。
   一條 PIT 分頁鏈完成，不代表上層整個使用者問題涵蓋、所有策略皆完成，
   更不能自行呼叫 `complete_round(... request_wide_attested=True)`，
   也不賦予 Word/Report Job 的完成或下載授權。

## 待完成事項（尚未上線）

- 對應正式使用者身分的 RBAC／索引／查詢欄位白名單與原始提問之可信
  `QueryConstraints` 映射，包含必須實體、分析日期、固定欄位與其 ES mapping。
- 真實 ES PIT query 的 search_after／mapping／版本差異驗收；
  路徑真實網路 timeout、取消在途呼叫與額外 PIT open/close 的量測。
- 真實 request-wide 覆蓋度／品質評估、已完成輪次 Evidence 與安全去重，
  再整合獨立 LLM Planner（非重跑初始抽詞）與 ReportJobWorker。
- SQLite checkpoint 與 Job owner 綁定、後續 Word 檢索歷程與 OpenWebUI
  雙 Word 連結，以及持久化失敗／中斷後的狀態一致性。

## 目前可執行的離線測試

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_es_pit_adapter.py
```

測試使用注入假的 ES client；可以確認真正呼叫了 client 方法、PIT 延續、
日期與索引邊界、查詢預算、失敗拒絕與 PIT cleanup，但**沒有連線私人 ES**
或執行任何生產 Report Job；不應因此將 N 輪功能標成已啟用。
