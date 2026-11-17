# SRAF N 輪智慧檢索：ES 分頁完整性邊界（離線契約）

## 交付內容

`agent/adaptive_retrieval/es_page_fence.py` 為尚未接入正式 Report Job 的 ES 分頁資料檢查器。建構時需要協調器保留的原始 `QueryConstraints` **相同物件**，且必須正在指定輪次的 `SEARCHING`。

外部受授權 adapter 必須先取得 `begin_page()` 票據，才有此層認可的 ES admission；每張票由協調器扣除不可退還的一次 ES 呼叫額度。adapter 依票據內的 search_after、原始索引、日期、固定欄位和原始必要實體組成 DSL，執行真實 ES IO；本模組 **沒有執行 ES、建 DSL 或驗證 RBAC**。未來要從可信 adapter 證明這些義務。

`submit_page(ticket, response)` 只接收固定的 ES 原始結果格式：完整分片（successful=total、failed=0，且 skipped 已包含在 successful 計數內，不另外相加）、沒有 timed_out、命中索引在原始白名單、`_id` 和 `_source` 合法、每頁大小有上限、全鏈來源 ID 不重複。滿頁須再請求下一頁，只有收到短頁或空頁才能認定本鏈結束。滿頁必須帶合法 sort cursor，不能沿用先前 cursor。每輪最多 1000 hits；超出會中止，不得裁切後稱為完整資料。

驗證失敗、逾時、異常來源、重複 ID、額度或分頁數用盡，一律取消未來協調器准入，禁止將部分資料送進生成流程。提交回應時還會查詢檢索截止時間；這不能取代外部 HTTP timeout 或 SDK 取消正在執行中的請求。

`take_complete_hits()` 一次性取出通過分頁收集條件的 hits，交給上層使用原有 Event／Timeline 日期驗證、Topic Match、Evidence Ledger 和可信 coverage 判斷。**僅完成一條分頁鏈，絕對不等於整個使用者問題已涵蓋，也不自動設 `request_wide_attested=true`。** 特別是查詢若有多個分流、不同索引或不同檢索策略，仍必須由可信 Worker 確認全部完成。

`safe_audit()` 僅顯示輪次、完成頁數、來源數、固定失敗代碼與 `request_wide_attested=false`；不輸出原文、來源 ID、游標或原始問題。

## 限制與後續串接

- 沒有接正式 Agent／Worker／ES／OpenWebUI／SQL Server／Word；不代表正式 N 輪功能上線。
- 不知道 ES 真實伺服器是否遵守 search_after 或 PIT；trusted adapter 必須校驗並保留同一查詢/PIT 語意、禁止越權。
- 目前是 **單一策略的序列分頁**，尚未涵蓋多索引並列查詢與多策略組合。
- 未實作跨程序 checkpoint；與 PR #449 的 SQLite sidecar 契約仍需由後續 Worker 連接。
- 超時／未完整頁面只能停止，不能把既有局部結果假裝完整。
- 後續才把這個資料鏈的完成結果接入協調器 `complete_round()`，再由正式 Report Job 生成第二份 Word 與安全下載連結。

## 離線測試

`tests/test_sraf_nround_es_page_fence.py` 利用假 ES response 測試兩頁／滿頁後空頁、partial shards、timed_out、錯誤索引、同頁／跨頁重複來源、游標不動、超過 1000 hits、取消、錯誤票據、截止時間與併發 admission。CI 在 Python 3.10 與 3.11 驗證，**並非真實 ES E2E**。
