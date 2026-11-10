# SRAF #393 / PR #395：news_test 實機事件時間唯讀驗收

**狀態：工具已可供 operator 實機驗證；截至尚未取得工作站上的實際結果，不可宣稱 LIVE PASS。** 本文件不授權自動 Merge。

## 驗收目的與限制

本工具僅對固定 `news_test` index 觀察：
- Elasticsearch 服務身份、受保護的 Basic principal 資訊以及嚴格 CA + **IP SAN** TLS 驗證
- `multidim_event_json` → `Event`、`Event_Timeline`、`evidence_snippets` 的實際 nested Mapping，以及事件日期的 `date` 欄位
- 從真實 Event、Timeline 各抽取最多一筆 ES 文件（記憶體處理，不輸出原文），在同一個結構化區塊內比對 Evidence `event_ids`
- 對抽樣事件日期實際發出 SRAF `_structured_date_filter()` 的 nested 日期查詢，並用 `_id` 對應查詢目標；如果資料足夠，額外檢查 2 個候選 ES 分頁沒有重複文件

**只允許：** 嚴格 TLS、原生 GET `/`、GET `/_security/_authenticate`、GET `/news_test/_mapping`、最多四次 GET `/news_test/_search?source=...`。沒有 ES 寫入、Mapping 更新、重跑 GLM、SQL 寫入、LLM 生成、API／worker 重啟、scroll／PIT、檔案寫入或敏感資料輸出。所有 HTTP 請求使用既有已審核的 `OFF-1B` HTTPS GET 傳輸，不匯入會放寬 TLS hostname 驗證的 runtime ES client。

**驗收結果不等於正式上線**：只抽少量真實文件，未完整覆蓋 Event-only／Timeline-only／缺失精度／跨 index 同 UUID／不同本地時區／10k 預算補取。這些仍須額外獨立的唯讀 E2E 測量，否則 #395 不應視為全實機驗收。

## 交付方式：沿用 Windows Robocopy／7z 的單向增量部署，不在 Linux 用 Git

**重要環境契約：** Linux 的 `/mntCZJ/TopicClassification/poc-agent` 是
Windows 開發端製作 `poc-agent-update.7z`、單向傳輸並增量覆蓋的部署結果，
**不是 Git checkout**。絕不要求 Linux 執行 `git fetch`、`git pull`、
`git status`、`git worktree`，也不假設 Linux 有外網。

為了在 #395 尚未合併 main 前做唯讀實機驗證，採用**獨立 Sidecar ZIP**：
它只含驗收 Python 檔及必要的少量只讀匯入模組，**不包含**
`.env*`、CA 憑證、SQL 設定、新聞／報告、Git、API 主程式或任何資料。
Linux 上只需要現有 Python 環境與既有 SRAF 憑證，完全不動正在執行的 SRAF。

### 第一步：Windows／外網開發端製包（只執行一次）

優先在 GitHub Actions 的
[`SRAF Event date read-only sidecar for incremental transfer`](https://github.com/hun186/poc-agent/actions/workflows/sraf-event-date-readonly-bundle.yml)
找到 #395 **最新 head SHA 的成功 Run**，下載名為
`sraf-event-date-readonly-no-git` 的 Artifact，從 GitHub 提供的下載檔
解出真正的 `sraf-date-readonly.zip`。

如果 Windows 開發機已經有**對應 PR #395 版本**的原始碼，也可在
Windows 端自行製包（**不是**在 Linux 上製包或 Git 更新）：

```powershell
python scripts/build_sraf_event_time_readonly_bundle.py
```

會產生 `dist/sraf-date-readonly.zip`。包內
`_sraf_date_readonly/manifest.json` 記錄各個檔案 SHA-256，
供檢查增量傳輸後檔案一致性。這個 ZIP 不會封入整個 SRAF Repo。

### 第二步：透過原有單向增量傳檔管道傳入 Linux

將 **`sraf-date-readonly.zip`** 當作獨立增量檔案，沿用現有的
Windows → Linux Robocopy／7z 傳輸流程送到
`/mntCZJ/TopicClassification/`；不須變更既有
`133_rocopy_7z_poc-agent...` BAT、`poc-agent-update.7z` 正式更新內容，
更不須切換或停止現有服務。

如果既有流程只能將檔案增量覆蓋到 `poc-agent` 目錄內，也可以把 ZIP
或解壓後的 `_sraf_date_readonly/` 放在該目錄下的獨立子資料夾；
只要不覆蓋其他原有模組即可。Sidecar `run.sh` 能自動判斷
`_sraf_date_readonly` 是與 `poc-agent` 平行，還是位在其下。

### 第三步：Linux 端一鍵執行（不使用 Git）

若 ZIP 傳到 `/mntCZJ/TopicClassification/`：

```bash
cd /mntCZJ/TopicClassification
7z x sraf-date-readonly.zip -y
bash _sraf_date_readonly/run.sh
```

若原本增量包已經將 `_sraf_date_readonly/` 覆蓋到
`/mntCZJ/TopicClassification/poc-agent/`，只需：

```bash
bash /mntCZJ/TopicClassification/poc-agent/_sraf_date_readonly/run.sh
```

Runner 只會**讀取**原部署目錄的 `.env.local`／CA 憑證，執行固定索引
`news_test` 的嚴格 HTTPS GET 唯讀驗收；無須重啟 `run_sra_api.sh`
或安裝另一個系統服務。若非預設路徑，使用
`SRAF_CONFIG_ROOT=/實際/部署目錄` 指定原有 SRAF 目錄。

若只想先檢查 Python 腳本能否啟動而**不碰內網 ES**：

```bash
cd /mntCZJ/TopicClassification/_sraf_date_readonly
python tools/sraf_event_time_readonly_acceptance.py --no-network
```

以上不更新原本 Linux 工作樹、不搬動持久資料、不要求 /MIR、
刪除過期檔案、清空部署目錄、改寫 .env、重新啟動 API、重新索引或
執行 SQL/LLM。

## 輸出與判定（安全可貼回對話）

只輸出一行無敏感內容的 JSON，包含 `schema`、固定 index 名稱、各項狀態、抽樣數量及穩定失敗原因，**不會輸出 ES_URL、帳密、憑證、真實文章、uuid、event_id、_id 或查詢回傳原文**。

| 狀態 | 代表意義 | 程式 exit code |
| --- | --- | --- |
| `PASS_PARTIAL` | 嚴格 TLS/Mapping/抽樣日期查詢與兩頁檢查有實際觀測成功，但非完整 LIVE 驗收 | 2 |
| `INCOMPLETE` | 憑證身份不符、實際資料不足、Mapping/查詢未完成或部分步驟觀測不到 | 2 |
| `FAIL` | 已取得與 SRAF 時間契約不符的 Mapping，或實際事件日期查詢明確失敗 | 1 |
| `NOT_TESTED` | 明確未啟用連線（安全預設） | 2 |

嚴格 CA／IP SAN 驗證不通過時，**停止**，不以 `--insecure`、關閉 hostname 驗證、警告但繼續取得真實資料的方式宣稱 PASS。若你先前的 OFF-1B 顯示 SAN WARN，這個嚴格驗收可能只會得到 `INCOMPLETE`，必須先釐清 ES 憑證上的合法 IP SAN／信任鏈問題，不能把 WARN 當成 PASS。

如需回報，直接貼唯一的 JSON 輸出即可；**不要貼 `.env.local`、帳號密碼或實際新聞／Evidence 原文**。

## 完成門檻

- [ ] 實機成功取得完整且乾淨的唯讀 JSON 觀測結果，無 `FAIL` / `INCOMPLETE`
- [ ] 對 Event-only、Timeline-only、不同精度與同 ID 跨區塊等真實資料再做必要的抽樣比對（若索引沒有這類資料，標記 `NOT_OBSERVED`）
- [ ] 觀測實際不同文件排序、ES paging／結果限制／高負載下的時間成本，不把合成測試當成實機吞吐證據
- [ ] 真實 SRAF API→Evidence→報告→DOCX 全鏈路在不修改正式索引的條件下完成驗收
- [ ] PR #395 最新 SHA 的 Hosted CI + Code Review 再次確認符合 Gate

如果前四項無法在這個工具內全部實測，標示 `PASS_PARTIAL`／`NOT_TESTED`，保持 PR Open。Issue #393 持續追蹤，不能以此工具的 exit 2 結果跳過正式驗收。
