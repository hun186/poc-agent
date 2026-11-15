# SRAF：初始抽詞與 N 輪策略代理的程式邊界（#413 B0）

## 決定

**雙代理決策、共用檢索與 Evidence 引擎。** 初始查詢仍由
`agent/data_agent/report_prompts.py`（Data Agent）及
`agent/es/query_terms.py`（初始 LLM 抽詞／同義詞）建立。
第二輪起另由 `agent/adaptive_retrieval/` 解析**前幾輪 request-wide 品質與缺口**，
提出新的補查面向／可選語意詞，**絕不重複跑初始抽詞 Prompt 來假裝智慧多輪**。

```text
使用者原問題／可信對話上下文
  └─> 現有 Data Agent：初始核心詞、同義詞、日期解析
        └─> 第 1 輪 ES → 同語意計畫的 date-refill/inner_hits/_source 補抓
               └─> canonical Event/Timeline 日期／主題驗證 → Evidence 公平篩選
                    └─> request-wide Evidence checkpoint + 缺口評估（尚待實作）
                         └─> 獨立 AdaptiveRetrievalPlanner（本 PR）
                              ├─ 停止／日期進入自動校驗
                              └─ 新可選詞 + 目標分析面向（受 Guard 約束）
                                   └─> 新語意查詢計畫 → 第 2～N 輪 ES
                                        └─> 共用原 Evidence 引擎 → 累積 checkpoint
                                             └─> 評估／再規劃迴圈（尚待實作）
                                                  └─> 唯一最終報告／Word
```

> 注意：本 PR 實作**獨立規劃代理人的純內部 LLM 決策與保護契約**，
> 並未實作以上整條執行鏈。圖中 request-wide evaluator、ES 搜尋迴圈、
> 持久化 checkpoint、Job 模式和 Word 是後續工作，不能當作已交付。

## 單輪與下一輪的精確判斷

| 行為 | 檢索輪次 |
| --- | --- |
| 首次 ES 查詢前抽核心關鍵字、建立名稱／同義詞群組 | 第 1 輪 |
| 相同查詢 DSL 的有界 ES 下一頁、日期候選回補 | 仍是第 1 輪 |
| 已回傳 ES hit 的 `inner_hits`／`_source` 片段驗證、弱證據救援、來源公平 | 仍是第 1 輪 |
| 檢視整輪 Evidence 後提出不同語意查詢計畫並再次向 ES 搜尋 | 第 2、3...N 輪 |

ES call 數不能當成語意輪次數。新規劃詞是**候選 optional/SHOULD**，
不是自動加入所有關鍵字的 required/AND；後續 ES adapter 必須證實這點，
並保持原始核心議題與使用者指定語意不漂移。

## 日期、權限與語意條件不可交給新代理管理

`QueryConstraints` 是由**可信上游**建立的 frozen 結構：
- `event_date`：事件本身的日期（可依原文指定日、月、年精度）。
- `analysis_date`：使用者要求的分析期間；與事件時間分開，未指定則無。
- `allowed_indexes`、`fixed_fields`、`required_entities`、`original_core_terms`。
- `keyword_policy`：人工指定只能用哪些詞時為 `user_locked`。

**日期硬約束不可因搜尋不足而放寬**。日期合法來源
`Event.time_iso`／`Event_Timeline.time_iso` 仍由原本 canonical
Evidence 引擎逐條檢核，不能以文章發佈日代替；LLM planner 不能回傳
`date_from`／`date_to`／`index_hint`／`permissions` 等欄位。

若 LLM 懷疑上游**解析錯**，只回 `date_recheck`，由未來獨立的**全自動日期校驗器**處理；不是要求使用者或管理員人工覆核。校驗期間立即**停止新搜尋**。
必須由另個可信解析糾錯流程對照使用者原文／可信上下文，版本化修正條件，
且對已存 Evidence checkpoint 全量重驗，才可續查。本 PR **尚未實作**
可信日期再解析／修正與 checkpoint revalidation。人工原文已鎖定的日期
不能藉由 `date_recheck` 改成比較容易查到的範圍。

`DateWindow.source_text` 是可稽核的上游文字來源聲稱，
**不等於已完成語意驗證**。正式接線前，須實作可追溯的可信日期原文驗證，
不能直接把第一輪 LLM 輸出視為授權資料。

## 新規劃代理人接收什麼

`RoundEvidenceSummary` 僅允許已驗證且**整個 request／整個查詢輪次**
範圍的統計、已使用搜尋詞、missing aspects、已知來源數與不完整訊號。
`#414` 的每一次 builder-slice health **不能冒充 request-wide** 判斷；
`result_incomplete=True` 時先停止新語意查詢，不能因為資料未知就假造
coverage gap。可傳入的是受限的統計與缺口描述，不是私人 ES 全文、文件 ID
或任意原文片段。

`AdaptiveRetrievalPlanner.propose_next(...)` 要求外部明確注入 LLM
callable（可在未來受控 Worker 中傳入既有 `call_llm`）；匯入模組本身不
讀 ES／不初始化模型／不送網路。輸出是嚴格 JSON：

```json
{
  "action": "search",
  "reason_code": "COVERAGE_GAP",
  "optional_terms": ["聯合國聲明", "外交回應"],
  "target_aspects": ["各國回應"]
}
```

不允許增添其他欄位。

新增的 `bind_next_round_plan` 必須再次驗證決策、request-wide 歷史、人工鎖詞與日期樣式，再輸出帶著原始 frozen `QueryConstraints` 的 `BoundNextRoundPlan`；未來 ES adapter 不得另行從 LLM 字串讀入日期／索引／欄位。

任何非法提案、LLM 失敗、前輪資料不完整、人工鎖詞、
預算不足、連續無增量、達輪數上限都**fail closed**。
本 PR 的 `BudgetSnapshot` 是只讀准入提示，**不是** 1800 秒硬中止、
真實 ES/LLM 計費、跨程序原子配額或可取消在途 HTTP。

## 下一步落地順序（須獨立 PR／Gate）

1. 完成 #397 的單輪 Evidence 低量救援、同輪補抓、公平分配、LLM 輸入真 token
   預算和私網基準測試，再產出**request-wide** 去重 Evidence 與缺口診斷。
2. 建立可信初輪日期／權限／索引/欄位限定值的 `QueryConstraints` 映射，
   不能讓第一輪 LLM JSON 自行聲稱授權；針對錯誤日期分離可信糾錯流程。
3. 建立 ES query adapter：新代理只有 optional strategy terms，
   底層永遠使用 server-owned scope，禁止直接執行模型生成 ES DSL；
   每輪共用原日期與主題驗證，checkpoint 必須跨輪以 index/id/
   Event-block/time 身分核實及去重。
4. 接入既有 `ReportJobWorker` 的明確 `adaptive_multiround` 模式，
   配備總檢索 1800 秒＋報告生成預留、max rounds/ES+LLM calls/tokens/
   佇列與合作式取消及斷點策略；再處理雙 Word 安全狀態/下載入口。
   #417 只是 queued-only cancel/ admission，尚未合併，不是此處已可使用。
5. 精確 HEAD Hosted Python3.10／3.11 tests、獨立 Codex Code Review、
   私網 `news_test`/LLM/DOCX/Word/browser/OpenWebUI 功能與效能驗收後
   才考慮啟用，不能把 Hosted synthetic PASS 當 private LIVE PASS。

## 本 PR 離線測試

```bash
python -m pytest -q tests/test_sraf_adaptive_planner_contract.py
```

測試的是**真正的不可變 dataclass、獨立 prompt、模型 JSON
驗證與 fail-closed 決策**，所用 LLM 輸出為測試替身，未連上
私人 ES/LLM/Job。這是非發布、預先隔離的候選能力。


## 日期再驗證：全自動，不設人工審批關卡（產品決策 2026-11-15）

`date_recheck` 是**系統內部狀態／建議**，不是 UI 等待人工或管理員批准：
- **啟動條件**：有可核查的原始問題/可信上下文與初始解析**矛盾的跡象**；不得只因 ES 命中太少、有效 Evidence 少或報告篇幅不足就啟動。
- **自動優先**：依原文中的西曆日期、年/月/日範圍與時間精度，由獨立、可追溯的規則解析器交叉比對；若涉及「去年」「事件後三個月」等相對時間，使用請求時鎖定的可信時間錨點／上下文。只有規則無法解決而有明確材料時才讓獨立日期解析 LLM 提出**候選**，由守衛程式核查原文與不變條件；不能拿另一個 LLM 意見當成已證實錯誤。
- **確認錯誤**：由受信的日期協調器產生新版本 `QueryConstraints`，保存匿名原因碼與版本；重新套用 ES 日期條件、對舊 Evidence checkpoint 全部重新驗證，不得沿用不符新日期的舊結果。不得藉日期糾錯修改 index/RBAC、手動指定欄位及核心實體。
- **無法證實**：保持原有明確日期，不修改也不放寬；若初始時間仍有重大歧義或無法確證符合使用者原意，標示 `INCOMPLETE_DATE_INTERPRETATION` 並避免宣稱報告完整（必要時停止深度報告）。
- **截至本 PR**：只有 `date_recheck` 意圖訊號與 fail-closed 限制，**尚無上述全自動日期再解析/版本化/舊 Evidence 重驗程式**。未來未接上校驗器時，應直接停止自適應下一輪，不能等待人工，也不能假裝自動修正成功。
