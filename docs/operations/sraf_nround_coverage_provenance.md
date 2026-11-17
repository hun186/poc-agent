# SRAF N 輪：已驗證 Evidence／來源綁定與整輪覆蓋度評估

本階段新增 `agent/adaptive_retrieval/coverage_evaluator.py`，以及在
`observe_canonical_round` 內從真實 canonical Event／Timeline 日期和
主題驗證成功的 Evidence 建立 `(evidence_digest, source_digest)` 配對。
所有摘要均只回傳數量；不輸出文章內容、問題、日期、索引或來源識別碼。

**這仍是隔離的可信 Worker 準備模組；沒有接入正式 API、
Report Job Worker、OpenWebUI、私人 ES、LLM 或 Word。**

## 主要機制

1. `QueryConstraints.required_entities` 和額外指定的分析面向由可信
   上游建置，合計最多 8 項，且整個 request 中不可被模型自行修改。
   不能將缺少證據的必要實體當作已完成的面向。
2. `observe_canonical_round` 先完成原有 Event／Timeline 日期、
   Topic Match 和 Evidence 來源身分驗證；只有 canonical verifier
   真正接受的片段會產生不可變的 Evidence+來源 SHA-256 配對。
   無關或無日期的回退片段不能偽裝成驗證過的 Evidence。
3. `EvidenceFacetWitness` 只能引用 canonical 配對並指定其中一個
   固定目標索引；**不能拿 A 文件的 Evidence 搭配 B 文件的來源**。
   另外必須由可信的、持有私有原文的 `semantic_verifier` 回呼
   獨立判斷「此片段是否足以支持該實體／分析面向」；
   單靠模型輸出的字串、片段數或索引命中不能建立有效證據。
   注意：模組只驗證配對和回呼結果，**不能自行證明回呼的可信度或語意品質**。
4. 評估器按整個 request 持續累積、跨輪去重同一段 Evidence 與來源。
   預設每項面向至少 2 段合格 Evidence、來自至少 2 個不同來源。
   同一文章的段落重複、下一輪再遇到同一文章，都不會偽造多來源支持。
   這些預設只是保守的合格計數門檻，**不是充分性或正確性的實證保證**。
5. 若 `request_wide_attested=False` 或某輪分頁／查詢結果不完整，
   立即失敗閉鎖，不呼叫語意驗證器、不宣稱覆蓋充分，也不能在同一
   評估器內再開下一輪。正式 Worker 仍需自己核對「此輪所有計畫中的
   ES 語意分支及 PIT 分頁都已完成」；單一 PIT 分頁鏈完成不等於
   全 request 證據充分。
6. 語意回呼出錯、證據來源配對不合法、超出面向或輪次上限時，
   拒絕整輪提交且不輸出原始錯誤／私人內容；沒有可信回呼時只能
   得到「尚未確認充分」，不得擅自標為 `coverage_sufficient=True`。
   公開 `safe_audit` 只有數量、固定狀態碼和未整合提醒。

## 使用與安全限制

目前只能由**未來的可信上層**在取得完整 canonical Evidence 後，
產生語意證據配對、注入可信語意驗證器，並傳入已核實的整輪完整性。
本階段的第二個 PR 已將 `CoverageAssessment.coverage_sufficient`
接入 `AdaptiveRequestCoordinator.complete_round` 的明確選用模式，
但**仍未**接入正式 Report Job；在配對來源能對應私有原文的可信
語意驗證、完整查詢與使用者 RBAC 都完成之前，不得拿這個離線模式
放行真實 N 輪報告。

下一個工項：
- 完成 Evidence 身分配對到私有段落的可信語意驗證轉接，而不洩漏內容到進度 log
- 將本評估結果接到 coordinator 的單次 canonical 驗證與完整性閘門
- 再把可信初始問題／日期／權限、真實 ES、獨立策略 LLM 和背景 Job 串起來
- 取得實機資料集下的跨輪精確度、漏召回率、來源多樣性和超時指標後，才討論預設啟用

## 合成測試（不連線）

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_sraf_nround_coverage_provenance.py \
  tests/test_sraf_nround_coordinator.py
```

CI 使用 Python 3.10／3.11 及既有 canonical builder 的合成 Event／Timeline
文件驗證：失效日期、錯誤來源、同來源跨輪重複、必要面向缺口、語意回呼失敗、
分頁不完整、競態提交與敏感資料不進入公開 audit。
