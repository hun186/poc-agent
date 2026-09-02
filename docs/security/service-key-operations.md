# SRA Service Key 維運技術文件（中文版）

## 安全模型

Service Key 格式為 `sra_sk_<key_id>_<random_secret>`，由密碼學安全亂數產生。
完整明文只在建立時回傳一次；檔案只保存完整 Key 的 SHA-256 digest，驗證時使用
constant-time comparison。API／CLI 的 list、audit、exception 與 log 都不得輸出明文
或 digest。

Service Key 只會解析為 `service` principal，不能通過 Editor 的 `current_user()` 或
superuser RBAC。不同服務必須使用不同 Key：OpenWebUI 與未來 Batch client 不得共用。

### 與環境變數的關係

- `SRA_SERVICE_KEYS_FILE` **不是 Service Key**，只是 store 的檔案路徑；未設定時預設 `.sra_service_keys.json`。
- 真正交給 client（例如 OpenWebUI）的 credential 是 CLI 建立時只顯示一次的 `sra_sk_...`。
- `SRA_SIGNED_URL_SECRET` 是另一把獨立的 server-side HMAC secret，用來簽署瀏覽器限時 URL，不可拿來當 Service Key，也不可與 `sra_sk_...` 共用。由系統管理者在部署時自行產生一次，然後固定保存。例如用 Python 產生一個高強度隨機值：
python -c "import secrets; print(secrets.token_urlsafe(48))"
- API runtime 可透過專案 `.env` 載入這些設定；但目前 Service Key CLI 不主動載入 `.env`。若自訂 `SRA_SERVICE_KEYS_FILE`，CLI 執行環境也必須設定同一路徑。

## Scope 對照

| Scope | 用途 |
|---|---|
| `model:read` | 讀取 `/v1/models` |
| `model:invoke` | 呼叫 `/v1/chat/completions` |
| `report:sync` | 同步產生 Word |
| `report:job:create` | 建立 Report Job |
| `report:job:read` | 讀取自己擁有的 Job |
| `report:job:download` | 下載自己擁有的 Job artifact |
| `report:job:admin` | 跨 owner 管理 Job；一般 service 不應授予 |
| `document:read` | 直接讀取文件資源 |
| `report:legacy-download` | 直接存取 legacy Word export |

## CLI 操作

### 建立

```bash
python -m api.security.cli create-service-key \
  --name integration-name \
  --scope model:read \
  --scope model:invoke
```

### 列表與撤銷

```bash
python -m api.security.cli list-service-keys
python -m api.security.cli revoke-service-key KEY_ID
```

建立是唯一會輸出明文的操作。CLI 不接受 caller-supplied raw secret，避免祕密出現在
process list 或 shell history。

## HTTP 管理 API

只有現有 Editor `superuser` user token 可以呼叫；Service Key 即使具有其他 scope 也
不能管理 Key：

```text
POST /v1/auth/service-keys
GET  /v1/auth/service-keys
POST /v1/auth/service-keys/{key_id}/revoke
```

建立 response 只回傳一次明文；列表與撤銷 response 不含明文和 digest。

## 檔案、權限與併發

- 預設 store：專案根目錄 `.sra_service_keys.json`。
- 建議正式環境以 `SRA_SERVICE_KEYS_FILE` 指向受備份保護的 persistent volume；若自訂路徑，API 與 CLI 必須使用完全相同的值。
- store、lock 與暫存檔在 POSIX 系統應維持 owner-only 權限。
- 每次 mutation 會在同一個 in-process `RLock` 與 OS advisory lock 內完成
  `read → validate → mutate → fsync → atomic replace`，避免 API 與 CLI 跨 process
  同時寫入造成 lost update。
- JSON 損壞時應 fail closed 並保留原始 bytes；不可自動用空 store 覆蓋。

備份必須包含 service-key store，但備份檔本身也含驗證 digest，需套用與正式 store
相同的存取控制與保存政策。還原後應用 `list-service-keys` 檢查 metadata，並以實際
credential smoke test 驗證，而不要檢視或列印 digest。

## 事件處理與輪替

1. 發現疑似洩漏時立即撤銷對應 `key_id`。
2. 確認下一次使用舊 Key 的請求回 `401`。
3. 檢查不含 query string 或已遮罩 `sig` 的 reverse-proxy access log。
4. 以最小 scope 建立新 Key，更新 integration 後做 smoke test。
5. 記錄操作者、時間與原因，但不得把 Key 或 digest 寫入事件紀錄。

Phase 0 的 file store 是單機持久化，不是多機共享資料庫；多 instance 部署前必須另行
設計集中式 credential store。自動輪替、每 principal quota/rate limit 與 OpenWebUI
個別終端使用者身份傳遞也不在 Phase 0 範圍內。
