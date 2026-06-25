# multidim_event_json 多維事件結構概要

## 文件目的

`multidim_event_json` 是目前第一年開發階段的核心事件結構化欄位，用來把文章經由 LLM 萃取後的事件資訊存入 Elasticsearch。現階段假想輸入以新聞文本為主，因新聞通常具有較明確的「誰、何時、何地、做了什麼、造成什麼影響」敘事；後續可再逐步調整規則，應用到報告、公告、長文彙編、社群文本或其他非典型敘事文本。

本文件提供查閱用概要，詳細 LLM 任務規則與輸出樣板仍以 `docs/taskSetting_Enrichment.py` 中的 `MULTIDIM_EXTRACTION_Rule` 為準。

## 資料產生與儲存流程

1. **輸入文本**：原始文章或文件內容進入 enrichment 任務。
2. **LLM 萃取**：依 `docs/taskSetting_Enrichment.py` 的任務模板，從文本中抽取事件摘要、時間、地點、人物、關係、影響、證據片段與重要性分數。
3. **JSON 輸出**：LLM 必須輸出可直接解析的 JSON 陣列；每個陣列元素代表一個頂層事件物件。
4. **存入 Elasticsearch**：解析後的 JSON 寫入文件的 `multidim_event_json` field，供搜尋、RAG、Editor 表單檢視與後續 agent 分析使用。

## 頂層形狀

`multidim_event_json` 的標準語意是「事件物件陣列」。多數文章只有一個事件物件：

```json
[
  {
    "article_title": "文章標題",
    "article_date_iso": "2025-01-01",
    "article_date_precision": "day",
    "facet": ["politics"],
    "core_entities": ["範例組織"],
    "locations": ["範例地點"],
    "Event_Summary": "一句到三句事件摘要。",
    "Event": {},
    "Person": [],
    "Involved_Parties": [],
    "Impact": [],
    "Event_Timeline": [],
    "evidence_snippets": [],
    "importance": {}
  }
]
```

### 事件聚合原則

- 若一篇文本是同一主題的情勢摘要、快報、條列彙編或多源整理，預設應聚合為同一個頂層事件物件。
- 同一主題下的個別行動、來源陳述或不同時間點，應放進同一事件物件的 `Event_Timeline`、`evidence_snippets`、`Involved_Parties`、`Impact` 等欄位。
- 只有當輸入明確包含多則互不相關新聞或多個沒有共同時空脈絡、因果鏈、政策議題的事件時，才輸出多個頂層事件物件。

## 欄位概要

| 欄位 | 型別 | 用途 |
| --- | --- | --- |
| `article_title` | string/null | 文章或事件標題，可由文本標題或主檔名輔助判斷。 |
| `article_date_iso` | string/null | 整篇文章最具代表性的日期，格式為 `YYYY-MM-DD`；無法判斷時為 `null`。 |
| `article_date_precision` | string | 日期精度：`day`、`month`、`year` 或 `unknown`。 |
| `facet` | array[string] | 主題面向標籤，例如政治、經濟、安全、災害、健康、環境等，用於聚合與篩選。 |
| `core_entities` | array[string] | 事件中的核心國家、組織、人物、政策、制度、武器、平台或其他關鍵實體。 |
| `locations` | array[string] | 事件中明確提及且與主事件直接相關的地點。 |
| `Event_Summary` | string/null | 以一到三句描述文章核心事件。 |
| `Event` | object | 「誰對誰做了什麼、在何時何地、造成什麼後果」的主事件框架。 |
| `Person` | array[object] | 重要人物的角色、行動、言論、立場與關係。 |
| `Involved_Parties` | array[object] | 參與方、受影響方或相關機構及其角色。 |
| `Impact` | array[object] | 事件造成的直接影響、後果、風險或程序效果。 |
| `Event_Timeline` | array[object] | 事件時間軸，保存各時間點或期間的描述。 |
| `evidence_snippets` | array[object] | 支撐事件判斷的原文證據片段，用於回查、檢索與 RAG grounding。 |
| `importance` | object | 覆蓋度、新穎性、影響、可信度與綜合重要性分數。 |

## Event 主事件框架

`Event` 是事件物件的核心，目標是穩定描述：

> 主體（subject）→ 行動（action）→ 對象（object）→ 時間 / 地點 / 後果

主要子欄位：

- `subject`：行動發起者、執行者、主導者或制度性程序主體。
- `object`：行動直接作用、影響、處理、表決、發布、簽署或通過的對象。
- `aspect`：事件面向，例如政治、經濟、社會、災害等。
- `medium`：涉及物、媒介、法案、平台、裝備或制度工具。
- `action`：最能代表事件核心的可驗證動作。
- `time_raw` / `time_iso` / `time_precision`：原始時間字面、標準化時間與精度。
- `location`：事件發生或主要影響的地點描述。
- `consequence`：原文直接支持的結果、後果、風險或影響。
- `relation`：涉及的人物、單位或國家關係。
- `source`：新聞報導來源、發布機構或報導者；不得填入圖片署名或圖說。

## 證據優先原則

`evidence_snippets` 是本結構的重要基礎，因為它讓後續 agent、RAG 回答與人工檢視能回到原文核對。

每筆 evidence 建議包含：

- `text`：逐字擷取的原文片段，不得改寫。
- `char_start` / `char_end`：片段在原文中的字元位置。
- `paragraph_id`：段落或小節識別；無法判斷時可為空字串或 `null`。
- `sentence_index`：句子序號；無法判斷時可為 `null`。
- `source_id`：來源 ID 或 URL；沒有時可為空字串或 `null`。
- `confidence`：模型對該片段支撐性的信心分數。

原則上應先選取 evidence，再生成 `Event_Summary`、`Event`、`Impact` 與 `Event_Timeline`，避免產生沒有原文支撐的結論。

## 日期與時間設計重點

- 日期標準化使用 `YYYY-MM-DD`。
- 僅有年份時回填為 `YYYY-01-01`，精度標為 `year`。
- 僅有年月時回填為 `YYYY-MM-01`，精度標為 `month`。
- 無法判斷時使用 `null` 與 `unknown`，不得猜測。
- 四位數字可能是日期也可能是時間；若語境顯示為時間（例如偵獲、觀測、升空、雷達、上午、晚間等），不得誤判成日期。
- 整理時間、查詢時間或匯整時間不可覆蓋事件實際發生時間。

## 目前已完成 / 預期支援的應用目標

### 1. Elasticsearch 結構化儲存與搜尋

`multidim_event_json` 將非結構化文章轉為可索引的事件欄位，支援以標題、摘要、核心實體、證據片段、時間軸與參與方等維度查詢。

### 2. RAG 與 agent grounding

`evidence_snippets` 保存原文片段與位置資訊，讓回答生成、文件追問與證據整理能以原文為依據，降低未被文本支撐的推論。

### 3. 多維度事件分析

結構同時涵蓋：

- 事件主幹：`Event.subject/object/action/consequence`
- 時間維度：`article_date_*`、`Event_Timeline`
- 空間維度：`Event.location`、`locations`
- 實體維度：`core_entities`、`Person`、`Involved_Parties`
- 影響維度：`Impact`、`Event.consequence`
- 來源與證據維度：`Event.source`、`evidence_snippets`
- 重要性維度：`importance`

### 4. Editor 表單檢視與人工修正

目前 Editor 表單設定已針對 `multidim_event_json` 常用欄位提供檢視與編修能力，包含文章資訊、核心事件、分類與實體、時間軸、參與方、人物與證據片段。這讓人工可在 ES 文件層級校正 LLM 萃取結果。

### 5. 後續文本類型擴充基礎

雖然初始設計以新聞為主，但欄位已盡量保持事件抽象性。後續若要處理非新聞文本，可優先調整：

- 事件聚合 / 拆分規則。
- `Event.source` 對非新聞來源的定義。
- `article_date_iso` 在報告、會議紀錄或公告中的代表日期判定。
- evidence 選取密度與片段長度。
- facet 類別是否需要新增領域標籤。

## 維護注意事項

- 任何欄位形狀、命名或型別變更，應同步更新 `docs/taskSetting_Enrichment.py`、Editor form 設定與相關測試。
- 不應用 hard-coded output 或 mock data 宣稱結構化萃取完成；若有暫時未完成流程，需明確標註 `STUB IMPLEMENTATION` 並記錄 backlog。
- 重要資訊必須可由 `evidence_snippets` 回查；無法由原文支撐的內容應保守填 `null`、`unknown` 或空陣列。
- 請避免將 API key、token、password、cookie、private key、憑證或其他敏感資訊寫入事件 JSON 或專案記憶檔。
