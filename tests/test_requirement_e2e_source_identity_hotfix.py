from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from operator_e2e.requirement_e2e_support import HarnessFailure


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"; repo.mkdir()
    _git(repo, "init"); _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "operator_e2e").mkdir(); (repo / "sra_api").mkdir(); (repo / ".codex").mkdir()
    (repo / "operator_e2e" / "runner.py").write_text("VALUE = 1\n")
    (repo / "sra_api" / "main.py").write_text("VALUE = 1\n")
    (repo / ".codex" / "memory.md").write_text("baseline\n")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_operator_exact_reviewed_sha_passes(tmp_path):
    from operator_e2e.source_identity import inspect_operator_source
    repo, reviewed = _repo(tmp_path)
    assert inspect_operator_source(repo, reviewed)["identity_status"] == "exact"


def test_operator_documentation_only_descendant_passes_with_warning(tmp_path):
    from operator_e2e.source_identity import inspect_operator_source
    repo, reviewed = _repo(tmp_path)
    (repo / ".codex" / "memory.md").write_text("new docs\n")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "docs")
    result = inspect_operator_source(repo, reviewed)
    assert result["identity_status"] == "reviewed_equivalent_descendant"
    assert result["runtime_relevant_committed_changes"] == []
    assert result["warnings"] == ["newer_non_runtime_commits"]


@pytest.mark.parametrize("path", ["operator_e2e/runner.py", "sra_api/main.py"])
def test_operator_runtime_descendant_blocks(tmp_path, path):
    from operator_e2e.source_identity import inspect_operator_source
    repo, reviewed = _repo(tmp_path)
    (repo / path).write_text("VALUE = 2\n"); _git(repo, "add", "."); _git(repo, "commit", "-m", "runtime")
    with pytest.raises(HarnessFailure, match="operator_runtime_source_changed_since_review"):
        inspect_operator_source(repo, reviewed)


def test_operator_non_ancestor_blocks(tmp_path):
    from operator_e2e.source_identity import inspect_operator_source
    repo, reviewed = _repo(tmp_path)
    _git(repo, "checkout", "--orphan", "other"); _git(repo, "rm", "-rf", ".")
    (repo / "README.md").write_text("other\n"); _git(repo, "add", "."); _git(repo, "commit", "-m", "other")
    with pytest.raises(HarnessFailure, match="operator_source_not_reviewed_descendant"):
        inspect_operator_source(repo, reviewed)


def test_generated_and_documentation_dirty_warn_but_runtime_dirty_blocks(tmp_path):
    from operator_e2e.source_identity import inspect_operator_source
    repo, reviewed = _repo(tmp_path)
    (repo / "operator_e2e" / "gaza_report.docx").write_bytes(b"generated")
    out = repo / "operator_e2e" / "output" / "nested"; out.mkdir(parents=True)
    (out / "result.json").write_text("{}")
    (repo / ".codex" / "memory.md").write_text("dirty docs\n")
    result = inspect_operator_source(repo, reviewed)
    assert result["runtime_relevant_dirty_changes"] == []
    assert result["non_runtime_dirty_changes"]
    (repo / "sra_api" / "main.py").write_text("VALUE = 3\n")
    with pytest.raises(HarnessFailure, match="operator_runtime_dirty"):
        inspect_operator_source(repo, reviewed)


def test_untracked_python_in_importable_location_blocks(tmp_path):
    from operator_e2e.source_identity import inspect_operator_source
    repo, reviewed = _repo(tmp_path)
    (repo / "sra_api" / "old.py").write_text("VALUE = 1\n")
    with pytest.raises(HarnessFailure, match="operator_runtime_dirty"):
        inspect_operator_source(repo, reviewed)


def _manifest(root: Path, reviewed: str, files: dict[str, bytes]) -> None:
    entries = []
    for path, data in sorted(files.items()):
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        entries.append({"path": path, "sha256": hashlib.sha256(data).hexdigest()})
    (root / "REQUIREMENT_E2E_PROVENANCE.json").write_text(json.dumps({
        "schema_version": 1, "repository": "hun186/poc-agent",
        "reviewed_runtime_sha": reviewed, "runtime_files": entries,
    }, sort_keys=True))


def test_incremental_package_accepts_matching_active_runtime_and_ignores_inactive_residual(tmp_path):
    from sra_api.services.requirement_e2e_runtime_evidence import collect_source_evidence
    reviewed = "a" * 40
    _manifest(tmp_path, reviewed, {"sra_api/main.py": b"current", "requirement_scheduler/cli.py": b"worker"})
    (tmp_path / "requirement_scheduler" / "old_worker.py").write_text("inactive")
    evidence = collect_source_evidence(tmp_path, active_paths=[tmp_path / "sra_api" / "main.py"])
    assert evidence["identity_kind"] == "incremental_package"
    assert evidence["identity_verified"] is True
    assert evidence["inactive_residual_count"] == 1


@pytest.mark.parametrize("mode", ["hash", "loaded", "shadow"])
def test_incremental_package_blocks_active_runtime_drift(tmp_path, mode):
    from sra_api.services.requirement_e2e_runtime_evidence import collect_source_evidence
    reviewed = "a" * 40
    expected = tmp_path / "sra_api" / "main.py"
    _manifest(tmp_path, reviewed, {"sra_api/main.py": b"current", "requirement_scheduler/cli.py": b"worker"})
    active = [expected]
    if mode == "hash": expected.write_bytes(b"changed")
    elif mode == "loaded":
        old = tmp_path / "requirement_scheduler" / "old_worker.py"; old.write_text("old"); active.append(old)
    else:
        shadow = tmp_path.parent / "shadow" / "sra_api" / "main.py"; shadow.parent.mkdir(parents=True); shadow.write_text("current")
        active = [shadow]
    expected_error = {"hash": "active_runtime_source_mismatch", "loaded": "unexpected_active_runtime_module", "shadow": "runtime_module_shadowing"}[mode]
    with pytest.raises(RuntimeError, match=expected_error): collect_source_evidence(tmp_path, active_paths=active)


def test_incremental_source_external_reviewed_authority_is_checked(tmp_path):
    from operator_e2e.test_requirement_schedule_e2e import _validate_deployment_source
    with pytest.raises(HarnessFailure, match="deployment_source_provenance_mismatch"):
        _validate_deployment_source({"identity_kind": "incremental_package", "identity_verified": True,
                                     "reviewed_runtime_sha": "b" * 40, "runtime_files": []}, "a" * 40)
