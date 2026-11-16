# SRAF GLM 結構化欄位 A/B：雙私人快照、有效 Evidence 對照

## 目的與使用範圍

此工具解決目前欄位加權只看 ES hit 數量、無法判斷是否真的多出合格 Evidence 的問題。它在**不聯網**的 Python 執行環境，對操作員已另外取得的兩份 ES 查詢結果執行同一套 SRAF canonical Evidence Parser。

- 基準組：SRAF_STRUCTURED_FIELD_EXPANSION=off 的 ES query 結果（baseline）。
- 增強組：SRAF_STRUCTURED_FIELD_EXPANSION=on 的 ES query 結果（structured_on）。
- 兩組必須使用相同的原問句、term_groups、effective_terms、日期範圍、snippet query、索引範圍與其它查詢參數；**工具僅能檢查快照內前六個參數是否相同，不能驗證實際 ES DSL 與 Index Mapping**。
- 檢查快照中的每個 ES hit 必須有不重複的（_index, _id）；跨索引重複 ID 仍是不同文件。不能把 UUID、文章標題或同一事件 ID 當作 ES 文件身分。
- 比較候選 hit 數、新增與失去的來源、經既有 Event/Timeline／event_ids 日期和 Topic Match（嚴格或降低群組門檻）驗證的 Evidence 數、強弱 Evidence、各組有效來源數、新增有效來源與原本有效來源損失。現有 fallback_any_term 雖可能輸出片段，**沒有通過 Topic Match 群組門檻**，因此只能算 Parser 輸出，不能算有效主題 Evidence 或有效來源。
- 另外顯示**新增候選但沒有任何有效 Evidence 的來源數**。可直接驗證「ES 多撈到文章，卻沒有改善合格證據」這種反例。
- 所有輸出是固定欄位純計數，不會包含原始問題、日期、來源 ID、Event IDs、正文、Token、SQL／ES 連線資訊，也不會把任何快照傳給外部。
- 仍需研究人員逐篇標記真實相關性。僅通過 canonical 日期＋主題規則不等於人類判定的 precision，也不等於完全召回率。

## 準備快照（操作員自行取得，工具不查 ES）

兩個 JSON 文件均需是使用者自己持有的私人資料，**允許任一組 `es_hits=[]`，以免把最重要的零命中基準／增強案例誤判為無效測試**；請勿上傳 GitHub。檔案擁有者須與執行帳號相同、權限 0600、大小 1B–8 MiB、不是 symlink／FIFO。

沿用既有 tools/sraf_topic_adaptive_ab_offline.py 的 snapshot schema：

| 欄位 | baseline 文件 | structured_on 文件 |
| --- | --- | --- |
| snapshot_role | "baseline" | "structured_on" |
| es_hits | 基準組從 ES 拿到的原始 hits 陣列 | 增強組原始 hits 陣列 |
| original_question | 完全相同原始提問 | 同左 |
| date_from / date_to | 同一個日期條件 | 同左 |
| term_groups | 同一個語意群組陣列 | 同左 |
| effective_terms | 同一組實際搜尋關鍵詞 | 同左 |
| query_for_snippet | 同一個原本查詢文字 | 同左 |

保留每個 ES hit 的 _index、_id、_source、inner_hits 等既有 Parser 使用的欄位。**不要用公開資料拼湊 ID，或把兩次查詢合併成一份快照**。查詢使用相同索引的操作規則／映射必須由現場額外證明，工具只驗證輸入內容契約；無法證明兩份快照真正由正式 ES 搜尋產生。

執行（在 Windows 打包更新後的 Linux repo 中，使用相同專案環境的 Python）：

~~~bash
cd /mntCZJ/TopicClassification/poc-agent
python -m tools.sraf_structured_field_pair_ab_offline \
  /private/ab/baseline.json \
  /private/ab/structured_on.json
~~~

輸出 `SRAF_STRUCTURED_AB={...}`，包含以下重點數值：

- `candidate_new_sources`：只在結構化欄位增強結果中的候選文件數。
- `new_candidate_sources_with_valid_evidence`：新增文件中，有通過 SRAF 原有日期和 Topic Match 驗證者的來源數。
- `new_candidate_sources_without_valid_evidence`：增強搜尋新增文件，但未能產生合格 Evidence 的來源數。
- `valid_sources_gained`、`valid_sources_lost`：即使總數持平，也要觀察有沒有失去原本的有效來源。
- `baseline_strict_evidence`、`enhanced_strict_evidence`：真正嚴格 Topic Match 合格段數（明確排除雖沿用 `match_policy=strict`、但實際 `match_scope=fallback_any_term` 的舊式弱證據）；另分強弱 Evidence。
- `baseline_parser_output_evidence`、`enhanced_parser_output_evidence`：包含舊式 fallback 的 Parser 輸出總數；`baseline_any_term_fallback_evidence`、`enhanced_any_term_fallback_evidence`：僅命中任一有效關鍵詞、未過 Topic Match 門檻的片段數。不能將這些片段當成已通過嚴格主題精篩。
- `human_precision_assessment=REQUIRED`；`same_es_index_mapping_verified=NOT_TESTED`；`query_elapsed_and_token_cost=NOT_MEASURED`；`report_docx=NOT_TESTED`：避免把離線比較誤認成正式品質或部署驗收。

## 對照條件與安全限制

此工具刻意關閉 Topic Match 3→2 自動放寬、Evidence Trace、可選 rescue/source refill/fair budget 等旗標，對兩份已下載 hit 以**一致且可重複的單次 Parser 基礎規則**比較。這不是完整的正式單輪／多輪 Report Job 結果，亦不能判斷新 GLM 欄位加權所增加的 ES 請求時間、LLM token 或最終 Word 引用率。

若要啟用有界 Topic Match 放寬，再另外使用同一批快照的 Topic Match A/B，避免把「搜尋欄位加權」和「證據門檻放寬」的效果混成一個分數。

**本工具本身不查詢 ES、不寫資料、不調 Mapping、不建立 Report Job，也不接收帳號密碼**。若現場查詢 baseline/on 必須操作 ES，應先用唯讀專用身分與實際 Mapping 核對，限定同索引／日期／大小、固定查詢條件，個別授權執行。這個 PR 不代替現場安全驗證，也不自動查詢或下載私人新聞。
