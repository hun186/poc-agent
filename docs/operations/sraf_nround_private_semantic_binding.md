# SRAF N 輪：可信私有 Evidence／來源／日期／語意 witness 綁定（尚未上線）

## 為何需要這一層

之前 N 輪覆蓋度評估器只認證 Evidence SHA-256 digest 與 ES 來源 digest；
沒有把**真正通過 canonical Event／Timeline 日期和主題驗證的原文片段**
傳給可信的語意評估回呼。若上層只根據摘要猜測 witness，會使
`coverage_sufficient` 失去可信度。

新增 `observe_canonical_round(private_evidence=...)`，
同一遍原有 Evidence builder 檢查中同步擷取每個驗證成功的片段，
原文、`date_iso`、原始 Event/Timeline 時間候選及 Event IDs
綁到正確 `(evidence_digest, source_digest)`。此擷取區只存在
私有記憶體，只有整個 canonical batch 檢查成功才原子提交到 collector；
中途任何來源或日期錯誤都不能留下部分原文。

`prepare_private_semantic_grant` 需要可信 `QueryConstraints`、
同一物件的 request-wide `RequestWideCoverageEvaluator`、完整一輪 hits，
以及由未來正式 Worker 注入的 **真正可信** `assessor` 回呼：
- 每個固定必要實體及分析面向，對每條已驗證的私人 Evidence 判斷是否支持；
- 回呼只能回傳真正 boolean；例外或非 boolean 不會當作成功；
- 控制單次最大語意檢查次數（預設 512、硬上限 2048），防止無限的 LLM 成本；
- 僅 approved 的 witness 被寫入 `CanonicalSemanticGrant`；
  grant 的 `semantic_verifier` 再對必要目標物件身分及證據／來源 digest
  做封閉集合查詢，拒絕外來同名目標、異來源及未批准配對；
- 私有原文不寫入任何 `RoundObservation`、
  `safe_audit`、日誌、Checkpoint 或 Word 除非正式 Worker
  另外完成獨立的合法輸出流程。私有 staging 在完成回呼後立即清空。

## 安全與完整性限制

本模組不提供真正的 LLM、提示詞規範、真實 ES／SQL 網路連線，也
**不能自行證明注入的 assessor 可靠或 Event 原文充分**。
真正使用時，Worker 應考慮把前置事件資訊（Event 時間、Timeline、
人物、涉入方及同一原始區塊上下文）交由可信 Evidence enrichment
階段補全；片段過短不得由模型補造事實。

本模組也不能自行認證「所有預定 ES 查詢／PIT 分頁都完成」，
`CanonicalSemanticGrant.safe_audit().request_wide_attested` 永遠為
`False`。未來正式上層必須將可信的 PIT／查詢計畫完整性證明
與此 grant 共同交給 coordinator；目前尚未連接
Report Job Worker、API、OpenWebUI、Word 或排程。

## 離線驗證（未接真實 ES／LLM）

```bash
cd /mntCZJ/TopicClassification/poc-agent
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_private_semantic_binding.py \
  tests/test_sraf_nround_coverage_provenance.py \
  tests/test_sraf_nround_coverage_coordinator_bridge.py
```

合成測試涵蓋日期不符、來源配對、原文不洩漏、暫存原子提交、
無 Evidence、語意回呼拒絕、缺失與例外、成本上限、假 boolean
與可信面向授權；通過不等於真實 LLM／ES 多輪 Job 驗收。
