# Chat Agent、PURE_LLM 與 Word 匯出流程

本文件說明 `/v1/chat/completions` 從接收請求、任務路由、實際模型執行，
到 Word / DOCX 匯出的資料流，並說明大型資料分析輸入如何避免在路由階段逾時。

## 流程概要

```text
完整使用者訊息 user_msg
        |
        +--> 路由判定視圖（有字元上限，只供 mode/topic 分類）
        |         |
        |         +--> SRA_REPORT
        |         +--> SRA_STYLE
        |         +--> DOC_FOLLOWUP
        |         +--> PURE_LLM
        |
        +--> 完整執行輸入（不套用路由字元上限）
                  |
                  +--> 關鍵字提取暫時視圖（僅檢索模式、有獨立字元上限）
                  |       |
                  |       +--> 核心關鍵字
                  |
                  +--> 對應 agent / LLM 產生完整回答
                                  |
                                  +--> 統一 response
                                               |
                                               +--> Word / DOCX presenter
```

`sra_api/routers/chat.py` 負責 HTTP request、session context 與 response；
`agent/agent.py::answer_with_routing()` 負責協調路由及模式執行；
`agent/routing.py::build_router_input()` 只建立分類器所需的路由判定視圖。

## 大型輸入的路由瘦身

路由器只需判斷任務模式與 topic，不需要先分析使用者附上的每一筆資料。
因此路由判定視圖採下列規則：

- 當輪使用者訊息預設最多 `6000` 字元。
- 每筆最近使用者訊息預設最多 `1500` 字元。
- 超限時保留約 75% 開頭與 25% 結尾。
- 中段改成明確省略標記，表示完整資料仍會交給執行模型。
- 短訊息保持原樣，不會無條件截斷。
- 實際啟動裁切時，後端 terminal 會輸出 WARNING，包含訊息來源、原始字元數與路由字元上限；不會把原始資料本文寫入 log。

保留頭尾是為了同時涵蓋兩種常見格式：任務指示放在資料前方，以及補充輸出要求放在資料後方。

## 完整資料不會被截斷

路由瘦身只作用於傳給分類模型的暫時字串，不會改寫原始 `user_msg` 或
既有 `query_for_agent`。因此：

- PURE_LLM 執行模型仍會收到完整的任務指示與資料。
- SRA_REPORT 等模式的實際執行輸入維持既有行為。
- 統一 response 中的回答與問題仍可供 Markdown / DOCX presenter 使用。
- Word 下載功能不會只拿到路由階段的截斷視圖。

## 設定

可在 `.env` 設定：

```dotenv
ROUTER_CURRENT_MAX_CHARS=6000
ROUTER_HISTORY_MAX_CHARS=1500
KEYWORD_EXTRACTION_MAX_CHARS=6000
```

| 變數 | 用途 | 預設值 | 最低值 |
| --- | --- | ---: | ---: |
| `ROUTER_CURRENT_MAX_CHARS` | 當輪訊息的路由判定字元上限 | `6000` | `512` |
| `ROUTER_HISTORY_MAX_CHARS` | 每筆歷史使用者訊息的路由判定字元上限 | `1500` | `256` |
| `KEYWORD_EXTRACTION_MAX_CHARS` | 關鍵字提取 LLM 暫時輸入的字元上限 | `6000` | `512` |

前兩個值只控制路由判定成本，第三個值只控制關鍵字提取成本，都不是執行模型的 context limit。
若降低數值，對應前置模型的速度通常會改善，但任務指示或 topic 藏在資料中段時可能降低分類或
提取準確度；調高則會增加對應模型的輸入量與逾時風險。

裁切時可在 API terminal 看到類似訊息：

```text
[router] 輸入過長，已啟動路由裁切機制：source=current_user_message original_chars=42000 router_chars=6000；完整內容仍會交給執行模型與 Word 匯出流程。
```

此訊息只記錄長度與來源，不會記錄使用者輸入內容，避免大量資料或敏感本文進入 log。

## 與關鍵字精煉的關係

路由與關鍵字提取各自建立 bounded temporary view，且都不會覆寫原始 `user_msg`、
`query_for_agent` 或精煉後查詢。只有路由結果為需要資料檢索的模式時，後續 report / data
agent 才會執行關鍵字抽取；PURE_LLM 不會為了 Word 匯出而額外執行 Elasticsearch 關鍵字抽取。

關鍵字裁切只套用在 `extract_topic_terms_llm()` 的輸入前。人工同義詞比對、同義詞擴增函式與
Elasticsearch 搜尋仍收到未套用此字元上限的完整查詢。這可避免「暫時視圖」被誤當成共用
query 後，無意間傳播至現在或未來新增的下游功能。

仍需注意兩種**間接影響**：路由結果會決定是否檢索及使用哪個 index；關鍵字提取結果本來就會
成為同義詞與檢索詞的種子。因此若關鍵主題只存在於被省略的中段，分類或檢索召回率仍可能下降，
但下游收到的完整查詢與資料本身不會被裁切。

## PURE_LLM 大型任務逾時

`REPORT_LLM_TIMEOUT`（以及相容舊名 `REPORT_TIMEOUT`）只套用在 SRA_REPORT 最後的報告生成，
不會作用到 PURE_LLM。PURE_LLM 是 `answer_with_routing()` 中獨立的直接模型呼叫，可用下列設定
控制應用程式等待模型回應的秒數，預設為 180 秒：

```dotenv
PURE_LLM_TIMEOUT=900
```

這個值是 Python HTTP client 等待模型服務的 timeout，不會縮短輸入，也不會讓模型本身運算變快。
若設為 900 秒後仍在更早的固定時間中斷，應另外檢查反向代理、API gateway、load balancer、瀏覽器
或部署平台的 request timeout。對極長輸入而言，提高 timeout 只能延長等待；若模型 context window
不足或推論資源不夠，仍需縮減輸入、選擇更大 context / 更快模型，或另行設計分段處理。

## 驗證

路由輸入行為由 `tests/test_routing_input.py` 覆蓋，包括：

- 大型當輪訊息保留頭尾並符合上限。
- 大型歷史訊息獨立套用歷史上限。
- 短訊息保持原樣。
