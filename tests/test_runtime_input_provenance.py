from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


def _manifest(root: Path, files: dict[str, bytes]) -> dict:
    entries = []
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    value = {"schema_version": 2, "repository": "hun186/poc-agent",
             "reviewed_runtime_sha": "a" * 40, "runtime_files": entries}
    (root / "REQUIREMENT_E2E_PROVENANCE.json").write_text(json.dumps(value))
    return value


def _verify(root: Path, files: dict[str, bytes], monkeypatch, **env):
    from sra_api.services.requirement_e2e_runtime_evidence import collect_source_evidence
    for key in ("APP_ENV", "ENV", "PY_ENV", "MANUAL_SYNONYMS_DIR", "INDEXES_CONFIG",
                "INDEX_CONFIG", "INDEXES_CONFIGS", "REQUIREMENT_SQL_REGISTRY_FILE",
                "SRA_EDITOR_FORM_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    _manifest(root, {"requirement_scheduler/cli.py": b"worker", **files})
    return collect_source_evidence(root, active_paths=[])


def test_closed_synonym_directory_blocks_only_auto_loaded_json(tmp_path, monkeypatch):
    (tmp_path / "config/synonyms").mkdir(parents=True)
    (tmp_path / "config/synonyms/extra.json").write_text("{}")
    (tmp_path / "config/synonyms/notes.txt").write_text("ignored")
    (tmp_path / "config/unrelated.json").write_text("inactive")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch)


def test_provenance_managed_synonym_passes_with_harmless_residue(tmp_path, monkeypatch):
    result = _verify(tmp_path, {"config/synonyms/base.JSON": b"{}"}, monkeypatch)
    (tmp_path / "config/synonyms/notes.txt").write_text("ignored")
    (tmp_path / "config/unrelated.json").write_text("inactive")
    result = _verify(tmp_path, {"config/synonyms/base.JSON": b"{}"}, monkeypatch)
    assert result["identity_verified"] is True


def test_selected_environment_index_requires_membership_but_stale_other_does_not(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/indexes.prod.yaml").write_text("default_indexes: [prod]")
    (tmp_path / "config/indexes.dev.yaml").write_text("default_indexes: [dev]")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch, APP_ENV="prod")
    assert _verify(tmp_path, {"config/indexes.prod.yaml": b"default_indexes: [prod]"},
                   monkeypatch, APP_ENV="prod")["identity_verified"]


@pytest.mark.parametrize("selector", ["INDEXES_CONFIG", "INDEXES_CONFIGS"])
def test_explicit_project_index_selector_requires_membership(tmp_path, monkeypatch, selector):
    path = tmp_path / "config/custom.yaml"
    path.parent.mkdir(); path.write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch, **{selector: path})
    assert _verify(tmp_path, {"config/custom.yaml": b"{}"}, monkeypatch,
                   **{selector: path})["identity_verified"]


def test_ignored_deployment_sql_registry_is_not_release_provenance(tmp_path, monkeypatch):
    path = tmp_path / "config/requirements/sql_registry.json"
    path.parent.mkdir(parents=True)
    secret = '{"password":"not-public","queries":{"private":"SELECT secret FROM private"}}'
    path.write_text(secret)

    result = _verify(tmp_path, {}, monkeypatch)

    assert result["identity_verified"] is True
    serialized = json.dumps(result)
    assert secret not in serialized
    assert hashlib.sha256(secret.encode()).hexdigest() not in serialized
    assert str(path.resolve()) not in serialized
    assert "SELECT secret FROM private" not in serialized
    assert "not-public" not in serialized


def test_external_sql_registry_is_deployment_local(tmp_path, monkeypatch):
    path = tmp_path.parent / "private-registry.json"
    path.write_text('{"password":"external-secret"}')

    result = _verify(tmp_path, {}, monkeypatch, REQUIREMENT_SQL_REGISTRY_FILE=path)

    assert result["identity_verified"] is True
    serialized = json.dumps(result)
    assert str(path.resolve()) not in serialized
    assert "external-secret" not in serialized


def test_selected_editor_form_requires_membership(tmp_path, monkeypatch):
    path = tmp_path / "config/editor.custom.json"
    path.parent.mkdir(); path.write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch, SRA_EDITOR_FORM_CONFIG=path)


@pytest.mark.parametrize("selector", ["MANUAL_SYNONYMS_DIR", "INDEXES_CONFIG",
                                      "SRA_EDITOR_FORM_CONFIG"])
def test_external_material_input_fails_closed(tmp_path, monkeypatch, selector):
    external = tmp_path.parent / ("external-dir" if selector == "MANUAL_SYNONYMS_DIR" else "external.json")
    if selector == "MANUAL_SYNONYMS_DIR":
        external.mkdir(); (external / "one.json").write_text("{}")
    else:
        external.write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch, **{selector: external})


def test_generator_rejects_untracked_auto_loaded_synonym(tmp_path):
    from tools.requirement_e2e_provenance import generate
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    path = repo / "config/synonyms/base.json"; path.parent.mkdir(parents=True); path.write_text("{}")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    reviewed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "config/synonyms/extra.json").write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        generate(repo, reviewed, tmp_path / "out.json")


@pytest.mark.parametrize("external", [False, True])
def test_generator_allows_deployment_local_sql_registry(tmp_path, monkeypatch, external):
    from tools.requirement_e2e_provenance import generate
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    tracked = repo / "shared/runtime_provenance.py"
    tracked.parent.mkdir(parents=True); tracked.write_text("# tracked\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    reviewed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    registry = (tmp_path / "private-registry.json" if external
                else repo / "config/requirements/sql_registry.json")
    registry.parent.mkdir(parents=True, exist_ok=True); registry.write_text('{"password":"private"}')
    if external:
        monkeypatch.setenv("REQUIREMENT_SQL_REGISTRY_FILE", str(registry))
    else:
        monkeypatch.delenv("REQUIREMENT_SQL_REGISTRY_FILE", raising=False)
    output = tmp_path / "out.json"

    generate(repo, reviewed, output)

    serialized = output.read_text()
    assert "sql_registry.json" not in serialized
    assert "private" not in serialized


def test_empty_manual_synonyms_directory_disables_discovery(tmp_path):
    from shared.runtime_provenance import manual_synonym_files
    (tmp_path / "vercel.json").write_text("{}")
    assert manual_synonym_files(tmp_path, {"MANUAL_SYNONYMS_DIR": ""}) == []


def test_empty_manual_synonyms_directory_does_not_select_root_json(tmp_path, monkeypatch):
    (tmp_path / "vercel.json").write_text("{}")
    assert _verify(tmp_path, {}, monkeypatch, MANUAL_SYNONYMS_DIR="")["identity_verified"]


def test_absent_manual_synonyms_directory_defaults_and_enforces_membership(tmp_path, monkeypatch):
    (tmp_path / "config/synonyms").mkdir(parents=True)
    (tmp_path / "config/synonyms/extra.json").write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch)


def test_explicit_nonempty_manual_synonyms_directory_is_used(tmp_path):
    from shared.runtime_provenance import manual_synonym_files
    selected = tmp_path / "custom-synonyms"
    selected.mkdir(); expected = selected / "one.JSON"; expected.write_text("{}")
    assert manual_synonym_files(tmp_path, {"MANUAL_SYNONYMS_DIR": "custom-synonyms"}) == [expected]


def test_all_requirement_entrypoints_share_sql_registry_selector():
    import config.deployment_bootstrap as bootstrap
    import requirement_scheduler.cli as scheduler_cli
    import shared.runtime_provenance as policy
    import sra_api.main as api_main

    assert api_main.requirement_sql_registry_path is policy.requirement_sql_registry_path
    assert scheduler_cli.requirement_sql_registry_path is policy.requirement_sql_registry_path
    assert bootstrap.requirement_sql_registry_path is policy.requirement_sql_registry_path


def test_generator_and_verifier_use_shared_discovery_function():
    import shared.runtime_provenance as policy
    import tools.requirement_e2e_provenance as generator
    import sra_api.services.requirement_e2e_runtime_evidence as evidence
    assert generator.discover_release_runtime_inputs is policy.discover_release_runtime_inputs
    assert evidence.discover_release_runtime_inputs is policy.discover_release_runtime_inputs


def test_remote_preflight_preserves_unexpected_runtime_input_category():
    from operator_e2e.requirement_e2e_evidence import RemoteDeploymentEvidenceProvider
    from operator_e2e.requirement_e2e_support import HarnessFailure

    class Api:
        def get(self, *_args, **_kwargs):
            raise HarnessFailure("unexpected_runtime_input")

    with pytest.raises(HarnessFailure, match="unexpected_runtime_input") as raised:
        RemoteDeploymentEvidenceProvider(Api()).preflight()
    assert raised.value.stage == "RUNTIME_WORKERS"
