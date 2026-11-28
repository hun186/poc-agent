# SRAF #393 / PR #395：news_test 實機事件時間唯讀驗收

**狀態：PR #395 已合併至 main；現有 Linux 實測確認 CA_CHAIN=PASS、IP_SAN=MISMATCH，日期 Mapping／搜尋還未取得實機驗收結果。** 本文件不代表 FULL_LIVE 已通過。

## 驗收目的與限制

本工具僅對固定 `news_test` index 觀察：
- Elasticsearch **CA 憑證鏈強制驗證**、受保護的 Basic principal 資訊以及 IP SAN 觀測。為支援 LAN／無聯網搬遷後 IP 變更，日期唯讀驗收的標準 Shell 入口將 IP SAN 不符標示為 **WARN** 而不中止後續唯讀檢查；另保留嚴格模式。
- 實際 index 名稱**必須**為 `news_test`（拒絕解析至其他實體 index 的同名 alias）；`multidim_event_json` → `Event`、`Event_Timeline`、`evidence_snippets` 必須為 nested，且 `time_iso:date`、`time_precision:keyword`、`event_id/event_ids:keyword`、`evidence_snippets.text:text` 等必要葉節點型別皆符合
- 從真實 Event、Timeline 各抽取最多一筆 ES 文件（記憶體處理，不輸出原文），在同一個結構化區塊內比對 Evidence `event_ids`
- 對抽樣 Event 的實際 precision，從 SRAF `_structured_date_filter()` **抽取該筆資料所需的單一 nested 分支**進行日期 GET 查詢（避免完整 14 分支 GET URL 超過 Elasticsearch 預設 4 KiB request-line 限制），再以 `_id` 對應查詢目標；其他精度分支未經此樣本驗證。資料足夠時額外觀察 2 個 ES 分頁沒有重複文件，並拒絕意外 `_index`

**只允許：** CA 驗證強制開啟的 HTTPS（IP SAN 在 operator 日期驗測可以只警告）、原生 GET `/`、GET `/_security/_authenticate`、GET `/news_test/_mapping`、最多四次 GET `/news_test/_search?source=...`。沒有 ES 寫入、Mapping 更新、重跑 GLM、SQL 寫入、LLM 生成、API／worker 重啟、scroll／PIT、檔案寫入或敏感資料輸出。GET URI 限長至 3072 字元，留出 HTTP request-line framing 空間。所有 HTTP 請求使用既有已審核的 `OFF-1B` HTTPS GET 傳輸，不匯入會放寬 TLS hostname 驗證的 runtime ES client。

**驗收結果不等於正式上線**：只抽少量真實文件，未完整覆蓋 Event-only／Timeline-only／缺失精度／跨 index 同 UUID／不同本地時區／10k 預算補取。這些仍須額外獨立的唯讀 E2E 測量，否則 #395 不應視為全實機驗收。

## LAN IP 變更的驗測政策（2026-11-11）

**正常日期驗收（CA 必須有效，IP SAN 不符改為警告並繼續）：**

```bash
cd /mntCZJ/TopicClassification/poc-agent
bash scripts/sraf_event_time_readonly.sh
```

- 只有 **CA 鏈驗證成功**且 HTTP 來源是既有受控內網 ES 時，才允許記錄 `ip_san_mismatch_ca_chain_verified`。此模式使用既有 OFF-1B `warn_only_ip_san=True`；CA 驗證仍為 `CERT_REQUIRED`，不使用 `--insecure` 或取消 CA 鏈驗證。
- 如果憑證沒有包含目前連線的 IP，繼續觀測受保護的 principal、固定 `news_test` Mapping／日期查詢，結果明列 `identity=CA_VERIFIED_IP_SAN_MISMATCH`、`tls_validation=WARN`、`identity_warning=true`、`release_tls_identity_verified=false`。**日期抽樣全部符合時可為 `PASS_PARTIAL`，不因 SAN WARN 自動變成 `INCOMPLETE`；但不能宣稱嚴格 TLS 身分已通過。**
- 此模式仍將 Basic 憑證交給「由設定 CA 簽發、但 IP 身分未證明」的目標。因此僅供操作者確認為可信私有 LAN／封閉網路的唯讀驗測；如 CA 被多個服務共用或路由可能遭替換，就應維持嚴格模式或重新簽發正確 SAN 憑證。即使日期結果 `PASS_PARTIAL`，**不等同 FULL_LIVE／正式安全驗收。**
- **CA 驗證失敗、憑證異常、HTTP 身分／認證不符仍立即停止**；Mapping 或日期功能失敗仍為 `FAIL`，不被 SAN 警告掩蓋。沒有索引寫入、LLM 呼叫、SQL 寫入或服務重啟。

若要完全保持原本 **CA + IP SAN 強制驗證**，使用：

```bash
bash scripts/sraf_event_time_readonly.sh --strict-ip-san
```

直接執行 Python CLI 的 `--run` 仍預設嚴格模式；只有明確傳入 `--run --warn-only-ip-san` 才放寬 IP SAN 的 **operator 診斷**。與正式 API、ES client、L1/L2 嚴格檢查完全分離。

## 標準部署方式：既有 Windows BAT → 7z → Linux 單向增量解壓

**此節是 SRAF 常態部署的唯一預設操作方式；不需要另外建立 Git Worktree、另行 checkout PR，或在 Linux 執行 Git。**

原本的 Windows 來源是 `D:\shared\TopicClassification\poc-agent`，已存在的本機 BAT 是 `133_rocopy_7z_poc-agent_pr_ref_runtime_complete.bat`（BAT 保留在原本 Windows 所在位置；不假設它在 GitHub repo 裡）。正常執行時，**不要附加 `--pr`、`--ref` 或 `--offline`**：

```bat
REM 在 BAT 實際所在資料夾執行；也可以直接雙擊原 BAT。
call "133_rocopy_7z_poc-agent_pr_ref_runtime_complete.bat"
```

這支既有 BAT 的流程包含：

1. 先在 **Windows 原本的同一份 `poc-agent` Git 目錄**確認／更新 `origin/main`（內含 Git fetch、必要時 fast-forward，對真實本機修改則 fail closed）；不額外建立 Worktree。
2. 清理專用的 `D:\temp\poc-agent-package` 暫存包，以 Robocopy 的 `/MAXAGE`（預設 3 天）做增量選檔；另依 Requirement E2E provenance manifest **強制帶入並 hash 驗證所有管理中的 runtime files**，避免僅依檔案日期漏掉必要程式。
3. 排除 `.git`、`.env.local`、`e2e.env.local`、快取及其他暫存資訊；建立 `D:\temp\poc-agent-update.7z`，並在製包失敗時停止。
4. 沿用原有 Windows → Linux 單向上傳方式（不要將示例指令當成新的上傳系統）；將 `poc-agent-update.7z` 送至既有 Linux 部署位置。
5. 在 Linux **沿用現有覆蓋解壓程序**，例如檔案已上傳至部署目錄時：

```bash
cd /mntCZJ/TopicClassification/poc-agent
7z x poc-agent-update.7z -y
```

以上解壓是**增量覆蓋**，不執行 `git fetch`／`git pull`、不做 `/MIR` 清空、也不會自動刪除曾經同步但後來從 GitHub 移除的舊檔。若需 API／Worker 重啟及驗收，仍使用既有另行授權的維護程序；製包與解壓本身不代表 `FULL_LIVE` 通過。

**#395 已合併：** 正常 BAT 不帶參數更新 `origin/main` 即可取得 #395 事件日期功能，不需要 `--pr 395`、額外 Worktree 或 Linux Git。即使已有最新程式，實機日期／DOCX 測試狀態仍須另外驗收。

### 之前誤建的 Windows Worktree 如何還原

若曾執行 `git worktree add --detach ..\sraf-date-probe ...`，在原本 Windows `poc-agent` 目錄內執行：

```bat
cd /d D:\shared\TopicClassification\poc-agent
git worktree list
git -C ..\sraf-date-probe status --short
git worktree remove ..\sraf-date-probe
git worktree list
git status -sb
```

`git worktree remove` 若因本機新增／修改檔案而拒絕，就**停止檢查**，不可強制刪除；它不需要對原本 `main` 執行 reset 或 clean。先前單獨執行的 `git fetch origin` 也不會修改原本工作檔案，無須回滾。

## 可選的隔離 Sidecar 唯讀實機日期驗收（非 BAT 正式部署）

既有獨立 `sraf-date-readonly.zip` 是為了在**不覆蓋正式 API 模組**的情況下讀取 `news_test`；它**不是**常態增量部署，也不應取代上面的 BAT。若要在不覆蓋正在運作的模組時另外執行此測試，可由 [Sidecar CI workflow](https://github.com/hun186/poc-agent/actions/workflows/sraf-event-date-readonly-bundle.yml) 的**對應 PR HEAD**產出 `sraf-event-date-readonly-no-git` Artifact，再從中取得 `sraf-date-readonly.zip`，沿用既有單向傳送路徑上傳；**Windows 不必建立 Worktree，也不必把整個未合併 PR 覆蓋到正式 Linux**。

若單獨 ZIP 傳到 `/mntCZJ/TopicClassification/`：

```bash
cd /mntCZJ/TopicClassification
7z x sraf-date-readonly.zip -y
bash _sraf_date_readonly/run.sh
```

此工具只從現有部署目錄讀取 `.env.local`／CA，Sidecar 入口原本預設嚴格 TLS GET；如需對既有 LAN 換 IP 的憑證採 **CA 驗證 + SAN WARN**，可執行 `bash _sraf_date_readonly/run.sh --warn-only-ip-san`。不重新啟動 SRAF；若工具放在 `poc-agent/_sraf_date_readonly` 獨立子目錄，則執行 `bash /mntCZJ/TopicClassification/poc-agent/_sraf_date_readonly/run.sh`。若只檢查腳本可啟動而不連內網：

```bash
cd /mntCZJ/TopicClassification/_sraf_date_readonly
python tools/sraf_event_time_readonly_acceptance.py --no-network
```

這個 Sidecar 不證明完整多精度日期覆蓋、真正 Report／DOCX E2E 或正式 release readiness；沒有操作人員的真實 `news_test` 證據時標記為 `NOT_TESTED`。**不因 Sidecar 存在而改變常態 BAT 操作，也不預設執行 Sidecar。**

## 輸出與判定（安全可貼回對話）

只輸出一行無敏感內容的 JSON，包含 `schema`、固定 index 名稱、各項狀態、抽樣數量及穩定失敗原因，**不會輸出 ES_URL、帳密、憑證、真實文章、uuid、event_id、_id 或查詢回傳原文**。

| 狀態 | 代表意義 | 程式 exit code |
| --- | --- | --- |
| `PASS_PARTIAL` | Mapping／抽樣日期查詢／兩頁檢查有實際觀測成功；若 `identity_warning=true` 則只保證 CA 驗證，SAN 不符仍為 WARN，絕非完整 LIVE／TLS 身分驗收 | 2 |
| `INCOMPLETE` | 憑證身份不符、實際資料不足、Mapping/查詢未完成或部分步驟觀測不到 | 2 |
| `FAIL` | 已取得與 SRAF 時間契約不符的 Mapping，或實際事件日期查詢明確失敗 | 1 |
| `NOT_TESTED` | 明確未啟用連線（安全預設） | 2 |

CA 憑證鏈驗證不通過時**必須停止**。IP SAN 不符時，operator 日期驗測可在 CA 驗證成功且明確標記 `identity_warning=true` 的前提下，繼續唯讀日期檢查；這是**受限制的觀測**，不是嚴格 TLS 身分 PASS。嚴格模式仍對 SAN 不符回報 `INCOMPLETE`。若要取得正式安全驗收，應修正 IP SAN 或用另一種可審核的身分綁定方法。

如需回報，直接貼唯一的 JSON 輸出即可；**不要貼 `.env.local`、帳號密碼或實際新聞／Evidence 原文**。

## 完成門檻

- [ ] 實機成功取得完整且乾淨的唯讀 JSON 觀測結果，無 `FAIL` / `INCOMPLETE`
- [ ] 對 Event-only、Timeline-only、不同精度與同 ID 跨區塊等真實資料再做必要的抽樣比對（若索引沒有這類資料，標記 `NOT_OBSERVED`）
- [ ] 觀測實際不同文件排序、ES paging／結果限制／高負載下的時間成本，不把合成測試當成實機吞吐證據
- [ ] 真實 SRAF API→Evidence→報告→DOCX 全鏈路在不修改正式索引的條件下完成驗收
- [ ] PR #395 最新 SHA 的 Hosted CI + Code Review 再次確認符合 Gate

如果前四項無法在這個工具內全部實測，標示 `PASS_PARTIAL`／`NOT_TESTED`，保持 PR Open。Issue #393 持續追蹤，不能以此工具的 exit 2 結果跳過正式驗收。
