# SRAF 封閉網路 Report Job：一鍵部署驗收與 Debug

本工具是 SRAF OFF-1 離線操作員的 Report Job/UI 驗收入口。它與 OFF-1A/1B/1S、OFF-1P/Q 等既有獨立證據相容，**不等於 OFF-2–5 全部實機、物理斷網或生產放行驗收**。在離線 Linux 部署 repo 根目錄，**必須使用啟動 SRAF API 的同一個 Python 應用環境**（例如已啟用的 venv/Conda 中的 `python`），包含部署時已安裝的 `python-dotenv`、`pyodbc` 等專案需求套件；此工具重用既有 OFF-1B/OFF-1S 探針，因此**並非 stdlib-only 的獨立 Python 腳本**。驗收當下不需要重新 pip 安裝、不需要 Node.js、網際網路或雲端服務，也不會重啟 API。若系統預設 `python3` 與 API 的應用 Python 不同，請使用 API 實際使用的 Python 絕對路徑。

## 現場一條指令

預設 quick（只讀、安全、不觸發 LLM／SQL／ES）：

    python tools/sraf_airgap_report_jobs_acceptance.py

額外診斷已設定的 API/ES/LLM TCP 連線（仍不呼叫模型，不讀取 ES/SQL）：

    python tools/sraf_airgap_report_jobs_acceptance.py --suite diagnose

純設定檢查、完全禁止連線：

    python tools/sraf_airgap_report_jobs_acceptance.py --suite diagnose --no-network

本工具依現有啟動器 shell PORT（預設 9002）連接本機 127.0.0.1，不把 PUBLIC_API_BASE 當作本機 listener。沿用已審查的 OFF-1A 絕對截止時間、上限 64 KiB 匿名 GET 測量 /healthz、/report-jobs、/static/report_jobs_ui.js 與 /static/report_jobs_ui.css。部分結果只證明 HTTP 200 與固定靜態內容片段，不代表頁面在真實瀏覽器可正常操作，也不代表 LLM 成功。diagnose 模式額外沿用 OFF-1B 有界私有 IPv4 TCP 探測；TCP 成功不是服務認證或端到端結果。

## 經授權的真實報告 E2E（會耗用 LLM 資源）

只有操作員明確選擇以下指令，才會建立 **一筆真實任務**：

    python tools/sraf_airgap_report_jobs_acceptance.py --live-report

輸入現有 SRAF 帳號與密碼，程式透過 POST /v1/auth/login 取得臨時 Token，記憶體內使用，不寫入檔案；具有 report:job:create、report:job:read、report:job:download 三種權限。若現場已有受控、可撤銷、限定權限的 Service Key，可以由安全的執行環境提供：

    python tools/sraf_airgap_report_jobs_acceptance.py --live-report --token-env SRAF_TEST_BEARER

環境變數 SRAF_TEST_BEARER 的明文須由現場安全機制設定，不能寫進版本庫，勿在 shell history 中硬編碼，使用後應移除。Service Key 原始明文無法從僅儲存雜湊的服務 Key 檔還原；.env.local 的 ES 認證與簽章 Secret 都不能當 Report Job Bearer Token。

**信任門檻：** 任何登入密碼或 Bearer 傳送之前，必須透過既有 OFF-1S 嚴格檢查 API launcher PID/start/cwd/socket 獨占擁有者。網路連線建立後、傳送憑證之前與收到回應後再次檢查同一身分。若 /proc 存取、FD_LIMIT、身分不符或程序異動使證據不夠，狀態為 INCOMPLETE／SKIP，完全不發送憑證。不要放寬身分驗證或把 PUBLIC_API_BASE 當作繞道；該失敗不必然是 API 程式故障。

真實流程為一次 POST /v1/report/jobs 建立固定非敏感測試報告、每 3 秒 GET owner-scoped 狀態、預設最多 20 分鐘、只有 completed 才 GET /word 並驗證 DOCX ZIP 完整性及 CRC。**不會對 POST 自動重試**；如 HTTP 回應丟失，Job 是否建立未知，不應再次盲目提交。20 分鐘超時也不會取消正在執行的 Worker。真實進度可能跳過短暫階段，long_running 是時間提示，不等於失敗。

## 驗收檔案、診斷與判讀

預設在本地新建 owner-only sraf-acceptance-results/（0700），每次輸出獨立 JSON 證據（0600）；有成功的實際 DOCX 時也在該目錄存檔（0600）。JSON 僅固定檢查類別、PASS/FAIL/SKIP 與原因碼、觀察到的 phase、耗時和下載 DOCX 摘要，不存帳密、Token、API 原始回應、內部 Job ID、文件內容、原始錯誤或 PID。請勿公開傳送 DOCX；可用 --output-dir 指定受控的現場目錄。

- Exit 0／PASS_PARTIAL：本次必要子項成功，絕不是整套 SRAF／OFF-5 通過。
- Exit 1／FAIL：有實際失敗證據。
- Exit 2／INCOMPLETE：部分檢查未驗證、缺乏授權或超時，不能當 PASS。

限制：這次整合只覆蓋 Report Job/UI 及基礎網路診斷，仍須獨立驗收 ES TLS/IP SAN/Mapping、SQL schema/來源、排程與 Worker lease、原始模型及資料檢索品質、真實瀏覽器操作、OFF-2～5 物理斷網、備份／還原等。以上尚未完成項目保留於 .codex/backlog.md，不得寫成已落地驗收。

## 最新 P2 防護與模式退出碼

輸出目錄的每一層 Linux 父目錄以 O_NOFOLLOW dirfd 固定檢查，私有輸出目錄須由執行 UID 擁有並僅授權本人存取。若中途存在符號連結、不可信或非 sticky 的其他人可寫入父目錄，則拒絕寫入；**目錄驗證失敗時連錯誤證據 JSON 都不寫入**。所有 DOCX、JSON 都以已驗證 dirfd 相對建立，避免路徑被替換而重導向輸出。部署工作目錄若為多人可寫，請指定可信獨立目錄（如 `--output-dir "$HOME/sraf-acceptance-results"`），不可為方便而放寬保護。

`--suite diagnose` 會把所選 API/ES/LLM TCP 探測全部納入頂層判定：任一 FAIL → exit 1/FAIL；無 FAIL 但存在 SKIP → exit 2/INCOMPLETE；全部必要子項 PASS 才 exit 0/PASS_PARTIAL。預設 quick 不要求外部 TCP 探測成功。無網路模式不可宣稱通過真實服務。

## 第二輪 Codex P2 修正

- **同一 Python 執行環境**：腳本會匯入原本部署的 OFF-1A/B/S 共用模組，依賴應用環境已安裝的套件。請勿用缺少 `dotenv`/`pyodbc` 的系統 `python3` 當作可獨立執行的 stdlib 驗收；保留離線、單一命令、無額外安裝的操作體驗。
- **截止時間前才准送出要求**：OFF-1S 的連線後身分驗證可能耗掉 HTTP 預算；在任何 HTTP 封包（尤其會建立 Job 的 POST）發送前，必須再次確認正剩餘時間，逾時直接阻擋，不得用 1 ms 下限繼續嘗試發送。
- **ZIP 損壞可診斷**：DOCX 的 DEFLATE 解壓損壞要產生 `report_docx=FAIL`，仍保留其餘安全的本地 JSON 證據，不讓 `zlib.error` 造成未處理 traceback。
