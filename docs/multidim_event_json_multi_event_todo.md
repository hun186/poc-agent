# multidim_event_json 多頂層事件與切片合併 TODO

## 背景

`multidim_event_json` 的設計語意是事件物件陣列，理想上可容許同一文本含有多個頂層事件物件。現階段多數代理人與 Editor 流程仍偏向「一篇文件主要只有一個事件物件」的使用方式；部分流程雖已能接受 `dict`、`list[dict]` 或 JSON 字串，但仍會以第一個事件物件作為主要分析來源。

目前用於多維度抽取的 LLM 框架是通用目標框架，不只服務事件抽取。若短期內直接重構切片合併流程，可能牽涉通用 merge slice 機制、ES 寫入、agent 分析、Editor UI 與測試資料，工程成本較高。因此本文件先記錄未來精進方向，作為後續排程與設計參考。

## 目前挑戰

1. **切片結果被合併成單一大字典**
   - 長文因輸入長度限制會被切片、各自分析，再由 rule-based merge slice 合併。
   - 若合併邏輯把多個切片的結果直接整併為一個 dict，最後寫入 ES 的 `multidim_event_json` 可能變成只含單一 dict 的 list。
   - 這會讓原本可容許多個頂層事件物件的設計，在實務上退化成單事件結構。

2. **不同事件可能被拼成四不像**
   - 多主題長文、每日多則新聞、排行榜、報告彙編或跨領域摘要，可能在不同 slice 中包含彼此無共同時空脈絡或因果鏈的事件。
   - 若只依欄位層級 merge，`Event`、`Impact`、`Event_Timeline`、`Person`、`Involved_Parties` 與 `evidence_snippets` 可能被混入同一頂層物件，造成事件語意不一致。

3. **agent 邏輯仍偏向第一個事件物件**
   - 現有部分流程會把 `multidim_event_json` 正規化成 list，但後續仍取第一個 dict 作為主要 `md`。
   - 即使 ES 內已有多頂層事件物件，agent 也可能忽略第二個以後的事件，無法良好支援多事件查詢、比較、展開與追問。

4. **Editor UI schema 偏向單事件編修**
   - 目前表單欄位多以 `multidim_event_json.article_title`、`multidim_event_json.Event_Timeline` 這類 path 表達。
   - 若要完整支援多頂層事件，未來需要先選擇事件物件，再編修該事件內的欄位。

## 設計目標

- 保留 `multidim_event_json` 作為事件物件陣列的標準語意。
- 讓切片合併的單位從「整篇文件的一個大 dict」提升為「事件 cluster」。
- 同一事件跨切片的補充資訊可以合併；不同事件必須保留為不同頂層物件。
- 不確定是否同一事件時，採保守策略：優先保留多個事件，避免錯誤合併。
- 讓 agent、Editor 與搜尋流程逐步變成 multi-event aware，而不是隱含只使用第一個事件物件。

## 建議未來方案

### 1. 新增事件正規化 helper

建立共同 helper，集中處理 `multidim_event_json` 的輸入形狀：

- `dict`
- `list[dict]`
- JSON 字串
- 空值或異常值

並提供語意更清楚的 selector：

- `get_multidim_events(src)`：取得所有事件物件。
- `select_primary_event(events, query=None)`：選出主要事件。
- `select_relevant_events(events, query, limit=3)`：依使用者問題選出相關事件。
- `summarize_event_collection(events)`：產生多事件文件摘要。

### 2. 將 merge slice 改為 event-cluster merge

未來若有時間重構 merge slice，建議流程改為：

```text
slice 抽取結果
  → normalize 為 list[event_object]
  → 產生 event candidate metadata
  → rule-based event clustering
  → 每個 cluster 內做欄位 merge
  → multidim_event_json = [event_1, event_2, ...]
```

重點是：`merge_slices: true` 不應等於「所有 slice 結果合成一個事件」，而應等於「啟用跨切片整併，但先判斷哪些事件候選屬於同一事件」。

### 3. 建議 merge 設定語意

可考慮將既有設定延伸為：

```yaml
merge_slices: true
merge_unit: event_cluster
event_cluster_policy: rule_based
event_cluster_ambiguous_policy: keep_separate
merge_conflict_policy: prefer_supported
merge_dedup_lists: true
merge_log_changes: true
merge_max_log: 10
merge_require_entity_overlap: true
merge_allow_cross_topic_merge: false
```

其中：

- `event_cluster_ambiguous_policy: keep_separate`：無法確認同事件時不合併。
- `merge_conflict_policy: prefer_supported`：優先保留有 evidence 支撐、較具體且衝突較少的欄位值。
- `merge_allow_cross_topic_merge: false`：避免跨主題錯誤合併。

### 4. 每個事件保存合併 metadata

為了後續 debug 與人工檢視，事件物件可逐步加入：

```json
{
  "event_id": "cluster_001",
  "source_slice_ids": ["slice_0001", "slice_0002"],
  "merge_metadata": {
    "merged": true,
    "cluster_reason": "shared core entities and adjacent timeline",
    "conflict_count": 1,
    "conflicts": []
  }
}
```

注意 metadata 不應寫入 API key、token、password、cookie、private key、憑證或其他敏感資訊。

### 5. agent 改為 multi-event aware

後續可逐步檢查並移除隱含假設：

```python
md = md_blocks[0] if md_blocks else {}
```

替代方向：

- 文件追問：先列出或選取與 query 相關的事件。
- 全文下載：標題與日期可綜合所有事件，或明確標示 primary event。
- RAG evidence：回覆時標示 event index / event_id，支援「展開事件 2」這類追問。
- 報告模式：允許同一文件提供多個事件 evidence group。

### 6. Editor 改為事件列表 + 單事件表單

長期 UI 可改成兩層：

```text
Document
  └── multidim_event_json[]
        ├── Event 1
        ├── Event 2
        └── Event 3
```

建議功能：

- 事件卡片列表：顯示 `Event_Summary`、主體、動作、對象、日期、核心實體。
- 點選事件後編修該事件欄位。
- 支援新增、複製、刪除、合併、拆分事件。
- 顯示 `source_slice_ids`、`merge_metadata` 與 conflict 提示。

### 7. 評估新增 event-level index

若未來多維度事件分析成為核心功能，可考慮維持文件 index，同步新增事件級索引：

```text
documents_index: 保存原始文件與完整 multidim_event_json
events_index: 每個頂層事件展開成一筆 event document
```

事件級索引可降低 document-level array 查詢時的跨事件誤配風險，並讓時間軸、地圖、實體關係、事件比較與 RAG 檢索更自然。

## 建議分階段排程

### 短期

- 保留現有通用 LLM 框架與 merge slice 流程，避免立即大改。
- 記錄此限制，避免誤以為目前已完整支援多頂層事件。
- 新增測試或檢查點，至少確保 `multidim_event_json` 為 `list[dict]` 時不會因 `.get()` 直接失敗。

### 中期

- 建立共同 multi-event helper 與 selector。
- 將 agent 內直接取第一個事件物件的邏輯集中化，讓未來可逐步替換。
- 在回答中支援列出多個事件摘要，並允許使用者指定第 N 個事件追問。

### 長期

- 將 merge slice 改為 event-cluster merge。
- Editor 改為事件列表與單事件表單。
- 評估 nested mapping 或 event-level index。
- 補齊多事件 ingestion、搜尋、RAG、Editor 與匯出測試。

## 驗收建議

未來實作時至少應覆蓋以下案例：

1. 單一事件跨多個 slice，被合併為一個事件物件，且 evidence 不遺失。
2. 多主題新聞清單跨多個 slice，輸出多個頂層事件物件。
3. ambiguous case 不被硬合併。
4. agent 能回答「本文有哪些事件」。
5. agent 能針對第二或第三個事件追問。
6. Editor 能新增、編修、刪除多個頂層事件物件。
7. 搜尋結果不因跨事件欄位誤配而產生錯誤結論。

## 備註

此 TODO 屬未來精進目標；目前不要求立即修改通用 LLM 抽取框架、merge slice 主流程或所有 agent 介面。若後續要執行，建議先以最小可行改造集中處理 multi-event helper 與 agent selector，再進入 merge slice 與 Editor 重構。
