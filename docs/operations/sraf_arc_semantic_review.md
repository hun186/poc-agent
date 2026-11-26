# ARC A8 Evidence 語意複查離線契約

此階段只實作 `agent/es/evidence_core/arc_semantic_review.py` 的批次選取、提詞與回傳解析，不呼叫 LLM，不接入正式檢索、授權、排序、證據刪除或報告生成。可信呼叫者未來必須從同次最終 canonical Evidence 中提供私有 source-hit ordinal；本模組不自行證明日期/來源/owner 授權。

- 僅 strict、正文/混合/metadata 命中且有合法 source-hit ordinal 的完整片段。原始順序前 64 筆中交替觀察弱/強候選，每個來源 hit 最多一筆，最多 8 筆，每筆 1500 字元，合計 12000 字元。超長片段略過，不截斷語意；此為偏向診斷的局部樣本，不是隨機樣本，也不能據此推論全體相關率。
- 輸入重用 A2b 原問題與群組限制，序列化最多 64000 bytes；每筆只傳暫時批次 ordinal 和正文。不傳來源 ID、UUID、段落 ID、日期 metadata 或 DSL，但原問題及正文自身仍可能包含敏感資訊。payload 是私有內容，不可記錄或保存。
- 只允許 relevant / uncertain / unrelated。回傳須完整覆蓋每個批次 ordinal 恰好一次，拒絕重複 JSON keys、缺項、額外欄位、未知 verdict、非整數 ordinal、超過 4096 字元；失敗整批不採信。
- 對外僅產生計數、prefix 限制及模型 unrelated 與正文必要主體/既有 strong 的衝突數，不傳 row-level verdict 或來源定位。不論模型如何分類都不刪除、改序或提升 Evidence；uncertain 不當作 unrelated。
- 後續 transport gate：明確的 operator opt-in、經授權的資料/模型端點及資料出境政策、同次最終 Evidence 綁定、ARC 共享 LLM/掃描/時間/token/bytes 預算、無重試、E2E 與深度 owner scope 隔離、輸入/輸出與 backend log 隱私審查。深度既有 trusted semantic assessor 仍維持原本授權和 coverage contract，不能用此批次結果取代。
- 驗收：先跑 synthetic 契約測試，然後在私有相同快照對照人工標註的 relevant/uncertain/unrelated、誤淘汰率、必要主體保持、來源多樣性、p95 與 token 負載。尚未實機測試或核准啟用。

## A8b 私有 HTTPS 傳輸介面（尚未接入正式檢索）

`agent/es/arc_semantic_review_transport.py` 實作實際 Ollama-compatible HTTPS /api/chat 請求及 count-only 回應驗證。預設關閉，必須由可信部署管理者同時設定 SRAF_ARC_REVIEW=shadow、SRAF_ARC_REVIEW_EGRESS=approved、SRAF_ARC_REVIEW_ENDPOINT（完整 https://.../api/chat）、SRAF_ARC_REVIEW_MODEL、SRAF_ARC_REVIEW_VERIFIED_INDEX（單一具體索引）。需要私有 CA 時可配置 SRAF_ARC_REVIEW_CA_FILE；預設 TLS 驗證開啟，不接受 HTTP、redirect、URL credentials/query/fragment、環境 proxy/netrc 或替代模型。此專用端點不使用普通 LLM singleton，管理者必須另行確認端點營運者、資料使用/保留及出境政策；配置不證明個別使用者權限，也不證明服務本身不記錄正文。
需報告私有 ARC budget，每輪共用最多1次額外 LLM；拒絕 Requirement acceptance 及 ordinary scope capture。最多一次 POST、connect timeout 3s/read timeout 15s，num_predict 512；拒絕壓縮回應、非200、>65536 bytes、未完成 envelope、重複 JSON keys、tool_calls 及不符合 A8 回傳契約。每個讀取區塊檢查經過時間，不是硬取消或絕對 deadline；服務端 token/時間/記錄行為需另驗收。僅記固定狀態及判斷統計，不記正文、endpoint、model、index、raw exception/response。
**尚未提供 runtime caller**：後續須從同次已授權 ES 及最終 Evidence 選擇保留可信 source-hit ordinal、綁定實際索引、在批次準備前保留掃描預算、檢查日期 refill/partial scope、原問題 provenance、manual/深度/owner 隔離及 deadline，再接入。不能以操作員 attestation 或預算代替這些安全 gate。此 PR 只有 transport 與 synthetic regressions，不發送真實資料、不啟用新篩選、不改任何正式輸出。
