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


def test_selected_sql_registry_requires_membership(tmp_path, monkeypatch):
    path = tmp_path / "config/requirements/custom.json"
    path.parent.mkdir(parents=True); path.write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch, REQUIREMENT_SQL_REGISTRY_FILE=path)
    assert _verify(tmp_path, {"config/requirements/custom.json": b"{}"}, monkeypatch,
                   REQUIREMENT_SQL_REGISTRY_FILE=path)["identity_verified"]


def test_selected_editor_form_requires_membership(tmp_path, monkeypatch):
    path = tmp_path / "config/editor.custom.json"
    path.parent.mkdir(); path.write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected_runtime_input"):
        _verify(tmp_path, {}, monkeypatch, SRA_EDITOR_FORM_CONFIG=path)


@pytest.mark.parametrize("selector", ["MANUAL_SYNONYMS_DIR", "INDEXES_CONFIG",
                                      "REQUIREMENT_SQL_REGISTRY_FILE", "SRA_EDITOR_FORM_CONFIG"])
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
