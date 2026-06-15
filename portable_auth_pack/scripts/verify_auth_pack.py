from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path


def main() -> int:
    pack_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(pack_root))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bootstrap_file = root / "bootstrap_superusers.json"
        users_file = root / "users.json"
        bootstrap_file.write_text(
            json.dumps(
                {
                    "superusers": [
                        {"username": "codex_admin", "password": "CodexTestAdmin!2026"}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.environ["AUTH_SECRET"] = secrets.token_urlsafe(48)
        os.environ["AUTH_USERS_FILE"] = str(users_file)
        os.environ["AUTH_BOOTSTRAP_SUPERUSERS_FILE"] = str(bootstrap_file)

        from fastapi.testclient import TestClient

        import fastapi_auth_pack.auth_store as auth_store_module
        from examples.main import app

        original_verify_password = auth_store_module._verify_password
        verify_calls: list[str] = []

        def fake_verify_password(password: str, password_hash: str) -> bool:
            verify_calls.append(password_hash)
            return False

        auth_store_module._verify_password = fake_verify_password
        try:
            assert auth_store_module.AUTH_STORE.authenticate("missing-user", "anything") is None
            assert verify_calls == [auth_store_module.DUMMY_PASSWORD_HASH]
        finally:
            auth_store_module._verify_password = original_verify_password

        original_auth_secret = os.environ.pop("AUTH_SECRET", None)
        os.environ["AUTH_ENV"] = "production"
        try:
            try:
                auth_store_module._token_secret()
                raise AssertionError("production AUTH_SECRET requirement was not enforced")
            except RuntimeError as exc:
                assert "production" in str(exc)
            os.environ["AUTH_SECRET"] = "short"
            try:
                auth_store_module._token_secret()
                raise AssertionError("production AUTH_SECRET length requirement was not enforced")
            except RuntimeError as exc:
                assert "32 bytes" in str(exc)
        finally:
            if original_auth_secret is not None:
                os.environ["AUTH_SECRET"] = original_auth_secret
            else:
                os.environ.pop("AUTH_SECRET", None)
            os.environ.pop("AUTH_ENV", None)

        client = TestClient(app)
        login_res = client.post(
            "/v1/auth/login",
            json={"username": "codex_admin", "password": "CodexTestAdmin!2026"},
        )
        assert login_res.status_code == 200, login_res.text
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_res = client.get("/v1/auth/me", headers=headers)
        assert me_res.status_code == 200, me_res.text
        assert me_res.json()["user"]["username"] == "codex_admin"

        private_res = client.get("/v1/private/ping", headers=headers)
        assert private_res.status_code == 200, private_res.text

        register_res = client.post(
            "/v1/auth/register",
            json={"username": "alice", "password": "AlicePass!2026"},
        )
        assert register_res.status_code == 200, register_res.text
        duplicate_register_res = client.post(
            "/v1/auth/register",
            json={"username": "alice", "password": "AlicePass!2026"},
        )
        assert duplicate_register_res.status_code == 200, duplicate_register_res.text
        assert duplicate_register_res.json() == register_res.json()
        register_audit = auth_store_module.AUTH_STORE.list_login_audit(10)
        assert any(
            event.get("username") == "alice"
            and event.get("reason") == "register_duplicate_username"
            and event.get("client_host") == "testclient"
            for event in register_audit
        )
        pending_login_res = client.post(
            "/v1/auth/login",
            json={"username": "alice", "password": "AlicePass!2026"},
        )
        assert pending_login_res.status_code == 401, pending_login_res.text
        assert pending_login_res.json()["detail"] == "帳號或密碼錯誤，或帳號尚未啟用。"

        approve_res = client.post(
            "/v1/auth/users/alice/approve",
            json={"role": "data_editor"},
            headers=headers,
        )
        assert approve_res.status_code == 200, approve_res.text

        user_login_res = client.post(
            "/v1/auth/login",
            json={"username": "alice", "password": "AlicePass!2026"},
        )
        assert user_login_res.status_code == 200, user_login_res.text
        user_token = user_login_res.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}
        edit_res = client.post("/v1/documents/ping", headers=user_headers)
        assert edit_res.status_code == 200, edit_res.text
        db_denied_res = client.post("/v1/database/ping", headers=user_headers)
        assert db_denied_res.status_code == 403, db_denied_res.text
        denied_res = client.get("/v1/admin/ping", headers=user_headers)
        assert denied_res.status_code == 403, denied_res.text

        audit_res = client.get("/v1/auth/login-audit", headers=headers)
        assert audit_res.status_code == 200, audit_res.text
        assert audit_res.json()["is_restricted_to_self"] is False
        assert any(event["username"] == "alice" for event in audit_res.json()["events"])

        user_audit_res = client.get("/v1/auth/login-audit", headers=user_headers)
        assert user_audit_res.status_code == 200, user_audit_res.text
        assert user_audit_res.json()["is_restricted_to_self"] is True
        assert user_audit_res.json()["events"]
        assert all(event["username"] == "alice" for event in user_audit_res.json()["events"])

        changed_res = client.post(
            "/v1/auth/change-password",
            json={"current_password": "AlicePass!2026", "new_password": "AlicePass!2027"},
            headers=user_headers,
        )
        assert changed_res.status_code == 200, changed_res.text
        invalidated_res = client.get("/v1/private/ping", headers=user_headers)
        assert invalidated_res.status_code == 401, invalidated_res.text

        relogin_res = client.post(
            "/v1/auth/login",
            json={"username": "alice", "password": "AlicePass!2027"},
        )
        assert relogin_res.status_code == 200, relogin_res.text
        user_headers = {"Authorization": f"Bearer {relogin_res.json()['access_token']}"}
        logout_res = client.post("/v1/auth/logout", headers=user_headers)
        assert logout_res.status_code == 200, logout_res.text
        logged_out_res = client.get("/v1/private/ping", headers=user_headers)
        assert logged_out_res.status_code == 401, logged_out_res.text

        reset_res = client.post(
            "/v1/auth/users/alice/reset-password",
            json={"new_password": "AlicePass!2028"},
            headers=headers,
        )
        assert reset_res.status_code == 200, reset_res.text
        reset_login_res = client.post(
            "/v1/auth/login",
            json={"username": "alice", "password": "AlicePass!2028"},
        )
        assert reset_login_res.status_code == 200, reset_login_res.text

        forgot_res = client.post("/v1/auth/forgot-password", json={"username": "alice"})
        assert forgot_res.status_code == 200, forgot_res.text
        assert "reset_token" not in forgot_res.json(), forgot_res.text

        token_res = client.post("/v1/auth/users/alice/password-reset-token", headers=headers)
        assert token_res.status_code == 200, token_res.text
        recovery_token = token_res.json().get("reset_token")
        assert recovery_token, token_res.text
        recover_res = client.post(
            "/v1/auth/reset-password",
            json={"username": "alice", "reset_token": recovery_token, "new_password": "AlicePass!2029"},
        )
        assert recover_res.status_code == 200, recover_res.text

        for _ in range(auth_store_module.AUTH_THROTTLE_FAILURE_LIMIT - 1):
            bad_login_res = client.post(
                "/v1/auth/login",
                json={"username": "codex_admin", "password": "wrong-password"},
            )
            assert bad_login_res.status_code == 401, bad_login_res.text
        throttled_login_res = client.post(
            "/v1/auth/login",
            json={"username": "codex_admin", "password": "wrong-password"},
        )
        assert throttled_login_res.status_code == 429, throttled_login_res.text
        assert int(throttled_login_res.headers["retry-after"]) > 0
        failed_login_audit = auth_store_module.AUTH_STORE.list_login_audit(20)
        assert any(
            event.get("username") == "codex_admin"
            and event.get("success") is False
            and event.get("reason") in {"invalid_credentials", "rate_limited"}
            and event.get("client_host") == "testclient"
            for event in failed_login_audit
        )

        auth_store_module.AUTH_STORE.clear_auth_failures("register", None, "testclient")
        for idx in range(auth_store_module.AUTH_THROTTLE_FAILURE_LIMIT):
            register_attempt_res = client.post(
                "/v1/auth/register",
                json={"username": f"bulk-{idx}", "password": "BulkPass!2026"},
            )
            assert register_attempt_res.status_code == 200, register_attempt_res.text
        throttled_register_res = client.post(
            "/v1/auth/register",
            json={"username": "bulk-blocked", "password": "BulkPass!2026"},
        )
        assert throttled_register_res.status_code == 429, throttled_register_res.text
        assert int(throttled_register_res.headers["retry-after"]) > 0

        for _ in range(auth_store_module.AUTH_THROTTLE_FAILURE_LIMIT - 1):
            bad_reset_res = client.post(
                "/v1/auth/reset-password",
                json={"username": "alice", "reset_token": "bad-token", "new_password": "AlicePass!2030"},
            )
            assert bad_reset_res.status_code == 400, bad_reset_res.text
        throttled_reset_res = client.post(
            "/v1/auth/reset-password",
            json={"username": "alice", "reset_token": "bad-token", "new_password": "AlicePass!2030"},
        )
        assert throttled_reset_res.status_code == 429, throttled_reset_res.text
        assert int(throttled_reset_res.headers["retry-after"]) > 0

    print("portable_auth_pack verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
