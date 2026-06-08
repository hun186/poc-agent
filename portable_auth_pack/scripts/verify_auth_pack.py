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
        denied_res = client.get("/v1/admin/ping", headers={"Authorization": f"Bearer {user_token}"})
        assert denied_res.status_code == 403, denied_res.text

    print("portable_auth_pack verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
