# SRAF GLM 結構化全文欄位：部署前 Mapping 唯讀核對

## 背景

SRAF 的 `SRAF_STRUCTURED_FIELD_EXPANSION=on` 會在原本檢索上增加少量問題導向的 SHOULD 加分，分別查 `Event_Summary`、`Impact.impact_description`、`Event.consequence`、`Event.relation`、`Person.action`、`Person.relation`。PR #440 的程式根據 GLM Repository 中 InfoExtraction-MultiDim-mapping.yaml 設計，但 GLM 來源 YAML 不等於目前正式索引的 live Mapping。

既有 SRAF OFF-1B、Event-Time 唯讀驗收重點在 TLS、日期 nested、Event IDs 和 Evidence 型別，**不能代替新增六個 GLM TEXT 欄位的相容性核對**。

本工具只使用 **操作員已經另外透過授權、嚴格驗證的 ES API 所保存的一份實際索引 Mapping JSON**，讀檔對照固定允許清單。它**不會直接連 ES、不會查詢或下載新聞、不會拿帳密、不會寫 ES、不會開啟 `on`**。

## 受控操作

使用與 API 相容的應用 Python，在 Linux 私人目錄放置一份由授權操作員自行取得的 `GET /<index>/_mapping` 的完整 JSON，例如：

~~~json
{
  "news_test": {
    "mappings": {
      "properties": {
        "multidim_event_json": {
          "type": "nested",
          "properties": {
            "Event_Summary": { "type": "text" },
            "Event": {
              "type": "nested",
              "properties": {
                "consequence": { "type": "text" },
                "relation": { "type": "text" }
              }
            },
            "Person": {
              "type": "nested",
              "properties": {
                "action": { "type": "text" },
                "relation": { "type": "text" }
              }
            },
            "Impact": {
              "type": "nested",
              "properties": {
                "impact_description": { "type": "text" }
              }
            }
          }
        }
      }
    }
  }
}
~~~

這只是**最小結構示意，不是真正的 `news_test` Mapping**。正式驗收必須是 ES 伺服器實際 GET 的原始結果，不能用上述示例或 GLM YAML 自行組造再宣稱實機相容。

Mapping 快照檔需 owner-only（0600）、一般檔案、大小 1B–2MiB，不可為 symlink／FIFO，僅能有一個明確索引。不要使用不驗證 ES TLS 身分的請求方式，也不要把憑證、內網 IP、使用者登入資訊或快照內容上傳至 GitHub。

~~~bash
cd /mntCZJ/TopicClassification/poc-agent
python -m tools.sraf_glm_structured_mapping_preflight \
  /private/sraf_mapping_snapshot.json
~~~

固定格式的 `SRAF_GLM_MAPPING={...}` 輸出包含：
- `nested_verified/expected`：`multidim_event_json`、`Event`、`Person`、`Impact` 的 nested 邊界。
- `text_verified/expected`：上述六個應為 `text` 的葉節點。
- `missing_field_contracts`、`mismatched_field_contracts`：僅會顯示**程式中已固定的欄位名稱**，不輸出任意 ES 資料、索引名稱或來源內容。
- `structured_text_on_ab_ready`：全部四個 nested 層級與六個 TEXT 欄位存在、型別皆吻合才是 true；不完整／有差異回傳 `NOT_READY`、exit 2。
- `live_es_identity=NOT_ATTESTED_BY_TOOL`、`chinese_analyzer_quality=NOT_VERIFIED`：表示工具**不能驗證此快照來自當前正式 ES 或中文分析器分詞品質**，即使 PASS_COMPATIBLE 也不保證新欄位搜尋真的增加有效 Evidence。

若工具回傳 PASS_COMPATIBLE，下一步是由操作員確認快照索引與 ES 嚴格 TLS、取樣日期與查詢上下文一致，再執行兩次受控唯讀搜尋的 paired A/B；參考 `docs/operations/sraf_structured_field_pair_ab.md`。不得直接把 `SRAF_STRUCTURED_FIELD_EXPANSION=on` 設為正式預設。

## 不涵蓋的功能

- 不檢查 `Event.action`、`Person.stance`、`Involved_Parties.party_role`、`facet` 或 `core_entities` 是否有新中文全文分析器，因為目前新增 planner **不**把這些 keyword 欄位作 TEXT 搜尋。
- 不鑑定中文分詞器是否切得合理；即使為 `text`，Elasticsearch `standard` 也不保證符合所有中文語義需求。
- 不建立來源 ES TLS/IP SAN 可信身分，不核實 Mapping 快照時效，不量測新增命中數、誤收率或 Report Job Word 品質。
- 不更改 GLM 解析 YAML、ES Mapping、索引、LLM rerun 或任何部署檔案。
