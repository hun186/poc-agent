# ARC A8 Evidence 語意複查離線契約

此階段只實作 `agent/es/evidence_core/arc_semantic_review.py` 的批次選取、提詞與回傳解析，不呼叫 LLM，不接入正式檢索、授權、排序、證據刪除或報告生成。可信呼叫者未來必須從同次最終 canonical Evidence 中提供私有 source-hit ordinal；本模組不自行證明日期/來源/owner 授權。

- 僅 strict、正文/混合/metadata 命中且有合法 source-hit ordinal 的完整片段。原始順序前 64 筆中交替觀察弱/強候選，每個來源 hit 最多一筆，最多 8 筆，每筆 1500 字元，合計 12000 字元。超長片段略過，不截斷語意；此為偏向診斷的局部樣本，不是隨機樣本，也不能據此推論全體相關率。
- 輸入重用 A2b 原問題與群組限制，序列化最多 64000 bytes；每筆只傳暫時批次 ordinal 和正文。不傳來源 ID、UUID、段落 ID、日期 metadata 或 DSL，但原問題及正文自身仍可能包含敏感資訊。payload 是私有內容，不可記錄或保存。
- 只允許 relevant / uncertain / unrelated。回傳須完整覆蓋每個批次 ordinal 恰好一次，拒絕重複 JSON keys、缺項、額外欄位、未知 verdict、非整數 ordinal、超過 4096 字元；失敗整批不採信。
- 對外僅產生計數、prefix 限制及模型 unrelated 與正文必要主體/既有 strong 的衝突數，不傳 row-level verdict 或來源定位。不論模型如何分類都不刪除、改序或提升 Evidence；uncertain 不當作 unrelated。
- 後續 transport gate：明確的 operator opt-in、經授權的資料/模型端點及資料出境政策、同次最終 Evidence 綁定、ARC 共享 LLM/掃描/時間/token/bytes 預算、無重試、E2E 與深度 owner scope 隔離、輸入/輸出與 backend log 隱私審查。深度既有 trusted semantic assessor 仍維持原本授權和 coverage contract，不能用此批次結果取代。
- 驗收：先跑 synthetic 契約測試，然後在私有相同快照對照人工標註的 relevant/uncertain/unrelated、誤淘汰率、必要主體保持、來源多樣性、p95 與 token 負載。尚未實機測試或核准啟用。
