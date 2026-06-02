# Elasticsearch 模組速查

`agent/es/` 負責 Elasticsearch client、query construction、evidence 整理，以及 SQL/TXT 匯入 ES 的工具。

## 主要檔案

| 路徑 | 用途 |
| --- | --- |
| `es_client.py` | Elasticsearch client 封裝與查詢執行 |
| `query_body.py` | ES query body 建構 |
| `query_terms.py` | 查詢詞處理 |
| `evidence.py` | evidence 對外整理入口 |
| `evidence_core/` | evidence parser、snippet、topic match、date/text normalize 等拆分邏輯 |
| `ingest_sql.py` | SQL Server 匯入 Elasticsearch CLI |
| `ingest_txt.py` | TXT 匯入 Elasticsearch CLI |
| `synonyms/` | 同義詞或人工詞表 |

## 常見修改建議

- 查詢條件或排序改變：優先看 `query_body.py`。
- ES 連線或搜尋執行改變：優先看 `es_client.py`。
- 證據格式、引用、片段內容改變：優先看 `evidence.py` 與 `evidence_core/`。
- SQL 匯入 ES 改變：優先看 `ingest_sql.py` 與 `config/sql_import/`。

## 注意事項

- 檔名含 `複製`、`重構前` 的檔案通常是歷史備份，避免作為主要參考。
- 若修改 retrieval 行為，請檢查與 `agent/data_agent/` 的介面是否相容。
