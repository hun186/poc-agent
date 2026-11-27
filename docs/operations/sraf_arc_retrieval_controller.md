# SRAF ARC：自適應檢索控制器（分階段計畫）
 
目標：在有限 ES、網路、CPU、GPU、LLM token/時間預算內，區分檢索過少與過多。不要將同義詞、統計罕見度、語意相關性混為一談。

## A3 目前候選：只觀察已取得切片
環境變數 SRAF_ARC_GROUP_FREQUENCY=shadow（預設不執行）。
每個解析切片最多 128 source hits、256 rows、每 hit 8 rows、131072 字元、16 groups、64 terms。
重用原始 Event/Timeline 日期驗證與文字正規化；只統計至少有一段合格文字的 source hit，群組同義詞 OR，單 hit 單群組最多 1 次。
輸出固定 schema、群組 ordinal、取樣範圍、限制標記與數字，無字詞/來源 ID/原文/日期；idf_milli 只是 ln((sample_N+1)/(sample_df+1)) × 1000。無合格樣本時為 null。
這是有排序偏差、可能截斷的已回傳解析樣本，不是全索引 DF、全部初篩命中數、真正文章去重總數、或相關性/純度。多頁不可直接相加當唯一文件。
不新增 ES/LLM 呼叫、不更改檢索或 Evidence 結果、不啟用自動複篩。
 
### A3 解析切片統計預算（operator-only，預設不變）
下列環境變數只影響 shadow 統計，不影響原始 Evidence、ES 搜尋或 LLM context。正整數可降低預算；超過既有硬上限則夾限，無效值使用原預設，不輸出原始設定值。日志 effective_budget 顯示實際生效上限。

| 環境變數（共同前綴 SRAF_ARC_GROUP_FREQUENCY_MAX_） | 預設與硬上限 |
| --- | ---: |
| HITS | 128 |
| ROWS | 256 |
| ROWS_PER_HIT | 8 |
| CHARS | 131072 |
| ROW_CHARS | 4096 |
| GROUPS | 16 |
| TERMS | 64 |
| TERM_CHARS | 160 |

CHARS 是 Python len() 計算的原始片段字元數，含日期驗證前掃描過的文字，不是 bytes/token，也不是 ES 回傳或報告字數。現階段不允許增加硬上限，待實機測量後再調整。
各切片上限不是全報告累計上限；跨工具、分頁與深度輪次共用的 request-local budget 尚需驗證執行緒傳遞、生命週期與併發隔離後實作。

### A3b 離線 ES 原生文件頻率計畫（未接入 transport）
- 使用 size:0、_source:false、track_total_hits:true 與 root filters aggregation。每群組在雙層 nested Evidence 文字欄位做 match_phrase OR，根文件只計一次；不回傳原文、ID、inner_hits 或 highlight。
- 明確雙端日期、最大跨度 3660 日、最多 8 群組/32 詞、每詞 160 字元；保留呼叫者 high-value/selected 必要篩選；ES timeout 2s 是協作式查詢 timeout，並非 CPU/牆鐘硬上限。
- 分母是指定日期候選條件及必要篩選內的根文件，分子是該範圍內含指定群組的根文件；可能由不同事件或區塊符合日期與片段條件，不代表同一事件，也不代表 Python Evidence 日期驗證或語意相關性。
- 回應必須有精確 total、所有 shards 成功、無 timeout/提前終止、完整合法 buckets；不完整一律回傳 incomplete 而非零。精確只指該 ES DSL 的完整計數，非語意精確率或真實文章去重。
- 尚未發出 ES 請求。正式接入前驗證授權 index/scope、mapping/analyzer、查詢負載、跨輪次共享預算、timeout/transport 取消及私有快照 A/B。不得以模擬 DSL 測試宣稱實機 count 驗收。

### ARC 跨輪次共用預算基礎（尚未接入 coordinator）
以單份報告獨有的 ArcRequestBudget 物件提供 thread-safe、原子式 reservation；每次工作先保留所有所需維度，再執行。失敗不扣額度；已成功保留的額度即使後續工作失敗也不退款，防止無界重試。每輪及全報告同時檢查，seal 後不接受新工作。不得把保留額度當實際使用量。
暫定硬上限（全報告／單輪）：切片 8／4、來源文件 1024／512、片段 2048／1024、原文字元 1048576／524288、額外 ES calls 2／1、額外 LLM calls 2／1；可由可信呼叫者降低限額。這些不是實測最佳值。輪次 ordinal 必須由 coordinator 提供；不准模型指定，不使用 process-global singleton。
目前僅有離線物件與競爭測試，尚未接入 report、tool worker、ES transport 或 LLM client；仍需驗證普通／深度流程的生命週期、跨執行緒傳遞、重試及取消、時間/token/bytes 的獨立限制，才能啟用真實查詢。

### ARC Data Agent 單次執行共用預算
當 SRAF_ARC_GROUP_FREQUENCY=shadow 且 Data Agent mode=report/sra_report 時，在建構工具前建立一份私有 ArcRequestBudget，透過既有工具實例與 worker decorator 傳遞；執行結束或例外後 seal，重設 ContextVar。每個切片掃描前保留完整設定預算（最壞成本而非實際使用量），同一次 Data Agent invocation 最多 4 個預設大小切片；不足時紀錄 shared_budget_exhausted、無統計值，原始 Evidence 不變。單獨呼叫 builder 仍依單切片限制，尚無全報告共用範圍。
此整合不是深度報告全部輪次共用預算；目前每次 Data Agent invocation 各自建立，尚待上層 coordinator 擁有並跨輪次傳遞同一物件。未增加 ES/LLM 呼叫，也未啟用跨語言檢索與加權篩選。測試為 synthetic runtime/worker 與真實 parser 路徑，不是實機驗收。

### 深度報告 N-round 統計預算整合
深度報告實際走 trusted N-round PIT execution loop，而非反覆呼叫 Data Agent。原有 RequestAdmissionBudget 仍獨立控制輪次、ES/PIT、planner 與保留報告生成期限；ARC 只限制額外 A3 shadow 樣本掃描，不取得額外 ES/LLM 授權。
在單次 trusted loop 開始建立共用 ArcRequestBudget，於既有 canonical grant 與 complete_round 的 Evidence 路徑傳入實際輪次 ordinal；退出或失敗時 seal。兩次既有 canonical 解析各自保留一次配額，不能把兩份樣本統計當成唯一文件的累計 DF。預算不足只省略額外統計，不修改原本 coverage、PIT、語意覆核、checkpoint 或報告生成條件。
測試用 synthetic two-round PIT/semantic loop 及故意較低的統計配額驗證第二輪仍正常完成；不是私有 ES 或 LLM 實機驗收。仍未接入 A3b 真實聚合或 A2b LLM 擴充，額外時間/token/bytes 預算待完成。

### A3b 普通報告原生統計 shadow transport（待實機驗收）
預設關閉；SRAF_ARC_ES_FREQUENCY=shadow 且 SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX=<單一具體索引名稱> 才可嘗試。後者為操作員明確批准該資料集合可做 corpus 統計、並已核對 live mapping/analyzer 的聲明，不是程式自動驗證。未核對勿設定。僅 report/sra_report Data Agent 的私有預算範圍、正常主查詢成功且完整、至少一筆 _index 精確吻合、原主查詢 root filters 完全相同時，保留一次 ES 配額後使用同一 SDK client 發出 size:0 聚合。無 wildcard/alias/remote cluster，明確日期雙端且不超過原計畫限制；不在 Requirement E2E、ordinary scope capture、highlight retry 或分頁重試增加統計。空結果無具體索引證據則略過；不改普通查詢或深度授權 receipt。
每輪最多一次額外 ES 請求，SDK timeout 3s、ES timeout 2s、零重試，拒絕部分結果及缺索引；兩個 timeout 不是 server CPU 硬上限。額度保留後不退款。失敗僅記固定狀態；完整結果僅記群組序號與計數，不記原詞、索引、日期、ID、DSL 或後端錯誤，且不送入報告／模型。尚未接入深度報告 PIT 統計；普通報告真實索引/授權/分析器/負載實測仍為獨立驗收 gate。

### A2b 普通報告跨語言候選 shadow LLM
預設關閉，SRAF_ARC_BILINGUAL=shadow 為獨立操作員 opt-in。僅具私有 report Data Agent 預算、原始 report question、TOPIC_LLM_URL 啟用且非人工實體、Requirement E2E 或 ordinary scope capture 的正常主查詢路徑；使用現有 call_llm provider（TOPIC_LLM_URL 是原有抽詞功能開關，實際端點由既有 MODEL_BASE_URL/client 決定），不另設新端點。原始問題與語意群組作為提詞資料，不送 Evidence 或 ES 原文。每輪一次額外 LLM 呼叫；輸入原問題最多 6000 字元、序列化最多 64000 bytes，模型 num_predict 1536、requests timeout 15s、輸出解析上限 24000 字元。timeout 非端到端硬上限，模型是否遵守 token 限額須實機驗收。額度保留後不退款。
原始 groups/effective_terms、ES DSL、Evidence、回傳 payload 均不變；只記固定狀態及各群組 ordinal、原詞數與通過結構驗證的新增候選數，不記候選詞、提詞、原問題或錯誤正文。候選數不是語意正確率、召回率或新增命中數。未接入深度報告或候選 Evidence 影響評估，未核對實機資源前勿啟用。

## 後續 gate
- A1：Word/Markdown 分開未測與實測零值，再以真正 term_groups 顯示群組；歷史扁平清單不得推測歸屬。
- A2：中英文雙向查漏及兩岸異譯；原始必要詞優先、同群組 OR、總/每組預算、跨組正規化碰撞與英文單詞邊界、短語 precision、人工指定/排除控制；獨立 opt-in 與 A/B。
- A3b：在已授權 Index/日期/過濾條件下研究有界 ES count/聚合；檢查 nested/同事件及 analyzer 語意。精確/下限/抽樣標示；無完整數據不得假裝已觀察全索引。
- A4：僅 shadow 加權排序；統計鑑別力不是必要性，不可因高頻移除原始必要主題；稀有錯譯也不是優質詞。保持日期、來源、事件、授權及來源多樣性。
- A5/A6：爆量才有界重查或收緊、低量才有界放寬；全 request 共用呼叫/頁數/row/bytes/時間/token 預算；遇上限標示不完整，不轉送無界候選至 LLM。
- A7/A8：有界統計/抽樣摘要可供選擇性策略 LLM；個別證據覆核最後執行，維持原始必要主題、來源與低量安全 fallback。
- A9：普通及深度報告在共同規則及各自資源預算上整合。任何 on/預設改變前須在同一私有 news_test 快照，以人工標記相關性、精確率/召回率、p50/p95、ES 查詢數/CPU/傳輸量、LLM calls/token、來源多樣性、事件日期與必要主題保持作驗收。
 
此文件不是實機效能、已完成自適應重查或上線核准。

## 深度報告統計計畫補充
### A3b 深度報告統計 scope plan（離線，不發送）
由 active FrozenSingleQueryPlan 與原始 coordinator 語意群組建構，保留日期及必要實體 root candidate filter，不納入 planner 新增詞或相關性 should。無界日期、analysis date、固定欄位未支援時拒絕。計畫本身不包含 PIT ID、不消耗 ES 額度、不宣稱 owner 授權或分支證明。未來 transport 必須保留同一授權 PIT 最新 ID、原本 ES/時間及 ARC 雙重預算、當前 owner 複查、PIT 更新與 cleanup、完整 shard/count 回應；不得污染 Evidence 分頁證明。尚無 live mapping/analyzer/負載驗收。

## A4 嚴格 Evidence 局部排序觀察
僅在 SRAF_ARC_GROUP_FREQUENCY=shadow 且 SRAF_ARC_RANK=shadow 同時開啟時，使用同一 parser slice 的局部樣本，至少 16 個 date-valid source hits、strict Evidence 超過 20 才嘗試。不是 ES corpus DF，不混用不同輪次/索引統計。僅比較原始 strict 前 128 rows，額外保留共用預算一切片、128 rows、131072 chars；每 row 最多 4096 chars，任何超限則略過排序而非靜默丟棄該 row。
排序優先序：strong > weak、原有命中群組數、正文命中群組數、截頂 IDF 加總、原始順序。零觀測頻率權重為零而非最大罕見度；每群組最多 2000 milli IDF。只記 top20 替換數、相對不含 IDF 的 coverage-only 排序替換數、來源 hit 數與 strong 數。保留 prefix/sample 限制標記；不得推論整個資料庫的精確率、召回率或語意必要性。所有正式 Evidence、排序、篩選與來源維持原樣，無新增 ES/LLM 呼叫。尚未實作全域 DF 加權、必要實體獨立強制 gate、來源公平配置或自適應收緊；須待人工標記 A/B 驗收。

### A4 普通報告原生 DF 排序觀察
SRAF_ARC_ES_FREQUENCY=shadow 與 SRAF_ARC_RANK_NATIVE=shadow 同時啟用才走正式 transport 的 private receipt 路徑；仍需 operator 核准索引、mapping/analyzer 與原生查詢所有既有安全 gate。完整 native counts 透過單次工具呼叫的私有 sink 傳給首次 Evidence builder，核對原始群組內容及順序、日期雙端、不接受額外 allowed_years。每份 receipt 僅消費一次，不帶入後續 refill、其他 tool、其他報告、LLM 或公開輸出。
沿用 A4 strong/coverage/正文優先順序與有界 IDF；使用原生 root document frequency 而非局部樣本，仍需最少 16 個 eligible documents，零頻率不獎勵，額外排序使用同一 ARC budget。原生與局部排序各自記錄，不能混合分母或頻率；原生 scope 標明 not_pit，因普通報告主查詢與統計並非同一 PIT 快照，即使查詢條件一致也不保證資料版本相同。ES analyzer 與 Python 正規化匹配仍可能不同。沒有新增 ES/LLM 呼叫，無正式排序或結果變更，尚待實機及人工標記驗收。

## A5 初篩爆量及收緊反事實觀察（普通報告）
SRAF_ARC_TIGHTEN=shadow，預設關閉。只將第一次普通報告主查詢的 ES total（eq 精確、gte 下限、其他 unknown）與第一次 strict parser slice 配對，拒絕 timeout、提前終止、失敗 shard、remote cluster 或矛盾計數；不把回傳頁大小當全體命中數。候選總數 >=256 為暫定壓力訊號，不是報告充分性；即使候選爆量，strict 少於40也不提出收緊比較。非首次 refill、fallback、Requirement E2E 或 ordinary scope capture 不傳入壓力資訊。
至少4群組且有來自原問題的明確必要主體才比較：全群組正文命中；正文至少3群組、必要主體字面命中並命中局部最具鑑別力的非主體群組；同條件但使用原生 DF。各頻率來源分開，零觀測或全體命中不提供鑑別力候選。保留原日期驗證、strict Evidence 及正文語意群組基準，Latin alias 使用邊界驗證；不得將原有必要詞刪除。每種策略僅統計留下的 prefix rows / source hits、是否達到暫定20 rows及8 sources觀察門檻。最多128 rows、每row4096 chars、合計131072 chars，先保留ARC共用預算，超限略過。原生DF非同一PIT快照，局部樣本有偏差，prefix不代表全體，門檻不是召回率或充分性證明。無新增 ES/LLM 呼叫，不選擇/排除任何正式 Evidence，不啟動重查；尚待必要多實體保護、人工標記、時間及負載驗收。

## A6 低量原因與直接主體 3→2 反事實觀察
SRAF_ARC_RELAX=shadow，預設關閉；普通報告同一首次主查詢及首次 strict parser slice，與 A5 共用候選 total 確定性資訊，但獨立開關。空主查詢直接辨別精確零與未知空頁，不增加重查；既有無日期 fallback 不變。非首次 refill、Requirement E2E、ordinary scope capture 不啟動。既有 strict pass 收集計數（已解析 citation、canonical eligible、日期拒絕、其他拒絕、主題拒絕與 strict），不啟用全量 Trace 或多跑一次 strict；這些是已解析片段的結果，不證明整個資料庫不存在符合條件的資料，canonical eligible 也不是所有 legacy 日期已證實。
strict <3 且有主題淘汰、原始問題明確必要主體、3–16 群組及最多64詞時，才觀察 3→2；不把二群組降至一群組，不擴大日期或新增資料來源。正規化跨群組相同別名則略過，正文需直接含必要主體字面及恰好兩個原群組（Latin 邊界），再通過 canonical 日期/連結及去重；僅統計相對 strict 的新增候選，不代表相對最終輸出有增益（舊有 zero-only relaxation/rescue 等可已納入）。不使用同事件上下文的候選；既有 topic_adaptive 機制不變。觀察上限128 hits、128 rows、每hit8 rows、每row4096字元、總131072字元，先保留共用預算，假設最多補2筆且達3筆即止；無候選實際加入。明示樣本限制，無人工相關性、召回率或實機效能證明。

## A7 自適應策略決策觀察（普通報告）
SRAF_ARC_STRATEGY=shadow，預設關閉。只在普通報告首次主查詢取得候選量資訊並於完成原有日期 refill 與最終 Evidence 選擇後決策；A5/A6 同次首次 builder 觀察結果以私有 sink 傳遞，不讀日志、不跨頁混用、不對模型公開此 sink。A5/A6 仍需各自開啟，不因 A7 自動增加掃描。多頁 refill、截斷/不完整 refill、unknown primary、人工實體模式、Requirement E2E 或 ordinary scope capture 略過策略 LLM；無日期 fallback 不沿用首次資訊。空日期查詢只做確定性診斷。
先以程式路由：最終 Evidence 0–2 時，精確零建議檢查 query scope、日期/來源淘汰檢查資料、已存在可觀察放寬候選則評估既有機制；無可用候選但未截斷且有主題淘汰，或缺可信必要主體，才允許模型在 keep_original/review_aliases/review_topic_scope 的適用子集合中選擇人工評估方向。最終3–39或strong不足20不呼叫模型；高量時僅在同次 A5 未截斷且至少兩種真正減少片段、仍保留>=20 rows及>=8 sources的策略存在時允許模型比較。只有一種可行收緊方向由程式記錄。上述暫定門檻與計數不是語意充分性證明，也不代表實際 precision/recall。
模型沿用既有 topic LLM，需 TOPIC_LLM_URL 與報告私有 ARC 預算；與 A2b 共用每輪最多1次額外 LLM 預算（先執行的 A2b 如已保留則 A7 略過）。原始問題與群組受 A2b 輸入限制，序列化<=64000 bytes；僅固定計數、理由及允許選項，不傳送 Evidence 原文、日期/索引欄位、DSL、識別碼、自由格式診斷或錯誤內容。requests timeout 15s（非端到端硬上限）、num_predict 128（待實測供應端是否遵守）、輸出解析<=1024 chars、拒絕重複 JSON keys、額外欄位與未授權選項。只記固定狀態及建議 enum；不執行任何模型建議，不改日期、群組、權限、原始 Evidence 或查詢，不追加 ES；未實作完整報告/深度跨輪次策略執行與實機 A/B。

## A2/A7/A8 統一額外模型選擇（普通報告 Shadow）
SRAF_ARC_LLM_PRIORITY=shadow 時，低量別名疑慮沿用 A2、其他未解決策略歧義沿用 A7；高量且最終綁定 Evidence 具有可複查歧義時，先選 A8（至少40片段、4來源有效批次、完整單頁、可信政策入口、端點及時間候選門檻），仍由 A8  transport 執行獨立前後授權及原子不可退款預算。只在私有 tool-local sink 記錄 A8 已選擇，不記原文、來源或 verdict；拒絕、撤銷、失敗不改派 A2/A7，A7 仍可記確定性診斷。若 A8 未達候選門檻才沿用 A2/A7 分配。旗標關閉時保留原有執行順序。每輪共享 LLM ceiling 不變，不是整體跨輪資源分配或生產 ACL 安裝；未改正式 Evidence 或新增 ES 查詢。正式環境品質、成本與資料授權待獨立驗收。

## 深度多輪 A7 診斷（Shadow）
既有 SRAF_ARC_STRATEGY=shadow 同時允許深度協調器在實際 canonical ledger 與 request-wide semantic coverage evaluator 完成一輪後記錄固定計數和 advice enum。區分本輪候選、canonical 證據及新增量、累計有語意支持的證據/來源與缺少面向；依此觀察空候選、canonical attrition、語意支持不足、重複證據、低增量及高量但覆蓋不足。40片段與少於3新增片段僅為診斷候選門檻，非品質或放寬/收緊依據。未完整/未授權整體範圍不提出建議，舊版 isolated boolean 路徑不產生訊號。只記錄不執行；不改正式 planner prompt、查詢、Evidence、授權、預算或公開 progress，亦不新增模型呼叫。正式將訊號接入規劃器仍須獨立驗收。
