# Data Agent 模組速查

`agent/data_agent/` 負責把上層 agent 的資料需求轉成 retrieval runtime、prompt 與結構化結果。

## 主要檔案

| 路徑 | 用途 |
| --- | --- |
| `builder.py` | 建立或組裝 data-agent 相關物件 |
| `runtime.py` | 執行 retrieval / aggregation / evidence flow |
| `prompts.py` | Data-agent prompt 與指令文字 |
| `types.py` | Data-agent 使用的資料型別 |

## 常見修改建議

- 改 retrieval runtime 行為：先看 `runtime.py`。
- 改 prompt 或工具使用指令：先看 `prompts.py`。
- 改回傳資料結構：先看 `types.py`，再同步檢查呼叫端。
- 若涉及 ES query 或 evidence 格式，搭配查看 `agent/es/`。

## 注意事項

- 修改 output schema 時，請同步檢查 report、chat router、presenter 或測試是否依賴舊欄位。
- 優先保持與 `agent/es/` 的界線清楚：data-agent 負責 orchestration，ES 模組負責 query/evidence 細節。
