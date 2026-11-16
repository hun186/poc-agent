# SRAF：GLM 多維度欄位利用現況與有界問題導向擴充

## 唯讀盤點的依據

已檢查 GLM Repository: hun186/GenerativeLanguageModel 中 czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml（檔案 SHA 35f88c72652e9ae5f7da77eab748075ee4f9fb45），並和 SRAF agent/es/query_body.py main 對照。該 YAML 是 GLM 原始 Mapping 定義；它**不是部署機目前 news_test 等索引的已核實 live Mapping**。啟用正式權重前，應於 Linux 以唯讀 get_mapping/field_caps 確認指定索引一致。

## 欄位矩陣

- multidim_event_json.Event_Summary：text；先前未在主查詢；本 PR 對政策／因果問題可選 should。
- multidim_event_json.Impact.impact_description：nested → text；先前未在主查詢；本 PR 對政策／因果問題可選 should，ignore_unmapped。
- multidim_event_json.Event.consequence：nested → text；先前未在主查詢；本 PR 對政策／因果問題可選 should。
- multidim_event_json.Event.relation：nested → text；先前未在主查詢；本 PR 對因果問題可選 should。
- multidim_event_json.Person.action、Person.relation：nested → text；先前未在主查詢；本 PR 對人物問題可選 should。
- multidim_event_json.Event.action：nested → keyword；仍未做中文部分詞全文搜尋。若未來使用，只能依精確／受控詞彙匹配，不得視為分詞欄。
- multidim_event_json.Person.stance：nested → keyword；未加進中文全文搜尋。
- multidim_event_json.Involved_Parties.party_name、party_role：nested → keyword；既有 party_name 在主查詢 multi_match 中，但不代表具備中文部分詞分析；本次沒有新增泛化詞匹配。
- multidim_event_json.core_entities、facet、locations：outer nested 的 keyword；現有 core_entities、locations 在 multi_match，不具中文分詞保證；facet 尚未啟用。
- multidim_event_json.Event.subject、object、location：nested → keyword；既有主查詢使用，不能誤認能做中文部分詞全文搜尋。
- multidim_event_json.article_title：outer nested → text；主查詢已用。
- multidim_event_json.Event_Timeline.description：child nested → text；主查詢已用。
- multidim_event_json.evidence_snippets.text：child nested → text；既有 ES 召回與 Evidence 來源，保持不變。
- Event.time_iso、Event_Timeline.time_iso：nested date；保留 OR 篩選、精度及 event_ids 的後處理，不因新增語義欄位改成全文搜尋。

## 新增程式邊界

主要開關 SRAF_STRUCTURED_FIELD_EXPANSION=off|shadow|on，預設 off。

- off：舊查詢位元相同，不執行增強。
- shadow：從原始使用者提問（非 LLM 重寫的查詢）計算合法的 text 欄位計畫，寫固定枚舉／數量 log，但**不實際增加 ES 查詢欄位，也無法觀測新欄位帶來的真實召回差異**。
- on：只在原問句可辨識政策、人物或因果需求時，增加最多五條 OPTIONAL SHOULD score boosts。每條按照 GLM mapping 的 outer nested、Event/Impact/Person child nested 邊界組合；missing paths ignore_unmapped。舊有 filter、原 Evidence/inner_hits、時間精度和最後引用的 event_ids 安全檢查均不改。

此版不搜尋 keyword 欄位中的任意中文子字串、不增加 ES／LLM 呼叫、不回填新資料、不編輯 ES Mapping，不把 Event_Summary/Impact 等萃取摘要當成原始可引用 Evidence。原文仍需由已存在的 Evidence parser 做日期、主題、event_id、block-local 驗證。

## 真實品質驗收尚未完成

正式量測須固定 ES 索引、日期範圍、原始提問與查詢參數，先以 shadow 確認計畫符合問題，再在**受控唯讀 A/B**裡對同一快照／索引分別執行 off 與 on 搜尋（需要多一次 ES 查詢，與 shadow 的無額外查詢不同），比較新增候選文件、不同來源數、日期／主題／Event IDs 驗證後合格 Evidence、誤收與誤引、查詢時間和報告品質。真正的 token/context 成本與 30 分鐘 N 輪 Job 預算亦須另驗證。缺少 live Mapping 驗證，不得將 on 設為正式預設。

未來可獨立規劃 Event.action、Person.stance、core_entities、facet、locations 的 keyword 精確權重，以及多欄位 cjk text/multi-field + reindex（**必須另行授權**）。
