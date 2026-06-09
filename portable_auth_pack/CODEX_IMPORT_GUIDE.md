# Codex 導入指南：FastAPI Auth Pack

這份文件是給未來 Codex / agent 在其他專案導入帳號管理時使用的操作指南。

## 任務目標

把 `portable_auth_pack/fastapi_auth_pack` 作為素材嵌入目標 FastAPI 專案，依照目標專案既有架構整合 router、設定、測試與前端登入流程，並用 `current_user` / `require_superuser` 保護目標專案既有 endpoint。

## 建議導入步驟

1. **確認目標專案類型**
   - 若是 FastAPI：直接導入本 pack。
   - 若不是 FastAPI：只參考 `auth_store.py` 的使用者儲存、密碼雜湊、token 邏輯，router/dependency 需改寫。

2. **放置程式碼：嵌入既有 code 優先**
   - 先把 `portable_auth_pack/` 整包放到目標專案，作為 Codex 可參考的完整素材。
   - 正式整合時，不要優先把它當外掛套件長期掛在 `PYTHONPATH`；應把 `fastapi_auth_pack/` 的內容融入目標專案既有 app package，例如 `app/auth/`、`api/auth/`、`users/` 或既有帳號模組。
   - 依目標專案慣例調整 import path、router prefix、settings loader、測試目錄與前端 token key。
   - 若目標專案已經有 settings/auth/user 模組，優先改造既有模組或把本 pack 拆成小檔案嵌入，不要平行建立另一套衝突的架構。

3. **掛載 router**
   - 在 FastAPI app 建立處加入：

   ```python
   from fastapi_auth_pack import router as auth_router
   app.include_router(auth_router)
   ```

4. **設定環境變數**
   - 必設正式 secret：`AUTH_SECRET`。
   - 建議設定：`AUTH_USERS_FILE` 與 `AUTH_BOOTSTRAP_SUPERUSERS_FILE`。
   - 若是測試環境，可複製 `examples/bootstrap_superusers.test.json` 到目標專案 `config/auth/bootstrap_superusers.json`。

5. **保護 endpoint**
   - 一般登入：`Depends(current_user)`。
   - 管理者：`Depends(require_superuser)`。

6. **前端導入**
   - 參考 `static/login_admin_minimal.html`。
   - 將 token 存放 key、API base path 與 UI 文案改成目標專案慣例。

7. **測試導入**
   - 用 `scripts/verify_auth_pack.py` 在此 repo 檢查 pack 本身。
   - 在目標專案新增至少以下測試：
     - bootstrap superuser 可登入。
     - 未帶 token 呼叫 protected API 回 401。
     - pending user 登入回 403。
     - superuser 可 approve user。
     - approved user 可呼叫 protected API。
     - logout 後同一 token 呼叫 protected API 回 401。
     - change/reset password 後舊 token 回 401，且新密碼可登入。
     - forgot-password 不公開回傳 reset token；superuser 產生 reset token 後，使用者可用 token 重設密碼，且登入稽核可被 superuser 查詢。

## Codex 修改注意事項

- 不要把正式密碼、token、secret commit 到 repo。
- 測試用 `codex_admin / CodexTestAdmin!2026` 只能用於受控測試環境。
- 若目標專案已有 authentication middleware、settings、user model 或 DB session，優先與既有架構整合，避免平行建立另一套會衝突的登入流程。
- 若目標專案部署為多 worker / 多副本，本機 JSON user store 可能不適合；應改寫 `AuthStore` 存取層到資料庫。
- 若要改 endpoint prefix，例如 `/api/auth/*`，依目標專案既有 router 掛載方式調整；避免造成 `/v1/v1/auth` 這類重複 prefix。

## 常見改造點

- `auth_store.py`
  - 改 `_auth_file()`：接目標專案設定系統。
  - 改 `_token_secret()`：接 secret manager。
  - 改 `AuthStore`：改為 SQLAlchemy / Redis / 既有 user table。

- `dependencies.py`
  - 在 `current_user()` 加入更多使用者欄位。
  - 在 `require_superuser()` 改成 role list 或 permission-based access control。

- `router.py`
  - 改 response schema。
  - 維持 public forgot-password 不回傳 token；依目標專案調整 superuser 產生 reset token 後的交付方式。
  - 依目標專案調整 login audit 儲存位置、保留期限與查詢權限。
  - 若已有 session/JWT 系統，將 logout denylist 與 token_version 失效機制接到既有儲存層。

- `static/login_admin_minimal.html`
  - 抽出 `api()` helper 與 login/register/admin user management 函式。
