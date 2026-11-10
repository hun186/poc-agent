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

## 一鍵執行（已在 #395 獨立工作樹時）

```bash
bash scripts/sraf_event_time_readonly.sh
```

無參數直接執行底層 Python 指令是 `--no-network`，絕不嘗試 ES 連線：

```bash
python tools/sraf_event_time_readonly_acceptance.py --no-network
```

### 不要切換正在運作的 SRAF 主目錄：使用獨立 Worktree

如果目前的 Linux 目錄是 `main`，又不希望更動已部署的程式碼，請在**原有部署 checkout**中執行：

```bash
DEPLOYED_ROOT="$PWD"
git fetch origin fix/sraf-evidence-structured-event-time-20261110
git worktree add --detach ../sraf-date-readonly origin/fix/sraf-evidence-structured-event-time-20261110
cd ../sraf-date-readonly
SRAF_CONFIG_ROOT="$DEPLOYED_ROOT" bash scripts/sraf_event_time_readonly.sh
```

驗收程式碼從獨立工作樹載入；原始部署的 `.env.local` 和 `agent/certs/http_ca.crt` 只會被讀取，**不需複製憑證或密碼到新目錄**。上述 Git 指令不更新、重啟或停掉原有 API 服務；使用 `git worktree` 會建立一份獨立的 Git 工作樹。確認原目錄確實是預期的 SRAF repo，並留意 `../sraf-date-readonly` 不要覆蓋既有目錄。

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
