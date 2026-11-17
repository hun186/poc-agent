# SRAF N 輪智慧檢索：Request-local 協調器（離線狀態契約）

## 位置及交付範圍

新增 `agent/adaptive_retrieval/coordinator.py` 的 `AdaptiveRequestCoordinator`，將現有 `RequestAdmissionBudget`、`RequestWideEvidenceLedger`、`AdaptiveRetrievalPlanner` 和 `propose_budgeted_next_round` 串起來。

**這個程式沒有接入正式 API、Report Job Worker、OpenWebUI、SQL 或 ES，也沒有部署 Linux。** 它是一個可透過合成資料驗證的狀態協調器：上層未來的授權 adapter 才能實際搜尋、以同一個 Event／Timeline 日期及 Topic Match 契約把結果交回它，不得宣稱完成正式端到端 N 輪 Job。

## 狀態流程

```text
CREATED
  └─ start()：扣除 round 1 准入額度 → SEARCHING
SEARCHING
  ├─ admit_es_call()：每次外部 ES 請求前扣除 ES 額度（不真的發送請求）
  ├─ complete_round()：至少已有一筆 ES 額度；檢查只含允許索引，
  │     呼叫 canonical Evidence Parser + request-wide Ledger
  │     ├─ 合規完整且尚未足夠 → ASSESSED
  │     ├─ 研究可信評估已足夠 → TERMINAL (SUFFICIENT)
  │     └─ 部分結果、不具 request-wide 驗證／解析錯誤 → TERMINAL
  └─ 額度／時間不足 → TERMINAL
ASSESSED
  └─ plan_next_round() → PLANNING
       ├─ 原子 claim_next_strategy，保留 30 分鐘檢索／10 分鐘生成預算
       ├─ Planner 只提出 *下一輪策略*，不可改寫原始日期／索引／必要實體
       ├─ 成功 admit 下一輪 round → SEARCHING
       └─ 模型異常、無新 Evidence／已足夠／額度不足 → TERMINAL
任何階段
  └─ cancel() → TERMINAL；不再批准新的請求
```

## Evidence 安全契約

- 所有輪次沿用同一份由可信請求處理建立的 `QueryConstraints`（原始問題、Event 日期、允許的索引與固定條件）。原始 `term_groups`、`effective_terms` 也在協調器建立時固定；後續 Planner 只能提出新的**搜尋召回**選用詞，不得自行鬆綁 Evidence 採信門檻。
- ES hit 應含 `_index`／`_id`，且 `_index` 必須存在於原始 `allowed_indexes`。同文件多 Event、Event-only、年／月精度及日期不符仍由原有 canonical parser 處理。Ledger 的來源與片段 SHA 去重，不等於研究人員對來源語義品質的判斷。
- `complete=True`、`request_wide_attested=True` 和 `coverage_sufficient` 是**可信上層協調／人工或品質評估機制**的責任；本模組無從判斷搜尋是否真的涵蓋所有 ES 分頁／PIT、是否有未回傳的資料，不能憑原始 hit 數自動認定。
- `safe_progress()` 只回固定狀態、原因碼、已核准 ES 次數與 Ledger 的數值／布林計數；不輸出來源 ID、原始提問、Event IDs、全文、關鍵詞或去重雜湊。這類摘要是後續 Word「檢索歷程」及 Job progress 的資料契約候選，**但本 PR 尚未把它接到 Word**。
- 只有所有已核准 Round 均完整且 request-wide 合規驗收的特定正常終止條件，才可顯示 `ready_for_external_report_generation=true`。這只是「可由正式報告流程另行評估是否生成」的提示，不表示已執行任何 Word 報告、保存檔案或 L3-A 驗收。

## 嚴格資源與復原界線

- `start()` 前不允許 ES admission；`admit_es_call()` 須在同一 request 預算及當輪狀態中，成功只扣除不可退還的額度。
- `complete_round()` 以鎖把搜尋狀態切成 ASSESSING，避免同一輪結果被另一個執行緒同時入帳；真正的 canonical Parser 在鎖外處理，若期間取消，回來時不得寫回 Ledger。
- `plan_next_round()` 在 PLANNING 階段拒絕同一歷程重複規劃。Planner 若執行很久導致截止，原本的 atomic gate 會拒絕新 round。取消期間就算 LLM 回來也不得把協調器恢復成 SEARCHING。
- `cancel()` **不代表傳輸層真的取消已在執行的 ES／LLM**；正式 Job adapter 還必須設定 timeout、實際取消、同權限檢查、重入時的持久化鎖及明確狀態紀錄。現階段進度 `checkpoint_resume=NOT_IMPLEMENTED`，不能把純記憶體狀態當成可重啟 Job。
- 預設 budget 為 2400 秒總預算、600 秒生成保留，剩餘 1800 秒作為檢索 admission 截止；這不保證最後一個 in-flight ES／LLM 在截止前自行中止。正式 Worker 必須在 SDK / HTTP 層強制 timeout。

## 離線驗收

`tests/test_sraf_nround_coordinator.py` 以合成 ES hit 與假 LLM 驗證：兩輪完成與去重、Event-only／錯 Event 日期、空結果、未完整及未 request-wide 評估、越權索引拒絕、未完成新輪不可 handoff、30 分鐘截止、鎖定關鍵字、模型異常、LLM 期間取消、Parser 期間取消、同輪併發、公開進度隱私與 ES 原子額度。

後續正式路線仍需：授權 ES adapter、PIT／分頁完整性、每輪品質判斷器、Report Job durable checkpoints、重啟／取消／timeout 對帳、引用 Evidence 到 Word、與 OpenWebUI 的非阻塞 Job 連結。以上不屬本 PR 完成項目。


## 2026-11-17：canonical Evidence 評估與 N 輪協調器的單次綁定

`AdaptiveRequestCoordinator.complete_round(...)` 增加完全選用且
**尚未在正式 Worker 啟用**的三個參數：
`coverage_evaluator`、`coverage_witnesses`、`semantic_verifier`。

- 協調器對 ES hit 執行既有的 **同一次** `observe_canonical_round`
  Event／Timeline 日期、主題與來源驗證，再把這份不可變
  `RoundObservation` 交給已綁定相同 `QueryConstraints` 物件的
  `RequestWideCoverageEvaluator`，杜絕「另外解析一遍不同內容」
  的驗證歧異。
- 使用評估器時，協調器會**無條件以實際覆蓋度評估結果取代**
  來自外部的 `coverage_sufficient`、`missing_aspects`，
  不允許呼叫端聲稱 sufficient=True 就繞過來源多樣性與語意缺口。
  評估器不能自行發明 `request_wide_attested=True`；仍須有可信
  全輪查詢與完整分頁的獨立證明。
- 若評估器的 immutable scope 不是當輪原本的同一個物件、證據配對
  失真、未提供可信語意驗證回呼、判定過程取消或出現例外，
  協調器必須在不寫入 Ledger 的情況下轉為終止狀態；不能呼叫 LLM
  補查，也不能把該輪列為已完成可生成報告。
- 舊有無評估器的 `complete_round` 介面暫時保留，供尚未切換的
  隔離測試／相容程式使用；**正式 N 輪 Worker 不得採信舊有呼叫者
  直接傳入的 sufficiency boolean。** 不可單靠新模組就啟用功能。

本階段僅新增資料流契約與回歸測試。尚未有私有 Evidence 回查原文的
語意驗證服務、Job 擁有者 RBAC、完整 ES query-plan completion 証明、
持久化 Job 與 Word 輸出。Linux 端需更新至合併後 main，
才能執行 `tests/test_sraf_nround_coverage_coordinator_bridge.py` 離線驗證。
