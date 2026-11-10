# SRAF #393 / PR #395：news_test 實機事件時間唯讀驗收

**狀態：工具已可供 operator 實機驗證；截至尚未取得工作站上的實際結果，不可宣稱 LIVE PASS。** 本文件不授權自動 Merge。

## 驗收目的與限制

本工具僅對固定 `news_test` index 觀察：
- Elasticsearch 服務身份、受保護的 Basic principal 資訊以及嚴格 CA + **IP SAN** TLS 驗證
- 實際 index 名稱**必須**為 `news_test`（拒絕解析至其他實體 index 的同名 alias）；`multidim_event_json` → `Event`、`Event_Timeline`、`evidence_snippets` 必須為 nested，且 `time_iso:date`、`time_precision:keyword`、`event_id/event_ids:keyword`、`evidence_snippets.text:text` 等必要葉節點型別皆符合
- 從真實 Event、Timeline 各抽取最多一筆 ES 文件（記憶體處理，不輸出原文），在同一個結構化區塊內比對 Evidence `event_ids`
- 對抽樣 Event 的實際 precision，從 SRAF `_structured_date_filter()` **抽取該筆資料所需的單一 nested 分支**進行日期 GET 查詢（避免完整 14 分支 GET URL 超過 Elasticsearch 預設 4 KiB request-line 限制），再以 `_id` 對應查詢目標；其他精度分支未經此樣本驗證。資料足夠時額外觀察 2 個 ES 分頁沒有重複文件，並拒絕意外 `_index`

**只允許：** 嚴格 TLS、原生 GET `/`、GET `/_security/_authenticate`、GET `/news_test/_mapping`、最多四次 GET `/news_test/_search?source=...`。沒有 ES 寫入、Mapping 更新、重跑 GLM、SQL 寫入、LLM 生成、API／worker 重啟、scroll／PIT、檔案寫入或敏感資料輸出。GET URI 限長至 3072 字元，留出 HTTP request-line framing 空間。所有 HTTP 請求使用既有已審核的 `OFF-1B` HTTPS GET 傳輸，不匯入會放寬 TLS hostname 驗證的 runtime ES client。

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

### 第一步：Windows 本機 Git fetch → 選取 #395 → 本機打包

**正式沿用的流程是 Windows 本機 Git 更新與打包；GitHub Actions Artifact 僅為備援或 CI 驗證，不是必要的下載來源。**

在既有 Windows SRAF 原始碼目錄（例如 `D:\\shared\\TopicClassification\\poc-agent`）先更新遠端 refs。由於 #395 尚未合併 main，最安全的方式是在**Windows 本機**建立獨立工作目錄，避免讓原有主分支或未提交修改被測試版覆蓋：

```bat
cd /d D:\shared\TopicClassification\poc-agent
git fetch origin
git worktree add --detach ..\sraf-date-probe origin/fix/sraf-evidence-structured-event-time-20261110
cd ..\sraf-date-probe
python scripts\build_sraf_event_time_readonly_bundle.py
```

完成後會得到 `dist\\sraf-date-readonly.zip`。這是**在 Windows 執行 Git**；
Linux 不會執行 Git。如果你的 Windows 本機**已經切到** #395 對應的工作目錄，則不必額外建立 worktree，直接在該目錄執行製包 Python 即可。

產包前可在 Windows 用 `git rev-parse HEAD` 確認當前原始碼 SHA，並與 #395 最新 HEAD 比對；若程式碼版本不同，不可宣稱產包與最新 Code Review 一致。ZIP 內的 `_sraf_date_readonly/manifest.json` 會記錄 SHA 與各檔案 SHA-256。

GitHub Actions 仍會進行同一工具的安全測試與可選的 CI 產包。只有當你不方便在 Windows 本機產包時，才需改用
[`SRAF Event date read-only sidecar for incremental transfer`](https://github.com/hun186/poc-agent/actions/workflows/sraf-event-date-readonly-bundle.yml)
的 `sraf-event-date-readonly-no-git` Artifact，解出其中的
`sraf-date-readonly.zip`。

### 第二步：透過原有單向增量傳檔管道傳入 Linux

將**你剛才在 Windows 本機製作的 `dist\\sraf-date-readonly.zip`**
當作獨立增量檔案，沿用你原本的 Windows → Linux Robocopy／7z
上傳管道送到
`/mntCZJ/TopicClassification/`；不必為了驗收改動既有正式 SRAF 增量部署腳本或 `poc-agent-update.7z` 的程式內容；獨立 ZIP 必須確實由原管道送達，不能假設現有 BAT 自動包含它，
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
