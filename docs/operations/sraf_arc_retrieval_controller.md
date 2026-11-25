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

### A3b 深度報告統計 scope plan（離線，不發送）
由 active FrozenSingleQueryPlan 與原始 coordinator 語意群組建構，保留日期及必要實體 root candidate filter，不納入 planner 新增詞或相關性 should。無界日期、analysis date、固定欄位未支援時拒絕。計畫本身不包含 PIT ID、不消耗 ES 額度、不宣稱 owner 授權或分支證明。未來 transport 必須保留同一授權 PIT 最新 ID、原本 ES/時間及 ARC 雙重預算、當前 owner 複查、PIT 更新與 cleanup、完整 shard/count 回應；不得污染 Evidence 分頁證明。尚無 live mapping/analyzer/負載驗收。

## 後續 gate
- A1：Word/Markdown 分開未測與實測零值，再以真正 term_groups 顯示群組；歷史扁平清單不得推測歸屬。
- A2：中英文雙向查漏及兩岸異譯；原始必要詞優先、同群組 OR、總/每組預算、跨組正規化碰撞與英文單詞邊界、短語 precision、人工指定/排除控制；獨立 opt-in 與 A/B。
- A3b：在已授權 Index/日期/過濾條件下研究有界 ES count/聚合；檢查 nested/同事件及 analyzer 語意。精確/下限/抽樣標示；無完整數據不得假裝已觀察全索引。
- A4：僅 shadow 加權排序；統計鑑別力不是必要性，不可因高頻移除原始必要主題；稀有錯譯也不是優質詞。保持日期、來源、事件、授權及來源多樣性。
- A5/A6：爆量才有界重查或收緊、低量才有界放寬；全 request 共用呼叫/頁數/row/bytes/時間/token 預算；遇上限標示不完整，不轉送無界候選至 LLM。
- A7/A8：有界統計/抽樣摘要可供選擇性策略 LLM；個別證據覆核最後執行，維持原始必要主題、來源與低量安全 fallback。
- A9：普通及深度報告在共同規則及各自資源預算上整合。任何 on/預設改變前須在同一私有 news_test 快照，以人工標記相關性、精確率/召回率、p50/p95、ES 查詢數/CPU/傳輸量、LLM calls/token、來源多樣性、事件日期與必要主題保持作驗收。
 
此文件不是實機效能、已完成自適應重查或上線核准。
