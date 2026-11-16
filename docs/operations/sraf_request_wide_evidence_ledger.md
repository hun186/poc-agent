# SRAF N 輪智慧檢索：Request-wide Canonical Evidence Ledger（離線契約）

## 必要背景

截至 2026-11-16，SRAF 已有獨立 `AdaptiveRetrievalPlanner`、`RequestAdmissionBudget`，以及單輪 ES → Event/Timeline 日期 → Topic Match → Evidence 的安全契約，但尚未直接把 N 輪檢索併入正式 API／ReportJobWorker。Planner 需要的是跨輪次、去重、具請求層級可信評估的 `RoundEvidenceSummary`，而非單次 ES hit 數或單次 builder 的資料片段數。

本 PR 加入**純程式記憶體** `agent/adaptive_retrieval/evidence_ledger.py`，避免大量重複 ES 候選、同來源重複片段被算成「新增研究證據」。

## 設計

1. `observe_canonical_round`：必須提供本輪實際 ES hits 與同一次查詢的日期、主題群組、effective_terms、原始問句；內部仍呼叫 SRAF 正式 `build_hits_and_evidence`，保留 Event-only、Event ID／block-local 與 Topic Match 驗證。
2. 僅接受有合法 `match_scope=text/meta/mixed`、`match_policy=strict/relaxed/adaptive_two_axis`、`group_hits>0` 的 Evidence。舊式 `fallback_any_term` 與 `fallback_no_terms` **可以計入 Parser 輸出與 fallback 數量，但不能被視為已通過 Topic Match 的研究證據**。
3. 使用原始 ES `(_index,_id)`、nested block 索引、Event IDs、日期、段落 ID、來源 ID 與原文的 SHA-256 安全雜湊產生唯一 Evidence 身分，跨輪次重複、同頁重複不虛增。為支援同文件不同 nested 區塊的正確識別，既有 builder 只在 `include_source_hit_ordinal=True` 的內部選用模式提供 `__sraf_block_index`；公開 Evidence 格式不變。
4. `RequestWideEvidenceLedger` 累計不同 Evidence、不同有效來源、每輪新 Evidence、新來源、Parser fallback 數；最多 8 輪、每輪 1000 ES 文件／4096 Evidence、總計最多 16384 唯一雜湊。輸出 `safe_audit` 只有固定欄位整數與布林，不含文章文字、日期、Event ID、來源 ID、雜湊或原始問句。
5. `RoundEvidenceSummary` 只有在上層**可信協調器**明確確認 request-wide scope、全部預定頁數完成及 coverage assessment 後，才允許推進 Planner。若 incomplete／不具 request-wide 信任／coverage 已足夠，本 ledger 不允許繼續附加下一輪。缺失面向、是否足夠仍需可信研究品質評估，不得僅因文章數量自動宣稱覆蓋充足。

## 非本 PR 功能

- 不呼叫 ES／LLM／SQL／API、不執行搜尋、不啟動排程、沒有資料庫持久化或 Report Job 整合。
- `complete=True` 和 `request_wide_attested=True` **是上層可信 adapter 要負責證明的條件，不是 ledger 可自行查證**；僅通過此離線 API 不表示完整召回、真實檢索權限與來源可信。
- 雜湊身分是為了計數去重，不是可向研究者呈現的引用憑證。未來的完整協調器還必須驗證來源可用性、ES Snapshot/PIT／分頁一致性、傳輸 timeout、30 分鐘檢索上限與 10 分鐘生成保留，並從 canonical Evidence 載入正確 Word 引用。
- Evidence 中的日期精度、UTC offset 與相同 Event IDs 跨區塊關聯仍由原本 parser 管理；這個 PR 不擅自改寫日期、Evidence 內容或新增任何 keyword/LLM 過濾。

## 合成驗收

測試涵蓋兩輪相同／重排資料去重、新來源增加、Event-only、錯日期不借用 Event、同 ID 不同 block 不合併、同 block 重複去重、無關 fallback 不算有效、partial 與 unattested scope 停止、原始來源與問句不得出現在公開稽核紀錄。所有測試都是離線，不代表 Linux L3-A、N-round Job 或正式 ES 查詢完成。
