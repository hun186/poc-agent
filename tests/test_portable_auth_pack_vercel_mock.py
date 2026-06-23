from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_portable_env_example_includes_preview_secret_placeholder():
    env_example = Path("portable_auth_pack/examples/env.example").read_text(encoding="utf-8")

    assert "AUTH_VERCEL_MOCK_MODE=auto" in env_example
    assert "AUTH_VERCEL_PREVIEW_LOGIN_SECRET=replace-with-random-portable-preview-secret" in env_example


def test_portable_auth_pack_vercel_mock_preview_login(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "VERCEL": "1",
        "AUTH_ENV": "dev",
        "AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "AUTH_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "from portable_auth_pack.fastapi_auth_pack.router import router\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
        "client = TestClient(app)\n"
        "enabled = client.get('/v1/auth/vercel-preview-login-enabled')\n"
        "assert enabled.status_code == 200, enabled.text\n"
        "assert enabled.json()['enabled'] is True, enabled.text\n"
        "assert enabled.json()['username'] == 'portable_mock_reader'\n"
        "assert enabled.json()['secret_required'] is False, enabled.text\n"
        "login = client.post('/v1/auth/vercel-preview-login')\n"
        "assert login.status_code == 200, login.text\n"
        "payload = login.json()\n"
        "assert payload['user']['username'] == 'portable_mock_reader'\n"
        "assert payload['user']['role'] == 'data_reader'\n"
        "assert payload['user']['mock_preview'] is True\n"
        "me = client.get('/v1/auth/me', headers={'Authorization': 'Bearer ' + payload['access_token']})\n"
        "assert me.status_code == 200, me.text\n"
        "print(payload['user'])\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_portable_auth_pack_vercel_mock_preview_login_requires_secret(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "VERCEL": "1",
        "VERCEL_ENV": "preview",
        "AUTH_ENV": "dev",
        "AUTH_VERCEL_PREVIEW_LOGIN_SECRET": "portable-secret",
        "AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "AUTH_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "from portable_auth_pack.fastapi_auth_pack.router import router\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
        "client = TestClient(app)\n"
        "enabled = client.get('/v1/auth/vercel-preview-login-enabled')\n"
        "assert enabled.status_code == 200, enabled.text\n"
        "assert enabled.json()['enabled'] is True, enabled.text\n"
        "assert enabled.json()['secret_required'] is True, enabled.text\n"
        "missing = client.post('/v1/auth/vercel-preview-login')\n"
        "assert missing.status_code == 403, missing.text\n"
        "login = client.post('/v1/auth/vercel-preview-login', headers={'X-SRA-Preview-Login-Secret': 'portable-secret'})\n"
        "assert login.status_code == 200, login.text\n"
        "assert login.json()['user']['mock_preview'] is True\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_portable_auth_pack_vercel_mock_preview_login_auto_disabled_in_production(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "VERCEL": "1",
        "VERCEL_ENV": "production",
        "APP_ENV": "production",
        "AUTH_SECRET": "x" * 48,
        "AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "AUTH_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "from portable_auth_pack.fastapi_auth_pack.router import router\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
        "client = TestClient(app)\n"
        "enabled = client.get('/v1/auth/vercel-preview-login-enabled')\n"
        "assert enabled.status_code == 200, enabled.text\n"
        "assert enabled.json()['enabled'] is False, enabled.text\n"
        "login = client.post('/v1/auth/vercel-preview-login')\n"
        "assert login.status_code == 404, login.text\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_portable_auth_pack_vercel_mock_preview_login_can_be_disabled(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "AUTH_VERCEL_MOCK_MODE": "never",
        "AUTH_USERS_FILE": str(tmp_path / "users.json"),
        "AUTH_LOGIN_AUDIT_FILE": str(tmp_path / "login_audit.json"),
    }
    code = (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "from portable_auth_pack.fastapi_auth_pack.router import router\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
        "client = TestClient(app)\n"
        "enabled = client.get('/v1/auth/vercel-preview-login-enabled')\n"
        "assert enabled.status_code == 200, enabled.text\n"
        "assert enabled.json()['enabled'] is False, enabled.text\n"
        "login = client.post('/v1/auth/vercel-preview-login')\n"
        "assert login.status_code == 404, login.text\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
