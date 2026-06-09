from __future__ import annotations

import importlib
import json
import secrets


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
