# SRAF 深度報告｜可移植部署與故障隔離（候選）

既有一般報告、GLM、ES 設定不用為深度模式改變。深度模式預設關閉。
僅在正式驗收後由操作者顯式設定：

```dotenv
# Example only: same container, certificate SAN includes loopback
SRAF_DEEP_ES_URL=https://127.0.0.1:9001
SRAF_DEEP_STARTUP_FAILURE_POLICY=ordinary_only
```

- 同容器使用符合憑證的 loopback；跨主機使用對應 SAN 的 HTTPS DNS/IP。
  既有 ES_URL 仍供原本路徑使用。未設定 deep override 才沿用 ES_URL。
  顯式空值或錯誤不會回退；不關閉 CA 或 hostname verification。
- fail_startup 是現有預設。ordinary_only 是顯式選擇：深度配置或專用 ES
  SDK 配置失敗時不啟用深度授權及自動派送，深度提交回 503；一般 Worker
  跳過深度 queued 工作，保留 Job/checkpoint，修正設定後正常重啟方可繼續。
  操作者以 ordinary_only 且顯式停用深度功能做遷移時，也保留 queued 深度工作。
  原有 running restart recovery、共享 DB/簽章錯誤、未知程式錯誤政策不變。
  全域 queue ceiling 仍可能計入保留的工作。
- CONFIGURED 是本地 SDK composition，不證明 TLS、PIT、LLM 或報告成功。
  後續深度執行錯誤不能改走一般 Agent 假冒深度結果。
- OpenWebUI 不需因這個 PR 修改 TLS、Valve 或金鑰。#505 個人 Token pilot
  暫緩；可信後端身分交接、瀏覽器登入銜接與多網段傳輸政策仍需獨立審查。
  不信任 raw user header、IP 或 shared service key 作為個人身分。

實際部署仍須獨立 E2E；本 PR 不改動任何實機配置。
