from __future__ import annotations

import importlib
import json
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_auth_store(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    bootstrap_file = tmp_path / "bootstrap.json"
    bootstrap_file.write_text(
        json.dumps({"superusers": [{"username": "admin", "password": "AdminPass!2026"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SRA_AUTH_USERS_FILE", str(users_file))
    monkeypatch.setenv("SRA_BOOTSTRAP_SUPERUSERS_FILE", str(bootstrap_file))
    monkeypatch.setenv("SRA_AUTH_SECRET", secrets.token_urlsafe(48))
    import api.services.auth_store as auth_store

    return importlib.reload(auth_store)


def _load_editor_client(monkeypatch, tmp_path) -> tuple[TestClient, object]:
    auth_store = _load_auth_store(monkeypatch, tmp_path)
    monkeypatch.setenv("SRA_EDITOR_AUDIT_LOG", str(tmp_path / "editor_audit.jsonl"))
    import api.routers.editor as editor

    editor = importlib.reload(editor)
    app = FastAPI()
    app.include_router(editor.router)
    return TestClient(app), auth_store


def test_change_password_invalidates_existing_tokens(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)
    admin = auth_store.AUTH_STORE.authenticate("admin", "AdminPass!2026")
    assert admin is not None
    token = auth_store.create_token(admin)
    payload = auth_store.parse_token(token)
    assert payload is not None
    assert auth_store.AUTH_STORE.is_token_current("admin", int(payload["ver"]))

    auth_store.AUTH_STORE.change_password("admin", "AdminPass!2026", "AdminPass!2027")

    assert not auth_store.AUTH_STORE.is_token_current("admin", int(payload["ver"]))
    assert auth_store.AUTH_STORE.authenticate("admin", "AdminPass!2027") is not None


def test_logout_denylist_and_forgot_password_recovery(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)
    admin = auth_store.AUTH_STORE.authenticate("admin", "AdminPass!2026")
    assert admin is not None
    token = auth_store.create_token(admin)
    payload = auth_store.parse_token(token)
    assert payload is not None

    auth_store.AUTH_STORE.deny_token(payload)
    assert auth_store.AUTH_STORE.is_token_denied(str(payload["jti"]))

    recovery_token = auth_store.AUTH_STORE.request_password_reset("admin")
    assert recovery_token
    auth_store.AUTH_STORE.recover_password("admin", recovery_token, "AdminPass!2028")
    assert auth_store.AUTH_STORE.authenticate("admin", "AdminPass!2028") is not None


def test_login_audit_is_recorded_and_listed(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)

    auth_store.AUTH_STORE.record_login_audit("admin", success=True, reason="ok", role="superuser", status_value="active")

    events = auth_store.AUTH_STORE.list_login_audit()
    assert events[-1]["username"] == "admin"
    assert events[-1]["success"] is True


def test_unknown_user_password_check_uses_dummy_hash(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_verify_password(password: str, password_hash: str) -> bool:
        calls.append(password_hash)
        return False

    monkeypatch.setattr(auth_store, "_verify_password", fake_verify_password)

    assert auth_store.AUTH_STORE.authenticate("missing-user", "anything") is None
    assert calls == [auth_store.DUMMY_PASSWORD_HASH]


def test_auth_failure_throttle_blocks_and_clears(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)

    for _ in range(auth_store.AUTH_THROTTLE_FAILURE_LIMIT - 1):
        assert auth_store.AUTH_STORE.record_auth_failure("login", "admin", "127.0.0.1") == 0

    retry_after = auth_store.AUTH_STORE.record_auth_failure("login", "admin", "127.0.0.1")
    assert retry_after == auth_store.AUTH_THROTTLE_BLOCK_SECONDS
    assert auth_store.AUTH_STORE.throttle_retry_after("login", "admin", "127.0.0.1") > 0

    auth_store.AUTH_STORE.clear_auth_failures("login", "admin", "127.0.0.1")
    assert auth_store.AUTH_STORE.throttle_retry_after("login", "admin", "127.0.0.1") == 0


def test_production_requires_explicit_strong_token_secret(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    bootstrap_file = tmp_path / "bootstrap.json"
    bootstrap_file.write_text('{"superusers": []}', encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SRA_AUTH_USERS_FILE", str(users_file))
    monkeypatch.setenv("SRA_BOOTSTRAP_SUPERUSERS_FILE", str(bootstrap_file))
    monkeypatch.delenv("SRA_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    import api.services.auth_store as auth_store

    auth_store = importlib.reload(auth_store)
    with pytest.raises(RuntimeError, match="必須在 production 環境設定"):
        auth_store._token_secret()

    monkeypatch.setenv("SRA_AUTH_SECRET", "short")
    with pytest.raises(RuntimeError, match="至少需要 32 bytes"):
        auth_store._token_secret()


def test_login_endpoint_rate_limits_repeated_failures(monkeypatch, tmp_path):
    client, auth_store = _load_editor_client(monkeypatch, tmp_path)

    for _ in range(auth_store.AUTH_THROTTLE_FAILURE_LIMIT - 1):
        response = client.post("/v1/auth/login", json={"username": "admin", "password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["detail"] == "帳號或密碼錯誤，或帳號尚未啟用。"

    response = client.post("/v1/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_inactive_login_uses_generic_failure_response(monkeypatch, tmp_path):
    client, _ = _load_editor_client(monkeypatch, tmp_path)
    register_response = client.post("/v1/auth/register", json={"username": "pending", "password": "PendingPass!2026"})
    assert register_response.status_code == 200

    response = client.post("/v1/auth/login", json={"username": "pending", "password": "PendingPass!2026"})

    assert response.status_code == 401
    assert response.json()["detail"] == "帳號或密碼錯誤，或帳號尚未啟用。"
