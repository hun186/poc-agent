# SRA Elasticsearch 原文欄位契約

## 名詞：代理人參考文本

本專案以「**代理人參考文本**」（agent reference text）取代容易混淆的
「全文」稱呼。它代表代理人需要前後文時所讀取的連貫文本，來源可以是：

- 未加工的原始全文；或
- 經清理、去重、重排或精煉，但仍保留事件脈絡的詳文。

它與 `multidim_event_json.evidence_snippets` 的責任不同：evidence snippet 是
可引用、可追溯的局部證據；代理人參考文本則提供理解局部證據所需的上下文，
不能因文字較完整就取代 evidence snippet 的引證角色。

## 可設定欄位契約

代理人參考文本的 ES dot path 由環境變數 `SRA_REFERENCE_TEXT_FIELD` 控制，
預設為 `rawInfo.content`。例如改用精煉詳文：

```dotenv
SRA_REFERENCE_TEXT_FIELD=agent_context.coherent_text
```

設定值只接受英數、底線、連字號與 dot path；無效值會安全退回
`rawInfo.content`。設定後，TXT→ES 與 SQL→ES ingestion 仍會保留
`rawInfo.content`，並將相同輸入初始化到設定欄位；新 index 也會加入相同 text
mapping。後續清理／精煉 pipeline 只覆寫 reference 欄位，不應修改 raw。
SRA 搜尋中的原文加分、fallback
query/highlight、證據 parser 的日期與片段 fallback、依 ID 取得參考文本，
以及 docs 全文下載會共同讀取該欄位。

## 既有耦合與範圍

TXT→ES、SQL→ES、Agent runtime 與 docs API 已共用上述設定。Excel→SQL 本身只
負責將 Excel 欄位依任務 mapping 寫進 SQL Server，不直接產生 ES `_source`，
因此不應把 ES dot path 寫進 Excel→SQL 的 SQL destination 欄名；後續 SQL→ES
仍由 `source.columns.content` 選出 SQL 內容欄，再寫入
`SRA_REFERENCE_TEXT_FIELD`。

Editor 仍依 ES mapping / form config 決定可編輯欄位。環境變數不會搬移既有
ES 資料，也不會自動改寫 Editor 表單設定。

## 舊文件與 rolling deployment 相容性

| 情境 | 結果 |
| --- | --- |
| 未設定 `SRA_REFERENCE_TEXT_FIELD`，文件只有 `rawInfo.content` | 完全沿用舊行為，reference 與 raw 都可讀取原文。 |
| 已設定 `agent_context.coherent_text`，舊文件尚未 backfill | 代理人 reference 不會假裝已有精煉內容；reference 回 404／檢索不命中，但 raw 與 both 仍能取得原文。 |
| 新版 ingestion 搭配新欄位設定 | 同時保留 `rawInfo.content` 並初始化 reference 欄位；舊版程式仍能讀 raw，新版程式可讀 reference。 |
| 精煉 pipeline 完成 | 只更新 reference 欄位；raw 保持未處理原文，供人工稽核比對。 |

因此，切換到新欄位前仍建議先 backfill 舊文件的 reference 欄位，再切換 agent
讀取設定。雙寫解決新資料的前後版本相容性，但不會自動補齊切換前已存在的 ES
文件。

## 全文 API 的文本層次

`GET /v1/docs/{doc_id}/fulltext` 以 `text_layer` 明確選擇輸出素材：

- `reference`（預設）：代理人實際使用的連貫參考文本，例如
  `agent_context.coherent_text`。
- `raw`：固定讀取 `rawInfo.content`，供人工檢核清理、摘整或 AI 處理結果。
- `both`：JSON 同時回傳兩層的欄位、長度與文字；TXT 則以具欄名的分隔標題
  串接兩層，適合下載後直接比對。

JSON 會以 `available_text_layers` 揭露每一層是否存在及其長度。`both` 模式另有
`text_layers.reference` 與 `text_layers.raw`；既有 `full_text` 仍以 reference
為主要值，reference 缺少時才在 `both` 模式使用 raw。單獨要求 `raw` 時若原文
不存在會回傳 404，不會拿精煉文本冒充原始材料。

OpenWebUI 的 citation 區不再只顯示語意不明的「下載全文」，而會提供：

- **下載參考文本**：`text_layer=reference`；舊文件尚未 backfill 時可能回 404。
- **下載原始文本**：`text_layer=raw`；可直接檢核 `rawInfo.content`。
- **下載雙層比對**：`text_layer=both`；舊文件沒有 reference 時仍可下載 raw。
- **多層 JSON**：回傳兩層 availability 與內容，供程式或進階檢核使用。

結構化報告的主力搜尋以 `multidim_event_json`、`communication.subject`
等欄位為主，第一階段不直接以原文全文作為主力欄位。因此，只要
`multidim_event_json` 的 mapping 與資料仍符合現有契約，單純缺少
`rawInfo.content` 通常不會讓所有 SRA 報告請求立即失敗；但會造成下列功能
部分失效或降級：

- 核心詞與同義詞針對原文的加分查詢無法命中。
- Elasticsearch 主查詢失敗後的 fallback 查詢與 highlight 會失去原文欄位。
- 當結構化日期不存在時，無法再從原文推測文章日期。
- 未設定替代欄位時，依文件 ID 取得風格範例仍保留 root-level `content` 與
  `doc_text` 的舊版 fallback；明確指定替代欄位時不會混回這些舊來源。
- `/v1/docs/{doc_id}/fulltext` 在預設契約下保留 `full_text`、
  `rawInfo.content` 與 root-level `content` 相容順序；明確指定替代欄位時只讀取
  該代理人參考文本欄位。
- Editor 的預設搜尋、顯示與檔案附加仍指向 `rawInfo.content`，如需編修新欄位，
  必須另外更新 mapping 與 form config。

## 欄位改名建議

最安全的遷移方式是在過渡期保留 `rawInfo.content` alias/copy，或在寫入時
雙寫舊、新欄位，待應用程式、mapping、既有文件與測試全部完成遷移後再移除
舊欄位。只修改 ES mapping 或新資料的欄名並不安全。

若必須正式改名，至少需要同步盤點並修改：

1. 在部署環境設定 `SRA_REFERENCE_TEXT_FIELD`。
2. 確認新欄位已存在於 ES mapping，並 backfill / reindex 既有文件。
3. 若資料先由 Excel→SQL 匯入，確認 Excel 任務的 destination 欄名與 SQL→ES
   設定的 `source.columns.content` 對得上。
4. `sra_api/services/editor_form_config.py`、`config/editor_form.default.json`
   與 Editor 靜態資源的搜尋、顯示及檔案附加路徑。
5. 既有自訂 ingestion writer 與相關測試資料。

`ESFetchDocById.text_field` 仍可針對單次工具呼叫覆寫欄位；未指定時才使用全域
`SRA_REFERENCE_TEXT_FIELD`。如果全域或單次明確指定新欄位但文件沒有該值，
工具不會偷偷退回雜亂的 `rawInfo.content`，避免混用不同文本語意。
