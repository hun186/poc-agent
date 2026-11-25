# SRAF 深度多輪報告｜部署前本地快檢

此工具只檢查目前 checkout 的環境設定與本地 ES SDK 建立／釋放，**不會連線到 ES 或 Ollama，不會啟動服務、建立工作、初始化 AuthStore、修改 SQLite 或生成 Word**。預設不讀設定，也不執行檢查。

在依既有 Windows 打包／Linux 解壓流程完成部署後，於預定啟動服務的專案目錄、同一 Python 環境及同一 OS env 執行：

```bash
python -B tools/sraf_deep_local_preflight.py --check
```

若要另外驗證自動派送開關及瀏覽器入口配置格式（不代表傳輸安全）：

```bash
python -B tools/sraf_deep_local_preflight.py --check --require-auto
```

執行前須依 AGENTS.md 安裝專案 requirements。套件缺漏或程式匯入錯誤會以非零程序退出，不會被誤列為配置錯誤；此時先修復 Python 環境。沿用正式啟動的設定優先序 OS env > .env.local > .env.{APP_ENV} > .env。只輸出固定狀態，不輸出帳號、索引、模型、網址、憑證路徑或例外內容。執行程序結束後不改動其他程序的 env。

- `PASS_PARTIAL`（exit 2）：本地配置合法，ES SDK/CA setup 完成；不是已連線，更不是正式驗收。
- `INCOMPLETE`（exit 2）：深度模式未開啟；維持現況，不會自動修改 flag。
- `FAIL`（exit 1）：本地設定或 SDK 準備失敗；依固定 reason 定位。若 require-auto 啟用，還需配置 auto mode。需要明確檢查 HTTPS 字串設定時，另加 `--require-https-browser`；這也要求 auto mode。
- `NOT_TESTED`（exit 2）：未指定 --check。

即使本地 PASS_PARTIAL，真實 ES TLS 主機身分、映射、PIT 權限及資料讀取、本地模型可用性、帳號 grant、代理及 OpenWebUI 版本/加密、一般／深度 Word 都仍是 NOT_TESTED。HTTPS_CONFIGURED / HTTP_CONFIGURED 只表示字串設定，不代表 TLS、受保護通道、credential 傳輸或瀏覽器實測通過。不因本地快檢就允許跨主機 HTTP 敏感流量，也不要求修改既有 OpenWebUI 金鑰或對外 TLS。#505 pilot 暫緩。專用 SRAF_DEEP_ES_URL 由正式 SDK setup 檢查，明確空值不回退。後續真實驗收必須另行確認，不要把此工具的 exit 2 當成全驗收成功。
