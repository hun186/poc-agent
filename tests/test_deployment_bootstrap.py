from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from config.deployment_bootstrap import (
    DeploymentBootstrapError, KEY_NAME, KEY_SCOPES, _read_state, bootstrap, main,
)
from sra_api.security.service_key_store import ServiceKeyStore


@pytest.fixture
def deployment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"connections": {"requirement_control": {
        "server": "sql.example", "database": "sra", "trusted_connection": "true",
    }}, "queries": {}}), encoding="utf-8")
    monkeypatch.setenv("REQUIREMENT_SQL_REGISTRY_FILE", str(registry))
    monkeypatch.setenv("SRA_SERVICE_KEYS_FILE", str(tmp_path / "keys.json"))
    monkeypatch.setenv("SRA_DEPLOYMENT_STATE_DIR", str(tmp_path / ".sra_runtime"))
    monkeypatch.setattr("data_ingestion.requirements.connections.detect_odbc_driver", lambda _: "test-driver")
    return tmp_path


def test_first_run_is_secure_exact_scope_and_restart_is_idempotent(deployment: Path, capsys) -> None:
    state_path = bootstrap(project_root=deployment, port=9123)
    state = _read_state(state_path)
    token = state["REQUIREMENT_HANDOFF_CREDENTIAL"]
    first_store = (deployment / "keys.json").read_text(encoding="utf-8")

    assert stat_mode(state_path.parent) == 0o700
    assert stat_mode(state_path) == 0o600
    assert state["REQUIREMENT_HANDOFF_API_BASE_URL"] == "http://127.0.0.1:9123"
    metadata = ServiceKeyStore(deployment / "keys.json").resolve(token)
    assert metadata["name"] == KEY_NAME
    assert frozenset(metadata["scopes"]) == KEY_SCOPES

    assert bootstrap(project_root=deployment, port=9123) == state_path
    assert _read_state(state_path)["REQUIREMENT_HANDOFF_CREDENTIAL"] == token
    assert (deployment / "keys.json").read_text(encoding="utf-8") == first_store
    captured = capsys.readouterr()
    assert token not in captured.out and token not in captured.err


def test_cli_stdout_contains_only_machine_readable_state_path(deployment: Path, capsys) -> None:
    assert main(["bootstrap", "--project-root", str(deployment), "--port", "9002"]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"deployment_bootstrap_state_path={deployment / '.sra_runtime' / 'requirement_handoff.env'}\n"


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_missing_state_with_existing_canonical_key_fails_closed(deployment: Path) -> None:
    ServiceKeyStore(deployment / "keys.json").create(KEY_NAME, KEY_SCOPES, "test")
    with pytest.raises(DeploymentBootstrapError, match="canonical_key_without_state"):
        bootstrap(project_root=deployment, port=9002)


def test_corrupt_and_symlink_state_fail_without_overwrite(deployment: Path) -> None:
    state_dir = deployment / ".sra_runtime"
    state_dir.mkdir(mode=0o700)
    state = state_dir / "requirement_handoff.env"
    state.write_text("broken", encoding="utf-8")
    os.chmod(state, 0o600)
    with pytest.raises(DeploymentBootstrapError, match="state_file_corrupt"):
        bootstrap(project_root=deployment, port=9002)
    assert state.read_text() == "broken"

    state.unlink()
    target = deployment / "target"
    target.write_text("x")
    state.symlink_to(target)
    with pytest.raises(DeploymentBootstrapError, match="state_file_symlink"):
        bootstrap(project_root=deployment, port=9002)


def test_revoked_persisted_key_and_additional_scope_fail_closed(deployment: Path) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    state = _read_state(state_path)
    store = ServiceKeyStore(deployment / "keys.json")
    store.revoke(state["SRA_BOOTSTRAP_HANDOFF_KEY_ID"], "test")
    with pytest.raises(DeploymentBootstrapError, match="handoff_credential_unresolved"):
        bootstrap(project_root=deployment, port=9002)


def test_second_active_canonical_key_fails_normal_restart(deployment: Path) -> None:
    bootstrap(project_root=deployment, port=9002)
    ServiceKeyStore(deployment / "keys.json").create(KEY_NAME, KEY_SCOPES, "unexpected")
    with pytest.raises(DeploymentBootstrapError, match="canonical_key_ambiguous"):
        bootstrap(project_root=deployment, port=9002)


def test_repair_rotates_key_without_disclosing_credential(deployment: Path, capsys) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    old = _read_state(state_path)
    assert bootstrap(project_root=deployment, port=9002, repair=True) == state_path
    new = _read_state(state_path)
    keys = ServiceKeyStore(deployment / "keys.json").list_keys()
    assert new["SRA_BOOTSTRAP_HANDOFF_KEY_ID"] != old["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]
    assert [item["status"] for item in keys if item["key_id"] == old["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]] == ["revoked"]
    assert len([item for item in keys if item["name"] == KEY_NAME and item["status"] == "active"]) == 1
    captured = capsys.readouterr()
    assert old["REQUIREMENT_HANDOFF_CREDENTIAL"] not in captured.out + captured.err
    assert new["REQUIREMENT_HANDOFF_CREDENTIAL"] not in captured.out + captured.err


def test_repair_rejects_ambiguous_existing_keys(deployment: Path) -> None:
    bootstrap(project_root=deployment, port=9002)
    ServiceKeyStore(deployment / "keys.json").create(KEY_NAME, KEY_SCOPES, "unexpected")
    with pytest.raises(DeploymentBootstrapError, match="repair_identity_ambiguous"):
        bootstrap(project_root=deployment, port=9002, repair=True)


def test_repair_state_write_failure_keeps_old_credential_usable(deployment: Path, monkeypatch) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    old = _read_state(state_path)
    monkeypatch.setattr("config.deployment_bootstrap._write_state", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        bootstrap(project_root=deployment, port=9002, repair=True)
    store = ServiceKeyStore(deployment / "keys.json")
    assert store.resolve(old["REQUIREMENT_HANDOFF_CREDENTIAL"])["key_id"] == old["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]
    assert len([item for item in store.list_keys() if item["name"] == KEY_NAME and item["status"] == "active"]) == 1


def test_repair_post_replace_fsync_failure_retains_replacement_for_recovery(
    deployment: Path, monkeypatch,
) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    old_id = _read_state(state_path)["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]
    from config import deployment_bootstrap
    real_write = deployment_bootstrap._write_state

    def replace_then_fail(path, values):
        real_write(path, values)
        raise OSError("directory fsync")

    monkeypatch.setattr(deployment_bootstrap, "_write_state", replace_then_fail)
    with pytest.raises(OSError, match="directory fsync"):
        bootstrap(project_root=deployment, port=9002, repair=True)
    replacement = _read_state(state_path)
    store = ServiceKeyStore(deployment / "keys.json")
    assert store.resolve(replacement["REQUIREMENT_HANDOFF_CREDENTIAL"])["key_id"] == replacement[
        "SRA_BOOTSTRAP_HANDOFF_KEY_ID"
    ]
    assert len([item for item in store.list_keys() if item["name"] == KEY_NAME and item["status"] == "active"]) == 2

    monkeypatch.setattr(deployment_bootstrap, "_write_state", real_write)
    assert bootstrap(project_root=deployment, port=9002, repair=True) == state_path
    active = [item for item in store.list_keys() if item["name"] == KEY_NAME and item["status"] == "active"]
    assert [item["key_id"] for item in active] == [replacement["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]]
    assert active[0]["key_id"] != old_id


def test_repair_missing_state_replaces_unique_bootstrap_orphan(deployment: Path) -> None:
    store = ServiceKeyStore(deployment / "keys.json")
    orphan, _ = store.create(KEY_NAME, KEY_SCOPES, "deployment-bootstrap")

    state_path = bootstrap(project_root=deployment, port=9002, repair=True)
    state = _read_state(state_path)
    assert state["SRA_BOOTSTRAP_HANDOFF_KEY_ID"] != orphan["key_id"]
    assert store.resolve(state["REQUIREMENT_HANDOFF_CREDENTIAL"])["key_id"] == state[
        "SRA_BOOTSTRAP_HANDOFF_KEY_ID"
    ]
    assert [item["status"] for item in store.list_keys() if item["key_id"] == orphan["key_id"]] == ["revoked"]


def test_repair_recovers_first_run_interruption_after_journal_before_state(
    deployment: Path, monkeypatch,
) -> None:
    store = ServiceKeyStore(deployment / "keys.json")
    orphan, _ = store.create(KEY_NAME, KEY_SCOPES, "deployment-bootstrap")
    from config import deployment_bootstrap
    real_write = deployment_bootstrap._write_state

    monkeypatch.setattr(
        "config.deployment_bootstrap._write_state",
        lambda *_: (_ for _ in ()).throw(SystemExit("process interrupted")),
    )
    with pytest.raises(SystemExit, match="process interrupted"):
        bootstrap(project_root=deployment, port=9002, repair=True)

    journal_path = deployment / ".sra_runtime" / "requirement_handoff.repair.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["version"] == 2
    assert journal["operation"] == "first_run_orphan_recovery"
    assert journal["old_state_present"] is False
    assert journal["old_key_id"] == orphan["key_id"]
    assert not (deployment / ".sra_runtime" / "requirement_handoff.env").exists()

    monkeypatch.setattr(deployment_bootstrap, "_write_state", real_write)
    state_path = bootstrap(project_root=deployment, port=9002, repair=True)
    assert ServiceKeyStore(deployment / "keys.json").resolve(
        _read_state(state_path)["REQUIREMENT_HANDOFF_CREDENTIAL"]
    ) is not None
    assert not journal_path.exists()


def test_repair_recovers_first_run_replacement_create_committed_before_raising(
    deployment: Path, monkeypatch,
) -> None:
    store = ServiceKeyStore(deployment / "keys.json")
    orphan, _ = store.create(KEY_NAME, KEY_SCOPES, "deployment-bootstrap")
    real_create = ServiceKeyStore.create

    def create_then_fail(store, *args, **kwargs):
        real_create(store, *args, **kwargs)
        raise OSError("repair create response lost")

    monkeypatch.setattr(ServiceKeyStore, "create", create_then_fail)
    with pytest.raises(OSError, match="repair create response lost"):
        bootstrap(project_root=deployment, port=9002, repair=True)

    active = [item for item in store.list_keys() if item["name"] == KEY_NAME and item["status"] == "active"]
    assert {item["key_id"] for item in active} == {
        orphan["key_id"],
        json.loads((deployment / ".sra_runtime" / "requirement_handoff.repair.json").read_text())["new_key_id"],
    }

    monkeypatch.setattr(ServiceKeyStore, "create", real_create)
    state_path = bootstrap(project_root=deployment, port=9002, repair=True)
    state = _read_state(state_path)
    active = [item for item in store.list_keys() if item["name"] == KEY_NAME and item["status"] == "active"]
    assert [item["key_id"] for item in active] == [state["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]]
    assert state["SRA_BOOTSTRAP_HANDOFF_KEY_ID"] != orphan["key_id"]


def test_repair_missing_state_rejects_unowned_or_ambiguous_keys(deployment: Path) -> None:
    store = ServiceKeyStore(deployment / "keys.json")
    store.create(KEY_NAME, KEY_SCOPES, "unrelated")
    with pytest.raises(DeploymentBootstrapError, match="repair_identity_ambiguous"):
        bootstrap(project_root=deployment, port=9002, repair=True)


def test_repair_does_not_infer_interruption_without_journal(deployment: Path) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    bootstrap(project_root=deployment, port=9002, repair=True)
    store = ServiceKeyStore(deployment / "keys.json")
    unknown, _ = store.create(KEY_NAME, KEY_SCOPES, "deployment-bootstrap")

    with pytest.raises(DeploymentBootstrapError, match="repair_identity_ambiguous"):
        bootstrap(project_root=deployment, port=9002, repair=True)
    active_ids = {item["key_id"] for item in store.list_keys() if item["status"] == "active"}
    assert unknown["key_id"] in active_ids
    assert _read_state(state_path)["SRA_BOOTSTRAP_HANDOFF_KEY_ID"] in active_ids


def test_repair_create_failure_preserves_state_and_key(deployment: Path, monkeypatch) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    before = state_path.read_bytes()
    monkeypatch.setattr(ServiceKeyStore, "create", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("create")))
    with pytest.raises(OSError, match="create"):
        bootstrap(project_root=deployment, port=9002, repair=True)
    assert state_path.read_bytes() == before


def test_repair_recovers_first_run_create_that_committed_before_raising(
    deployment: Path, monkeypatch,
) -> None:
    real_create = ServiceKeyStore.create

    def create_then_fail(store, name, scopes, created_by):
        real_create(store, name, scopes, created_by)
        raise OSError("create response lost")

    monkeypatch.setattr(ServiceKeyStore, "create", create_then_fail)
    with pytest.raises(OSError, match="create response lost"):
        bootstrap(project_root=deployment, port=9002)
    assert not (deployment / ".sra_runtime" / "requirement_handoff.env").exists()

    monkeypatch.setattr(ServiceKeyStore, "create", real_create)
    state_path = bootstrap(project_root=deployment, port=9002, repair=True)
    state = _read_state(state_path)
    store = ServiceKeyStore(deployment / "keys.json")
    assert store.resolve(state["REQUIREMENT_HANDOFF_CREDENTIAL"])["key_id"] == state[
        "SRA_BOOTSTRAP_HANDOFF_KEY_ID"
    ]
    assert len([item for item in store.list_keys() if item["name"] == KEY_NAME and item["status"] == "active"]) == 1


def test_repair_recovers_interruption_after_state_replace(deployment: Path, monkeypatch) -> None:
    state_path = bootstrap(project_root=deployment, port=9002)
    old_id = _read_state(state_path)["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]
    real_revoke = ServiceKeyStore.revoke

    def fail_old_revoke(store, key_id, revoked_by):
        if key_id == old_id:
            raise OSError("revoke")
        return real_revoke(store, key_id, revoked_by)

    monkeypatch.setattr(ServiceKeyStore, "revoke", fail_old_revoke)
    with pytest.raises(OSError, match="revoke"):
        bootstrap(project_root=deployment, port=9002, repair=True)
    replacement = _read_state(state_path)
    assert replacement["SRA_BOOTSTRAP_HANDOFF_KEY_ID"] != old_id
    monkeypatch.setattr(ServiceKeyStore, "revoke", real_revoke)
    assert bootstrap(project_root=deployment, port=9002, repair=True) == state_path
    active = [item for item in ServiceKeyStore(deployment / "keys.json").list_keys()
              if item["name"] == KEY_NAME and item["status"] == "active"]
    assert [item["key_id"] for item in active] == [replacement["SRA_BOOTSTRAP_HANDOFF_KEY_ID"]]


@pytest.mark.parametrize("connection", [
    {"server": "", "database": "sra", "trusted_connection": True},
    {"server": "sql.example", "database": "", "trusted_connection": True},
    {"server": "sql.example", "database": "sra", "trusted_connection": False},
])
def test_invalid_direct_sql_configuration_fails_preflight(deployment: Path, connection: dict) -> None:
    Path(os.environ["REQUIREMENT_SQL_REGISTRY_FILE"]).write_text(
        json.dumps({"connections": {"requirement_control": connection}, "queries": {}}), encoding="utf-8",
    )
    with pytest.raises(DeploymentBootstrapError, match="sql_connection_invalid"):
        bootstrap(project_root=deployment, port=9002)


def test_production_signing_configuration_fails_before_state(deployment: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        bootstrap(project_root=deployment, port=9002)
    assert not (deployment / ".sra_runtime").exists()


def test_missing_referenced_site_environment_fails_before_state(deployment: Path) -> None:
    registry = Path(os.environ["REQUIREMENT_SQL_REGISTRY_FILE"])
    registry.write_text(json.dumps({"connections": {"requirement_control": {
        "server_env": "ABSENT_SQL_HOST", "database": "sra", "trusted_connection": "true",
    }}, "queries": {}}))
    with pytest.raises(DeploymentBootstrapError, match="environment_missing:ABSENT_SQL_HOST"):
        bootstrap(project_root=deployment, port=9002)
    assert not (deployment / ".sra_runtime").exists()
