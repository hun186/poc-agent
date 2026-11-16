# SRAF 單輪報告生成前：LLM Evidence Relevance Review

## 位置與既有功能區別

此機制位於 Data Agent 已完成 ES 日期／主題驗證，Report Agent 完成強弱選取、去重與欄位選擇之後，正式報告 LLM 呼叫之前。原有 REPORT_EV_FIELD_SELECTOR_MODE 僅選擇欄位，不會判斷片段與原始提問是否相關。新增階段以原始使用者提問（非只用 LLM 精煉詞）與已核實的證據片段進行相關性檢查，不重新檢索、不放寬日期。

LLM 只能回覆嚴格 JSON 的 ref_no、relevant、confidence 判定，不接收文件 UUID，不允許改寫文字、Event／Timeline 日期或來源引用。對背景、時間線、反例、限制等間接相關片段，指示模型應保留。來源判定僅有明確「無關且高信心」才允許移除。

## 開關與分批成本上限

主要設定 SRAF_REPORT_EVIDENCE_REVIEW 支援 off、shadow、on：
- off：暫時預設，0 次額外呼叫，原始已核實證據完整保留；待實機品質／成本驗證後考慮預設 ON
- shadow：真正進行分批 LLM 判定，但不實際剔除任何片段，只觀察擬排除數
- on：高信心無關才移除，其餘保留；任一批失敗就恢復整輪原片段

每次最多 125 條（SRAF_REPORT_REVIEW_BATCH_ITEMS，允許 1–125），且每批最多 24000 字元（SRAF_REPORT_REVIEW_BATCH_CHARS，允許 2000–24000），最多 4 次呼叫（SRAF_REPORT_REVIEW_MAX_CALLS，允許 1–4）／500 條，每次呼叫 75 秒請求 timeout，單次覆核階段 240 秒軟預算。超出容量、格式錯誤、模型失敗、逾時都保留全部原文。REPORT_EVIDENCE_REVIEW_MODEL_ID 未指定則沿用報告模型。這些是字元與請求限制，不是精確 Token、GPU 計算或實際 wall-clock 取消保證；125 條也只是上限，不是必定放得下。報告本身 REPORT_MAX_EVIDENCE_SNIPS 程式預設 120，不能把未實測的 500 條當成目前產能。

若擬排除大於 20%，此輪覆核不採用，全部保留並標記 excessive_rejection；大於 10% 時標記 high_rejection_rate 警示。模式 on 的結果不回填原始證據池，只按 ref_no 篩選報告 LLM 輸入及 Citations，不重新編號 ref_no，避免變造引用與時間鏈。所有批次必須完整回覆且引用恰好一一對應，才可以採用。

## Word／OpenWebUI 可檢視的前後差異

原有 Evidence usage 共用 formatter 擴充可選 count-only review schema。資料整備紀錄的 Evidence 篩選與使用紀錄會顯示：
- 覆核模式和實際狀態（完成、影子、跳過、降級）
- 覆核前、覆核後、擬排除、實際排除數量
- 批次、實際呼叫次數、輸入字元及耗時
- 異常原因與整輪保留原文的降級提示

使用固定原因碼和有界整數，不寫入原始證據、模型原文解釋、來源 ID 或問句，且數量不是檢索完整率或 LLM 正確率的證明。

## 預設開啟之前必須完成的驗收

先對照 L3-A 真實 Report Job + DOCX，確認 API 寫入、Agent、ES、LLM、Word 完整性；再使用 shadow 模式，比較固定題庫的真正相關／無關、背景、反例、日期精度及 Event／Timeline 片段。量測誤刪／誤留、p50/p95 延遲、LLM 呼叫與上下文、Citation 完整度。通過後才受控將 on 設為預設；現階段未完成 Linux 真實模型品質、效能及 L3-B Requirement→Schedule→Handoff 業務 E2E，均須標為 NOT_TESTED。

受控 E2E 路徑見 docs/operations/sraf_layered_diagnostics.md，需分別授權；日常 L1 不會建立任務或產生 DOCX。
