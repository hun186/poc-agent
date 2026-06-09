# FastAPI Auth Pack

這個子目錄是一包可搬移的 **FastAPI 帳號管理套用素材包**。目標是讓你把整個 `portable_auth_pack/` 複製到另一個網頁服務專案後，讓 Codex 或開發者用「嵌入既有程式」的方式導入帳密管理能力：

- 帳號註冊：新帳號預設為 `pending`
- 帳密登入：回傳 Bearer token，並記錄登入稽核
- `/v1/auth/me`：查詢目前登入者
- 密碼安全：使用者可變更密碼、superuser 可重設密碼、忘記密碼可建立一次性 reset token
- Token 失效：logout 會加入 token denylist；變更/重設密碼會讓該帳號既有 token 失效
- 使用者審核：superuser 可核准、拒絕、刪除帳號
- 權限 dependency：`current_user` 與 `require_superuser`
- 本機 JSON user store：不需要資料庫即可快速試用

> 適用情境：內部工具、PoC、測試環境、受控網路環境、或作為 Codex 導入其他專案時的修改基礎。

---

## 目錄結構

```text
portable_auth_pack/
├── README.md
├── CODEX_IMPORT_GUIDE.md
├── fastapi_auth_pack/
│   ├── __init__.py
│   ├── auth_store.py
│   ├── dependencies.py
│   ├── models.py
│   └── router.py
├── examples/
│   ├── bootstrap_superusers.test.json
│   ├── env.example
│   └── main.py
├── scripts/
│   └── verify_auth_pack.py
└── static/
    └── login_admin_minimal.html
```

---

## 建議導入策略：嵌入既有 code 優先

這包可以整包複製到目標專案，作為 Codex 導入時的參考素材；但對於已經有既有架構、router、設定系統或啟動流程的專案，**建議不要長期用外掛子目錄 + `PYTHONPATH` 的方式運作**。較穩定的做法是：

1. 先把 `portable_auth_pack/` 整包放進目標專案，讓 Codex 有完整上下文與範例。
2. 再由 Codex 依照目標專案慣例，把 `fastapi_auth_pack/` 內的 auth store、models、dependencies、router 嵌入到既有 app package，例如 `app/auth/`、`api/auth/` 或既有 `users/` 模組。
3. 掛 router 時沿用目標專案原本的 `app.include_router(...)`、prefix、dependency、設定載入與測試風格。
4. 前端只抽取 `static/login_admin_minimal.html` 裡的登入、token header、帳號審核邏輯，不必照搬整頁。

這樣比較不會破壞既有 import path、部署設定、測試設定或 API prefix，相容性也比較高。

## 快速導入到另一個 FastAPI 專案

### 1. 複製素材包

把這個目錄整包複製到目標專案，作為導入素材，例如：

```text
目標專案/
└── portable_auth_pack/
```

如果只是快速 PoC，可以暫時讓 Python 找得到套件：

```bash
export PYTHONPATH="$PWD/portable_auth_pack:$PYTHONPATH"
```

正式導入或既有專案整合時，建議把 `portable_auth_pack/fastapi_auth_pack` 內容依目標專案慣例嵌入到既有 package，再調整 import。

### 2. 掛載 router

在目標專案的 FastAPI app 加入：

```python
from fastapi_auth_pack import router as auth_router

app.include_router(auth_router)
```

完成後會提供：

| Method | Path | 說明 |
|---|---|---|
| `POST` | `/v1/auth/register` | 建立 pending 帳號 |
| `POST` | `/v1/auth/login` | 登入並取得 Bearer token |
| `GET` | `/v1/auth/me` | 查詢目前登入者 |
| `POST` | `/v1/auth/logout` | 登出並將目前 token 加入 denylist |
| `POST` | `/v1/auth/change-password` | 已登入使用者變更自己的密碼；既有 token 失效 |
| `POST` | `/v1/auth/forgot-password` | 忘記密碼申請；不公開回傳 reset token |
| `POST` | `/v1/auth/reset-password` | 使用一次性 reset token 重設密碼；既有 token 失效 |
| `GET` | `/v1/auth/users` | superuser 列出帳號 |
| `POST` | `/v1/auth/users/{username}/approve` | superuser 核准帳號 |
| `POST` | `/v1/auth/users/{username}/reject` | superuser 拒絕帳號 |
| `POST` | `/v1/auth/users/{username}/password-reset-token` | superuser 產生一次性 reset token，供核身後安全交付 |
| `POST` | `/v1/auth/users/{username}/reset-password` | superuser 直接重設使用者密碼；該帳號既有 token 失效 |
| `DELETE` | `/v1/auth/users/{username}` | superuser 刪除帳號 |
| `GET` | `/v1/auth/login-audit` | superuser 查詢登入稽核紀錄 |

### 3. 保護你的既有 API

一般登入即可使用：

```python
from fastapi import Depends
from fastapi_auth_pack import AuthUser, current_user

@app.get("/v1/private")
def private_api(user: AuthUser = Depends(current_user)):
    return {"hello": user.username}
```

只有 superuser 可使用：

```python
from fastapi import Depends
from fastapi_auth_pack import AuthUser, require_superuser

@app.post("/v1/admin/rebuild")
def rebuild(user: AuthUser = Depends(require_superuser)):
    return {"started_by": user.username}
```

---

## 環境變數

建議參考 `examples/env.example`。這版使用較正式、通用的 `AUTH_*` 命名，方便嵌入其他正式專案。

| 環境變數 | 必要 | 預設 | 說明 |
|---|---:|---|---|
| `AUTH_SECRET` | 正式環境必要 | development fallback | token 簽章密鑰；正式環境請用長隨機字串 |
| `AUTH_USERS_FILE` | 否 | `./.auth_users.json` | 使用者資料 JSON 檔位置 |
| `AUTH_BOOTSTRAP_SUPERUSERS_FILE` | 否 | `./config/auth/bootstrap_superusers.json` | 初始 superuser JSON 檔位置 |
| `AUTH_BOOTSTRAP_SUPERUSERS` | 否 | 空 | 直接用 JSON 字串設定 superusers |
| `AUTH_BOOTSTRAP_SUPERUSER_USERNAME` | 否 | 空 | 單一初始 superuser 帳號 |
| `AUTH_BOOTSTRAP_SUPERUSER_PASSWORD` | 否 | 空 | 單一初始 superuser 密碼 |
| `AUTH_TOKEN_TTL_SECONDS` | 否 | `43200` | token 有效秒數，預設 12 小時 |
| `AUTH_PROJECT_ROOT` | 否 | 目前工作目錄 | 控制預設 config/user file 的根目錄 |

產生正式環境 secret 範例：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## 測試用初始 superuser

`examples/bootstrap_superusers.test.json` 內含一組 **測試／安全環境限定** 的通用初始 superuser：

```text
username: codex_admin
password: CodexTestAdmin!2026
```

使用方式：

```bash
mkdir -p config/auth runtime
cp portable_auth_pack/examples/bootstrap_superusers.test.json config/auth/bootstrap_superusers.json
export AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export AUTH_USERS_FILE="$PWD/runtime/.auth_users.json"
export AUTH_BOOTSTRAP_SUPERUSERS_FILE="$PWD/config/auth/bootstrap_superusers.json"
```

> 重要：這組帳密是公開測試帳密，請勿用於公開網路或正式環境。正式環境請改成私有帳密，或改用環境變數 / secret manager 注入。

---

## 最小 demo

在目標專案根目錄執行：

```bash
export PYTHONPATH="$PWD/portable_auth_pack:$PYTHONPATH"
export AUTH_SECRET="dev-secret-for-local-only"
export AUTH_BOOTSTRAP_SUPERUSERS_FILE="$PWD/portable_auth_pack/examples/bootstrap_superusers.test.json"
uvicorn portable_auth_pack.examples.main:app --reload
```

登入：

```bash
curl -s -X POST http://127.0.0.1:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"codex_admin","password":"CodexTestAdmin!2026"}'
```

---

## 前端範例

`static/login_admin_minimal.html` 是一個最小可改造頁面，包含：

- 登入 / logout token 失效
- 註冊 pending 帳號
- 查詢 `/v1/auth/me`
- 使用者變更密碼、忘記密碼 reset token 補救
- superuser 帳號審核、重設密碼與登入稽核查詢
- 將 Bearer token 存在 `localStorage.auth_token`

你可以把它改成目標專案的登入頁，或只抽取其中的 JavaScript helper。

---

## 安全注意事項

- 正式環境必須設定 `AUTH_SECRET`，且要保持穩定；換 secret 會讓既有 token 失效。
- `*.json` user store 請放在非公開路徑，不要放在靜態檔目錄。
- 請把 `runtime/`、`.auth_users.json`、正式 `bootstrap_superusers.json` 加到 `.gitignore`。
- 這個 pack 使用本機 JSON 檔，適合 PoC / 小型內部服務；高併發或多副本部署建議改接資料庫或集中式 session/token 系統。
- 若前端使用 localStorage 存 token，請特別注意 XSS 防護。
- `/v1/auth/forgot-password` 只受理申請，不公開回傳 reset token；請由 superuser 在 `/v1/auth/users/{username}/password-reset-token` 產生 token，核身後用 email、簡訊或 help desk out-of-band 安全交付。
