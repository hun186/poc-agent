# SRAF Event-only / Timeline-only 文件排序相容性（無索引遷移）

## 現況與本輪選擇

過去 agent/es/query_body.py 的 _score 後排序鍵只採用 multidim_event_json.Event_Timeline.time_iso 的 nested 最大時間，因此 Event-only 文件雖通過 #395 的 Event OR Timeline 日期檢索，在同分候選中可能因缺失 Timeline 日期而劣勢。

本次採取沒有索引遷移的中立修正：

- 依相關性 _score desc 優先，和過去一致。
- 同分時以根欄位 importDT desc，缺值排最後。這是文件匯入時間，不是事件日期；Event-only、Timeline-only、雙日期及日期未知都按相同鍵處理。
- 日期 OR 過濾、Event ID、同區塊 Evidence 日期關聯驗證、原有共享與來源公平預算完全不變。
- 本次不宣稱跨 Event 與 Timeline 的共同最新事件時間排序；匯入時間也不是 Event-first 的同義詞。將 Event 和 Timeline 列成前後兩個 nested sort 不等於共同最大值。

## 明確限制

不改 ES Mapping／GLM／索引的前提下，若兩份文件 _score、importDT 都相同，現有 from/size 跨頁（尤其 refresh／跨 shard）仍可能不穩定。要達到全序，必須先驗證可排序且唯一的既有 docvalue 欄位，或另設 PIT／必要時衍生欄位；這些並未在本 PR 實施。

Year/month 精度與有 offset 時間的本地事件日不會由本輪排序改寫；Evidence 仍要獨立檢驗日期是否真正符合。多事件文件與 Event-only 的排序值不再被 Timeline 缺值懲罰，但這不是事件日期排序。

若未來確實需要兩個 nested 集合中的共同最大事件日期，需獨立設計有 time_precision／本地日期語意的衍生 docvalue，確認數據回填、舊資料重索引及 PIT／tie-break 方案，並經同意才進行。這個 PR 沒有觸及正式 ES 或資料回填。

## 驗收邊界

合成測試檢查分數第一、日期 OR 不變、Event-only／Timeline-only／雙日期／未知日期的統一排序，以及現有補頁程式的相容性。Linux news_test 真實排序與有效 Evidence A/B、同分同匯入時間的跨頁穩定性，仍屬 NOT_TESTED。
