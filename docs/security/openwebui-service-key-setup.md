# OpenWebUI Service Key 設定指南（中文版）

本文件說明如何為 OpenWebUI 建立最小權限的 SRA Service Key。這把 Key 只代表
OpenWebUI 這個整合服務，**不代表個別 OpenWebUI 使用者**，也不能用來登入 Editor
或管理使用者。

## 1. 先設定正式環境必要參數

正式環境必須設定固定且至少 32 bytes 的簽章密鑰，否則 SRA API 會拒絕啟動：

```bash
export APP_ENV=production
export SRA_SIGNED_URL_SECRET='請替換成至少32-bytes且由密碼管理系統提供的隨機值'
export SRA_SERVICE_KEYS_FILE='/var/lib/sra/service-keys.json'
export CORS_ALLOWED_ORIGINS='https://openwebui.example.internal'
```

`SRA_SIGNED_URL_SECRET` 用於瀏覽器下載連結，與下方的 Service Key 是兩種不同祕密，
不可共用。不要把任何真實密鑰提交至 Git、貼到工單，或寫進本文件。

## 2. 在 SRA API 主機建立 OpenWebUI Key

請直接在 SRA API 主機執行，且只授予模型清單與對話所需權限：

```bash
python -m api.security.cli create-service-key \
  --name openwebui-production \
  --scope model:read \
  --scope model:invoke
```

指令會在 stdout **僅顯示一次**完整的 `sra_sk_...`。請立即存入組織核准的
密碼管理系統；持久化檔只保存 SHA-256 digest，之後無法從 SRA API 還原明文。
不要用 shell history、CLI 參數或環境變數傳入自行指定的 Service Key。

## 3. 在 OpenWebUI 管理介面設定

由 OpenWebUI 管理員在 Provider／OpenAI-compatible connection 設定一次：

```text
Base URL: http://SRA_API_HOST:9002/v1
API Key:  sra_sk_...
```

不需、也不應要求每位終端使用者各自設定這把 Key。設定後驗證：

```text
GET  /v1/models            → 200
POST /v1/chat/completions  → 200
POST /v1/report/jobs       → 403（OpenWebUI Key 沒有 Batch 權限）
```

對話回傳的 citation 與 Word URL 使用限時 HMAC `sig` capability，瀏覽器點擊時不會
取得 OpenWebUI Service Key。歷史訊息中的連結可能在 TTL 到期後失效，這是預期行為。

## 4. 撤銷與更換

若 Key 洩漏，先找出公開的 `key_id`，再立即撤銷：

```bash
python -m api.security.cli list-service-keys
python -m api.security.cli revoke-service-key KEY_ID
```

撤銷後的下一次請求應回傳 `401`。更換時先建立新 Key、更新 OpenWebUI、驗證模型
清單與對話，再撤銷舊 Key，以縮短服務中斷時間。Phase 0 尚未提供自動輪替排程。

## 5. 常見問題

- `401 Invalid credential`：Key 格式錯誤、已撤銷、已到期，或 API 與 CLI 指向不同
  `SRA_SERVICE_KEYS_FILE`。
- `403 Insufficient scope`：Key 有效但缺少 endpoint 所需 scope；不要為排除問題直接
  授予全部權限。
- citation／Word URL 回 `401`：連結已過期、遭修改，或服務重啟後使用了不同的
  `SRA_SIGNED_URL_SECRET`。
- 正式環境無法啟動：確認 `SRA_SIGNED_URL_SECRET` 至少 32 bytes，且
  `APP_ENV=production` 的設定正確。

