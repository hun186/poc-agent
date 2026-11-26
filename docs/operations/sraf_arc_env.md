# SRAF ARC 環境變數啟用指南

以根目錄 `.env.example` 的「SRAF ARC 自適應檢索控制器」區塊為設定清單。
複製需要的設定到現有私有 `.env`，如已存在同名設定則更新，不要整份覆蓋連線設定或重複定義。
依部署方式重啟 API / Worker。不要把私有設定檔或憑證提交 Git。

## 1. 建議第一階段：本地觀察（不增加 ES / LLM 呼叫）

```dotenv
SRAF_ARC_GROUP_FREQUENCY=shadow
SRAF_ARC_RANK=shadow
SRAF_ARC_TIGHTEN=shadow
SRAF_ARC_RELAX=shadow
SRAF_ARC_ORDINARY_RESOURCE_METRICS=shadow
SRAF_ARC_DEEP_RESOURCE_METRICS=shadow
```

保持其餘 ARC 開關 off。A3/A4 共用掃描預算；超出時略過。A5/A6 普通報告只計算反事實統計，並不採用新 Evidence。
資源觀察是既有介面的部分量測，不是完整的端到端用量。仍需先在私有環境量測負載。

## 2. 可選：A2/A7 額外模型策略觀察

```dotenv
SRAF_ARC_BILINGUAL=shadow
SRAF_ARC_STRATEGY=shadow
SRAF_ARC_LLM_PRIORITY=shadow
```

此組合可能透過既有模型 client 額外呼叫 LLM（TOPIC_LLM_URL 是啟用條件，實際端點由既有 client 設定決定）。
送出問題及語意群組，不送 Evidence 正文；先確認模型的資料政策。共用預算及優先分配會按條件略過，不保證每次均執行。

## 3. 可選：ES 原生 DF（核對實機及索引授權後）

```dotenv
SRAF_ARC_ES_FREQUENCY=shadow
SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX=<VERIFIED_CONCRETE_INDEX>
SRAF_ARC_RANK_NATIVE=shadow
```

以已驗證的具體索引取代 placeholder；不要直接照抄。普通報告的 DF 與初篩並非同 PIT。
深度報告另有 SRAF_ARC_DEEP_FREQUENCY、SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX、
SRAF_ARC_RANK_DEEP，但需要受信任 Worker 注入獨立統計授權，不能只靠 env 開啟。
驗證 mapping/analyzer、資料集合授權及負載後才考慮使用。

## 4. A8 語意複查：未完成生產授權前保持關閉

SRAF_ARC_REVIEW_SCOPE 只準備普通報告本地候選樣本，不會把正文送出。
SRAF_ARC_REVIEW、SRAF_ARC_REVIEW_DEEP、SRAF_ARC_REVIEW_EGRESS、SRAF_ARC_REVIEW_VERIFIED_INDEX、
SRAF_ARC_REVIEW_ENDPOINT、SRAF_ARC_REVIEW_MODEL、SRAF_ARC_REVIEW_CA_FILE
需配合實際受信任來源、端點、模型及 egress 政策。不能以 env 取代權限。
SRAF_ARC_REVIEW_RESOURCE_METRICS 只量測已獲授權的額外模型傳輸。
目前普通報告 A8 正式傳輸未接入，深度報告亦未提供生產授權政策。

## 5. A9 私有操作工具

SRAF_ARC_CAPTURE_ES_URL、SRAF_ARC_CAPTURE_ES_USERNAME、SRAF_ARC_CAPTURE_ES_PASSWORD、
SRAF_ARC_CAPTURE_ES_CA_FILE 是獨立唯讀擷取命令的設定，並非報告執行開關。
參考 [樣本擷取指南](sraf_arc_primary_capture.md)。擷取資料及標註均留在私有主機。

## 6. 回退

將所有 ARC 模式設定恢復 `off`，並將 SRAF_ARC_REVIEW_EGRESS 恢復 `off`，
清空不再使用的 ARC 專用索引及端點設定，再重啟相關程序。不要修改原有 ES 或模型帳密。
本指南的 ARC shadow 開關不會啟用新的正式 Evidence 選擇；既有 SRAF_TOPIC_MATCH_ADAPTIVE
是不同功能，`on` 可能改變正式 Evidence，不能當作整套 ARC 啟用或回退開關。

## 7. 後續整體模式

目前沒有已實作的 ARC 主開關或正式策略組合。正式啟用前應建立一個簡單的整體模式，
以明確優先順序處理個別 override，並保持索引、傳輸授權、A/B 驗收、共用預算及回退條件獨立。
未實作、未驗收的整體模式不得寫入樣本當成可用設定。
新增 ARC env 讀取時，同步更新根目錄樣本與此指南。
