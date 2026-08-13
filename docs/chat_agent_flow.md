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
```

| 變數 | 用途 | 預設值 | 最低值 |
| --- | --- | ---: | ---: |
| `ROUTER_CURRENT_MAX_CHARS` | 當輪訊息的路由判定字元上限 | `6000` | `512` |
| `ROUTER_HISTORY_MAX_CHARS` | 每筆歷史使用者訊息的路由判定字元上限 | `1500` | `256` |

這兩個值只控制路由判定成本，不是執行模型的 context limit。若降低數值，路由速度通常會改善，
但任務指示或 topic 藏在資料中段時可能降低分類準確度；調高則會增加分類模型的輸入量與逾時風險。

## 與關鍵字精煉的關係

目前的 bounded view 位於最前面的任務路由階段。只有路由結果為需要資料檢索的模式時，
後續 report / data agent 才依既有設定進行問句精煉與關鍵字抽取。PURE_LLM 不需要為了 Word
匯出而額外執行 Elasticsearch 關鍵字抽取。

## 驗證

路由輸入行為由 `tests/test_routing_input.py` 覆蓋，包括：

- 大型當輪訊息保留頭尾並符合上限。
- 大型歷史訊息獨立套用歷史上限。
- 短訊息保持原樣。
