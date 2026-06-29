from __future__ import annotations

import importlib
import json
import logging
import secrets

import pytest
from fastapi import Depends, FastAPI
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



def test_login_failure_writes_audit_and_warning_log(monkeypatch, tmp_path, caplog):
    client, auth_store = _load_editor_client(monkeypatch, tmp_path)

    with caplog.at_level(logging.WARNING, logger="api.routers.editor_auth_logging"):
        response = client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
            headers={"user-agent": "pytest-agent"},
        )

    assert response.status_code == 401
    login_audit = auth_store.AUTH_STORE.list_login_audit()
    assert login_audit[-1]["username"] == "admin"
    assert login_audit[-1]["success"] is False
    assert login_audit[-1]["reason"] == "invalid_credentials"
    assert login_audit[-1]["client_host"] == "testclient"
    records = [json.loads(line) for line in (tmp_path / "editor_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[-1]["action"] == "auth.login"
    assert records[-1]["success"] is False
    assert records[-1]["reason"] == "invalid_credentials"
    assert "auth.login.failed username=admin reason=invalid_credentials client_host=testclient" in caplog.text
    assert "wrong-password" not in caplog.text

def test_inactive_login_uses_generic_failure_response(monkeypatch, tmp_path):
    client, _ = _load_editor_client(monkeypatch, tmp_path)
    register_response = client.post("/v1/auth/register", json={"username": "pending", "password": "PendingPass!2026"})
    assert register_response.status_code == 200

    response = client.post("/v1/auth/login", json={"username": "pending", "password": "PendingPass!2026"})

    assert response.status_code == 401
    assert response.json()["detail"] == "帳號或密碼錯誤，或帳號尚未啟用。"


def test_role_hierarchy_approval_and_role_options(monkeypatch, tmp_path):
    client, auth_store = _load_editor_client(monkeypatch, tmp_path)

    auth_store.AUTH_STORE.register("reader", "ReaderPass!2026")
    auth_store.AUTH_STORE.approve_user("reader", "data_reader", approved_by="admin")
    auth_store.AUTH_STORE.register("editor", "EditorPass!2026")
    approved_editor = auth_store.AUTH_STORE.approve_user("editor", "data_editor", approved_by="admin")
    auth_store.AUTH_STORE.register("operator", "OperatorPass!2026")
    approved_operator = auth_store.AUTH_STORE.approve_user("operator", "db_operator", approved_by="admin")

    assert approved_editor["role"] == "data_editor"
    assert approved_operator["role"] == "db_operator"
    assert auth_store.has_role_at_least("db_operator", "data_editor")
    assert not auth_store.has_role_at_least("data_reader", "data_editor")

    login = client.post("/v1/auth/login", json={"username": "admin", "password": "AdminPass!2026"})
    assert login.status_code == 200
    response = client.get("/v1/auth/users", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert response.status_code == 200
    role_values = [item["value"] for item in response.json()["role_options"]]
    assert role_values == ["superuser", "db_operator", "data_editor", "data_reader"]


def test_legacy_user_role_maps_to_data_editor(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)

    registered = auth_store.AUTH_STORE.register("legacy", "LegacyPass!2026")
    assert registered["role"] == "data_reader"

    approved = auth_store.AUTH_STORE.approve_user("legacy", "user", approved_by="admin")

    assert approved["role"] == "data_editor"


def test_role_dependencies_enforce_reader_editor_operator_boundaries(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)
    import api.routers.editor_dependencies as deps

    deps = importlib.reload(deps)
    app = FastAPI()

    @app.post("/edit")
    def edit(user=Depends(deps.require_data_editor)):
        return {"role": user.role}

    @app.post("/operate-db")
    def operate_db(user=Depends(deps.require_db_operator)):
        return {"role": user.role}

    auth_store.AUTH_STORE.register("reader2", "ReaderPass!2026")
    auth_store.AUTH_STORE.approve_user("reader2", "data_reader", approved_by="admin")
    auth_store.AUTH_STORE.register("editor2", "EditorPass!2026")
    auth_store.AUTH_STORE.approve_user("editor2", "data_editor", approved_by="admin")
    auth_store.AUTH_STORE.register("operator2", "OperatorPass!2026")
    auth_store.AUTH_STORE.approve_user("operator2", "db_operator", approved_by="admin")

    def token(username: str, password: str) -> str:
        user = auth_store.AUTH_STORE.authenticate(username, password)
        assert user is not None
        return auth_store.create_token(user)

    client = TestClient(app)
    reader_headers = {"Authorization": f"Bearer {token('reader2', 'ReaderPass!2026')}"}
    editor_headers = {"Authorization": f"Bearer {token('editor2', 'EditorPass!2026')}"}
    operator_headers = {"Authorization": f"Bearer {token('operator2', 'OperatorPass!2026')}"}

    assert client.post("/edit", headers=reader_headers).status_code == 403
    assert client.post("/edit", headers=editor_headers).status_code == 200
    assert client.post("/operate-db", headers=editor_headers).status_code == 403
    assert client.post("/operate-db", headers=operator_headers).status_code == 200

def test_register_duplicate_uses_generic_response_and_audits_ip(monkeypatch, tmp_path):
    client, _ = _load_editor_client(monkeypatch, tmp_path)

    first = client.post("/v1/auth/register", json={"username": "enum-target", "password": "EnumPass!2026"})
    duplicate = client.post("/v1/auth/register", json={"username": "enum-target", "password": "EnumPass!2026"})

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == duplicate.json() == {"message": "若資料符合申請條件，帳號申請已送出；請等待系統管理員審核。"}

    records = [json.loads(line) for line in (tmp_path / "editor_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    register_events = [record for record in records if record.get("action") == "auth.user_registered"]
    assert register_events[-2]["success"] is True
    assert register_events[-2]["client_host"] == "testclient"
    assert register_events[-1]["success"] is False
    assert register_events[-1]["reason"] == "duplicate_username"
    assert register_events[-1]["client_host"] == "testclient"


def test_register_endpoint_rate_limits_by_ip(monkeypatch, tmp_path):
    client, auth_store = _load_editor_client(monkeypatch, tmp_path)

    for idx in range(auth_store.AUTH_THROTTLE_FAILURE_LIMIT):
        response = client.post(
            "/v1/auth/register",
            json={"username": f"bulk-{idx}", "password": "BulkPass!2026"},
        )
        assert response.status_code == 200

    throttled = client.post("/v1/auth/register", json={"username": "bulk-blocked", "password": "BulkPass!2026"})
    assert throttled.status_code == 429
    assert int(throttled.headers["retry-after"]) > 0


def test_superuser_can_clear_login_throttle(monkeypatch, tmp_path):
    client, auth_store = _load_editor_client(monkeypatch, tmp_path)
    auth_store.AUTH_STORE.register("locked", "LockedPass!2026")
    auth_store.AUTH_STORE.approve_user("locked", "data_reader", approved_by="admin")

    for _ in range(auth_store.AUTH_THROTTLE_FAILURE_LIMIT):
        response = client.post("/v1/auth/login", json={"username": "locked", "password": "wrong"})
    assert response.status_code == 429
    assert "剩餘約" in response.json()["detail"]

    admin_login = client.post("/v1/auth/login", json={"username": "admin", "password": "AdminPass!2026"})
    assert admin_login.status_code == 200
    token = admin_login.json()["access_token"]

    unlocked = client.post(
        "/v1/auth/users/locked/unlock-login",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unlocked.status_code == 200
    assert unlocked.json()["cleared"] >= 1
    assert auth_store.AUTH_STORE.throttle_retry_after("login", "locked", "testclient") == 0
    assert client.post("/v1/auth/login", json={"username": "locked", "password": "LockedPass!2026"}).status_code == 200

def test_login_audit_uses_separate_file_and_keeps_users_file_small(monkeypatch, tmp_path):
    audit_file = tmp_path / "login_audit.json"
    monkeypatch.setenv("SRA_LOGIN_AUDIT_FILE", str(audit_file))
    auth_store = _load_auth_store(monkeypatch, tmp_path)

    auth_store.AUTH_STORE.record_login_audit("admin", success=True, reason="ok", role="superuser", status_value="active")

    users_data = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))
    audit_manifest = json.loads(audit_file.read_text(encoding="utf-8"))
    audit_shards = sorted(audit_file.with_suffix(audit_file.suffix + ".d").glob("login_audit-*.json"))
    assert "login_audit" not in users_data
    assert audit_manifest["storage"] == "sharded"
    assert audit_shards
    assert json.loads(audit_shards[-1].read_text(encoding="utf-8"))["events"][-1]["username"] == "admin"
    assert auth_store.AUTH_STORE.list_login_audit()[-1]["reason"] == "ok"


def test_login_audit_is_split_into_monthly_shards(monkeypatch, tmp_path):
    audit_file = tmp_path / "login_audit.json"
    monkeypatch.setenv("SRA_LOGIN_AUDIT_FILE", str(audit_file))
    auth_store = _load_auth_store(monkeypatch, tmp_path)

    import api.services.auth_login_audit_store as auth_login_audit_store

    monkeypatch.setattr(auth_login_audit_store, "_utc_now", lambda: "2026-01-05T00:00:00+00:00")
    auth_store.AUTH_STORE.record_login_audit("admin", success=True, reason="jan")
    monkeypatch.setattr(auth_login_audit_store, "_utc_now", lambda: "2026-02-05T00:00:00+00:00")
    auth_store.AUTH_STORE.record_login_audit("admin", success=True, reason="feb")

    shard_dir = audit_file.with_suffix(audit_file.suffix + ".d")
    assert (shard_dir / "login_audit-202601.json").exists()
    assert (shard_dir / "login_audit-202602.json").exists()
    assert [event["reason"] for event in auth_store.AUTH_STORE.list_login_audit(2)] == ["jan", "feb"]


def test_auth_store_recovers_users_file_from_backup(monkeypatch, tmp_path):
    auth_store = _load_auth_store(monkeypatch, tmp_path)
    users_file = tmp_path / "users.json"
    backup_file = users_file.with_suffix(users_file.suffix + ".bak")
    healthy_data = json.loads(users_file.read_text(encoding="utf-8"))
    backup_file.write_text(json.dumps(healthy_data), encoding="utf-8")
    users_file.write_text("{broken json", encoding="utf-8")

    users = auth_store.AUTH_STORE.list_users()

    assert any(user["username"] == "admin" for user in users)
    assert json.loads(users_file.read_text(encoding="utf-8"))["users"]["admin"]["role"] == "superuser"


def test_legacy_login_audit_is_migrated_to_separate_file(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({"users": {}, "login_audit": [{"username": "legacy", "success": True, "reason": "ok"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SRA_LOGIN_AUDIT_FILE", str(tmp_path / "audit.json"))
    auth_store = _load_auth_store(monkeypatch, tmp_path)

    assert auth_store.AUTH_STORE.list_login_audit()[-1]["username"] == "legacy"


def test_json_store_keeps_daily_backup_once_and_recovers_from_history(tmp_path, caplog):
    from api.services.auth_json_store import JsonFileStore

    caplog.set_level(logging.WARNING)
    store = JsonFileStore(max_backup_versions=20)
    path = tmp_path / "store.json"
    for idx in range(5):
        store.write(path, {"version": idx}, prefix=".test_store.")

    versioned_backups = sorted(tmp_path.glob("store.json.bak.*"), reverse=True)
    assert len(versioned_backups) == 1
    assert json.loads(versioned_backups[0].read_text(encoding="utf-8"))["version"] == 0
    assert json.loads(path.with_suffix(path.suffix + ".bak").read_text(encoding="utf-8"))["version"] == 3

    path.with_suffix(path.suffix + ".bak").write_text("{broken backup", encoding="utf-8")
    path.write_text("{broken current", encoding="utf-8")

    recovered = store.read(path, {"version": "default"})

    assert recovered["version"] == 0
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 0
    recovery_events = [json.loads(line) for line in path.with_suffix(path.suffix + ".recovery.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(event["action"] == "backup_unusable" for event in recovery_events)
    assert recovery_events[-1]["action"] == "recovered_from_backup"
    assert "auth_json_recovered_from_backup" in caplog.text


def test_json_store_prunes_daily_backups_to_configured_limit(tmp_path):
    from api.services.auth_json_store import JsonFileStore

    store = JsonFileStore(max_backup_versions=20)
    path = tmp_path / "store.json"
    for day in range(1, 23):
        (tmp_path / f"store.json.bak.202601{day:02d}").write_text('{"ok": true}', encoding="utf-8")

    store.prune_backups(path)

    versioned_backups = sorted(tmp_path.glob("store.json.bak.*"), reverse=True)
    assert len(versioned_backups) == 20
    assert versioned_backups[0].name == "store.json.bak.20260122"
    assert versioned_backups[-1].name == "store.json.bak.20260103"
