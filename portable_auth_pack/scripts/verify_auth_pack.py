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

        from examples.main import app

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
        pending_login_res = client.post(
            "/v1/auth/login",
            json={"username": "alice", "password": "AlicePass!2026"},
        )
        assert pending_login_res.status_code == 403, pending_login_res.text

        approve_res = client.post(
            "/v1/auth/users/alice/approve",
            json={"role": "user"},
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
        denied_res = client.get("/v1/admin/ping", headers=user_headers)
        assert denied_res.status_code == 403, denied_res.text

        audit_res = client.get("/v1/auth/login-audit", headers=headers)
        assert audit_res.status_code == 200, audit_res.text
        assert any(event["username"] == "alice" for event in audit_res.json()["events"])

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

    print("portable_auth_pack verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
