# OpenWebUI Service Key 設定指南（中文版）

本文件說明 SRA API 正式環境的安全參數，以及如何為 OpenWebUI 建立最小權限的 SRA Service Key。
OpenWebUI 的 Service Key 只代表 OpenWebUI 這個整合服務，**不代表個別 OpenWebUI 使用者**，也不能用來登入 Editor 或管理使用者。

## 0. 先分清楚三個名稱

| 名稱 | 誰產生 / 設定 | 誰使用 | 用途 |
|---|---|---|---|
| `SRA_SIGNED_URL_SECRET` | SRA 系統管理者在部署時產生一次 | SRA API 伺服器 | 簽署/驗證 citation、文件全文、Word 等限時瀏覽器 URL；production 必須固定且至少 32 bytes |
| `SRA_SERVICE_KEYS_FILE` | SRA 系統管理者設定（可省略） | SRA API / Service Key CLI | **只是 Service Key store 的檔案路徑，不是 Key**；未設定時預設 `.sra_service_keys.json` |
| `sra_sk_...` | `create-service-key` CLI 產生 | OpenWebUI | OpenWebUI 呼叫 `/v1/models`、`/v1/chat/completions` 時放在 `Authorization: Bearer ...` 的真正 API credential |

`SRA_SIGNED_URL_SECRET` 與 `sra_sk_...` 是兩種不同祕密，**不可共用**。`SRA_SERVICE_KEYS_FILE` 則不是祕密本身，只是檔案位置。

## 1. 用 `.env` 設定正式環境必要參數

專案的 API runtime 會透過 `config/bootstrap.py` 載入專案根目錄的 `.env` / `.env.{APP_ENV}` / `.env.local`，OS 環境變數優先。
正式部署可從 `.env.example` 複製為 `.env`，例如：

```env
APP_ENV=production
SRA_SIGNED_URL_SECRET=<請替換成部署時產生且固定保存的至少32-bytes隨機值>
CORS_ALLOWED_ORIGINS=http://192.168.0.134:3000

# 可選。省略時使用專案執行目錄下的 .sra_service_keys.json。
# 單機 Windows 部署通常可先使用預設值；production/container 可改成 persistent path。
# SRA_SERVICE_KEYS_FILE=D:/shared/TopicClassification/poc-agent/.sra_service_keys.json
# SRA_SERVICE_KEYS_FILE=/var/lib/sra/service-keys.json
```

### `SRA_SIGNED_URL_SECRET` 是誰產生的？

它不是 OpenWebUI、Ollama 或任何外部服務提供的 Key，而是 **SRA 系統管理者在正式部署時自行產生一次**的伺服器端簽章密鑰。
可用 Python 產生高強度隨機值：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把輸出值保存到 `.env`、作業系統 Secret Store 或組織核准的密碼管理系統。正式環境至少需要 32 bytes，且應保持固定；若每次重啟都換新值，先前尚未過期的 signed URL 會立即失效。

### `SRA_SIGNED_URL_SECRET` 用來做什麼？

SRA API 會把資源識別資訊、HTTP method 與到期時間綁定後，以 HMAC-SHA256 產生 signed capability。瀏覽器打開 citation、文件全文或 Word 下載 URL 時，SRA API 再用同一把 secret 驗證簽章與有效期限。使用者若竄改資源識別或期限，簽章會失效。

這把 secret **只留在 SRA API 伺服器端**，不需、也不應填入 OpenWebUI。

### `SRA_SERVICE_KEYS_FILE` 是什麼？

它只是指定 Service Key store 的檔案位置。store 保存 `sra_sk_...` 的 SHA-256 digest 與 scope/status metadata，不保存可還原的完整明文 Key。

未設定時：

```text
SRA_SERVICE_KEYS_FILE -> .sra_service_keys.json
```

若 API 與 CLI 都從同一個專案根目錄執行，使用預設值最簡單。若 production 需要把 store 移到 persistent volume，可指定絕對路徑。

> **目前 baseline 注意事項：** `python -m api.security.cli ...` 本身不主動呼叫 `bootstrap_env()`，因此自訂 `SRA_SERVICE_KEYS_FILE` 只寫在 `.env` 時，CLI 不一定會看到它。若有自訂路徑，執行 CLI 時必須另外用 OS/shell 環境變數提供同一路徑；否則 API 與 CLI 可能操作不同 store，造成 OpenWebUI 使用新 Key 時回 `401 Invalid credential`。

Windows CMD：

```bat
set "SRA_SERVICE_KEYS_FILE=D:\shared\TopicClassification\poc-agent\.sra_service_keys.json"
python -m api.security.cli list-service-keys
```

PowerShell：

```powershell
$env:SRA_SERVICE_KEYS_FILE = 'D:\shared\TopicClassification\poc-agent\.sra_service_keys.json'
python -m api.security.cli list-service-keys
```

Linux：

```bash
export SRA_SERVICE_KEYS_FILE='/var/lib/sra/service-keys.json'
python -m api.security.cli list-service-keys
```

## 2. 在 SRA API 主機建立 OpenWebUI Key

請在 SRA API 主機、專案根目錄執行，且只授予模型清單與對話所需權限：

```bash
python -m api.security.cli create-service-key \
  --name openwebui-production \
  --scope model:read \
  --scope model:invoke
```

Windows CMD 也可直接使用單行：

```bat
python -m api.security.cli create-service-key --name openwebui-production --scope model:read --scope model:invoke
```

指令會在 stdout **僅顯示一次**完整的 `sra_sk_...`。請立即存入組織核准的密碼管理系統；持久化檔只保存 SHA-256 digest，之後無法從 SRA API 還原明文。
不要用 shell history、CLI 參數或環境變數傳入自行指定的 Service Key。

## 3. 在 OpenWebUI 管理介面設定

由 OpenWebUI 管理員在 Provider／OpenAI-compatible connection 設定一次：

```text
Base URL: http://SRA_API_HOST:9002/v1
API Key:  sra_sk_...
```

這裡的 `API Key` **只填第 2 步產生的 `sra_sk_...`**，不是 `SRA_SIGNED_URL_SECRET`，也不是 `SRA_SERVICE_KEYS_FILE`。
不需、也不應要求每位終端使用者各自設定這把 Key。

設定後驗證：

```text
GET  /v1/models            -> 200
POST /v1/chat/completions  -> 200
POST /v1/report/jobs       -> 403（OpenWebUI Key 沒有 Batch 權限）
```

對話回傳的 citation 與 Word URL 使用限時 HMAC signed capability，瀏覽器點擊時不會取得 OpenWebUI Service Key。歷史訊息中的連結可能在 TTL 到期後失效，這是預期行為。

## 4. 撤銷與更換

若 Key 洩漏，先找出公開的 `key_id`，再立即撤銷：

```bash
python -m api.security.cli list-service-keys
python -m api.security.cli revoke-service-key KEY_ID
```

撤銷後的下一次請求應回傳 `401`。更換時先建立新 Key、更新 OpenWebUI、驗證模型清單與對話，再撤銷舊 Key，以縮短服務中斷時間。Phase 0 尚未提供自動輪替排程。

## 5. 常見問題

- `401 Invalid credential`：Key 格式錯誤、已撤銷、已到期，或 API 與 CLI 指向不同 `SRA_SERVICE_KEYS_FILE`。
- `403 Insufficient scope`：Key 有效但缺少 endpoint 所需 scope；不要為排除問題直接授予全部權限。
- citation／Word URL 回 `401`：連結已過期、遭修改，或服務重啟後使用了不同的 `SRA_SIGNED_URL_SECRET`。
- 正式環境無法啟動：確認 `SRA_SIGNED_URL_SECRET` 至少 32 bytes，且 `APP_ENV=production` 的設定正確。
- `.env` 已設定自訂 `SRA_SERVICE_KEYS_FILE`，但 CLI 仍看不到 Key：確認執行 CLI 的 shell 也有設定相同的 `SRA_SERVICE_KEYS_FILE`，或先使用預設 `.sra_service_keys.json`。

## 6. 安全原則

- 不要把 `.env`、完整 `sra_sk_...`、`SRA_SIGNED_URL_SECRET` 提交到 Git、貼到工單或寫進文件。
- `.env.example` 只保留 placeholder 與操作說明，不放真實 secret。
- `SRA_SIGNED_URL_SECRET` 是 server-side signing secret；`sra_sk_...` 是 OpenWebUI integration credential；兩者必須分離。
- `SRA_SERVICE_KEYS_FILE` 的 store 與備份雖只含 digest，也應視為敏感驗證資料並限制存取。
