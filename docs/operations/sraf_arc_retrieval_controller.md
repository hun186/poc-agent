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

## 後續 gate
- A1：Word/Markdown 分開未測與實測零值，再以真正 term_groups 顯示群組；歷史扁平清單不得推測歸屬。
- A2：中英文雙向查漏及兩岸異譯；原始必要詞優先、同群組 OR、總/每組預算、跨組正規化碰撞與英文單詞邊界、短語 precision、人工指定/排除控制；獨立 opt-in 與 A/B。
- A3b：在已授權 Index/日期/過濾條件下研究有界 ES count/聚合；檢查 nested/同事件及 analyzer 語意。精確/下限/抽樣標示；無完整數據不得假裝已觀察全索引。
- A4：僅 shadow 加權排序；統計鑑別力不是必要性，不可因高頻移除原始必要主題；稀有錯譯也不是優質詞。保持日期、來源、事件、授權及來源多樣性。
- A5/A6：爆量才有界重查或收緊、低量才有界放寬；全 request 共用呼叫/頁數/row/bytes/時間/token 預算；遇上限標示不完整，不轉送無界候選至 LLM。
- A7/A8：有界統計/抽樣摘要可供選擇性策略 LLM；個別證據覆核最後執行，維持原始必要主題、來源與低量安全 fallback。
- A9：普通及深度報告在共同規則及各自資源預算上整合。任何 on/預設改變前須在同一私有 news_test 快照，以人工標記相關性、精確率/召回率、p50/p95、ES 查詢數/CPU/傳輸量、LLM calls/token、來源多樣性、事件日期與必要主題保持作驗收。
 
此文件不是實機效能、已完成自適應重查或上線核准。
