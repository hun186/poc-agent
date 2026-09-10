from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from config.deployment_bootstrap import (
    DeploymentBootstrapError, KEY_NAME, KEY_SCOPES, _read_state, bootstrap,
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


def test_missing_referenced_site_environment_fails_before_state(deployment: Path) -> None:
    registry = Path(os.environ["REQUIREMENT_SQL_REGISTRY_FILE"])
    registry.write_text(json.dumps({"connections": {"requirement_control": {
        "server_env": "ABSENT_SQL_HOST", "database": "sra", "trusted_connection": "true",
    }}, "queries": {}}))
    with pytest.raises(DeploymentBootstrapError, match="environment_missing:ABSENT_SQL_HOST"):
        bootstrap(project_root=deployment, port=9002)
    assert not (deployment / ".sra_runtime").exists()
