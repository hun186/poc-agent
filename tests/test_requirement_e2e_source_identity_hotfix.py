from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace
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


def test_runtime_policy_explicitly_classifies_runtime_root_files():
    from shared.runtime_provenance import RUNTIME_FILES, is_runtime_provenance_path

    assert "python_compat.py" in RUNTIME_FILES
    assert "run_sra_api.sh" in RUNTIME_FILES
    assert "app.py" in RUNTIME_FILES
    assert "telemetry.py" in RUNTIME_FILES
    assert "requirements.txt" in RUNTIME_FILES
    assert "__init__.py" not in RUNTIME_FILES
    assert is_runtime_provenance_path("python_compat.py")
    assert not is_runtime_provenance_path("README.md")
    assert not is_runtime_provenance_path("TODO.md")


def test_generator_includes_runtime_root_files_but_not_root_documentation(tmp_path):
    from tools.requirement_e2e_provenance import generate

    repo, reviewed = _repo(tmp_path)
    for path in ("python_compat.py", "run_sra_api.sh", "app.py", "telemetry.py", "requirements.txt",
                 "README.md", "TODO.md"):
        (repo / path).write_text(path + "\n")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "root runtime files")
    output = tmp_path / "provenance.json"
    generate(repo, _git(repo, "rev-parse", "HEAD"), output)
    paths = {entry["path"] for entry in json.loads(output.read_text())["runtime_files"]}
    assert {"python_compat.py", "run_sra_api.sh", "app.py", "telemetry.py", "requirements.txt"} <= paths
    assert paths.isdisjoint({"README.md", "TODO.md"})


def test_actual_module_discovery_accepts_reviewed_root_python_module(tmp_path):
    import sra_api.services.requirement_e2e_runtime_evidence as runtime_evidence

    reviewed = "a" * 40
    files = {"python_compat.py": b"reviewed", "requirement_scheduler/cli.py": b"worker"}
    _manifest(tmp_path, reviewed, files)
    original_modules = sys.modules.copy()
    try:
        sys.modules.clear()
        sys.modules["python_compat"] = SimpleNamespace(__file__=str(tmp_path / "python_compat.py"))
        evidence = runtime_evidence.collect_source_evidence(tmp_path)
    finally:
        sys.modules.clear()
        sys.modules.update(original_modules)
    assert evidence["active_runtime_files"] == ["python_compat.py", "requirement_scheduler/cli.py"]


@pytest.mark.parametrize(
    ("module_name", "relative_path"),
    [("thirdparty.api.client", "thirdparty/api/client.py"),
     ("vendor.telemetry", "vendor/telemetry.py")],
)
def test_actual_module_discovery_ignores_external_namespace_name_collisions(
    tmp_path, module_name, relative_path,
):
    import sra_api.services.requirement_e2e_runtime_evidence as runtime_evidence

    project = tmp_path / "project"
    external = tmp_path / "site-packages" / relative_path
    external.parent.mkdir(parents=True)
    external.write_text("VALUE = 1\n")
    _manifest(project, "a" * 40, {"requirement_scheduler/cli.py": b"worker"})
    original_modules = sys.modules.copy()
    try:
        sys.modules.clear()
        sys.modules[module_name] = SimpleNamespace(__file__=str(external))
        evidence = runtime_evidence.collect_source_evidence(project)
    finally:
        sys.modules.clear()
        sys.modules.update(original_modules)
    assert evidence["active_runtime_files"] == ["requirement_scheduler/cli.py"]


@pytest.mark.parametrize("module_name", ["sra_api.some_module", "python_compat"])
def test_actual_project_namespace_module_outside_project_is_shadowing(tmp_path, module_name):
    import sra_api.services.requirement_e2e_runtime_evidence as runtime_evidence

    project = tmp_path / "project"
    external = tmp_path / "site-packages" / (module_name.replace(".", "/") + ".py")
    external.parent.mkdir(parents=True)
    external.write_text("VALUE = 1\n")
    _manifest(project, "a" * 40, {"requirement_scheduler/cli.py": b"worker"})
    original_modules = sys.modules.copy()
    try:
        sys.modules.clear()
        sys.modules[module_name] = SimpleNamespace(__file__=str(external))
        with pytest.raises(RuntimeError, match="runtime_module_shadowing"):
            runtime_evidence.collect_source_evidence(project)
    finally:
        sys.modules.clear()
        sys.modules.update(original_modules)


def test_actual_residual_project_namespace_module_remains_blocking(tmp_path):
    import sra_api.services.requirement_e2e_runtime_evidence as runtime_evidence

    project = tmp_path / "project"
    files = {"requirement_scheduler/cli.py": b"worker"}
    _manifest(project, "a" * 40, files)
    residual = project / "requirement_scheduler" / "old_worker.py"
    residual.write_text("VALUE = 1\n")
    original_modules = sys.modules.copy()
    try:
        sys.modules.clear()
        sys.modules["requirement_scheduler.old_worker"] = SimpleNamespace(__file__=str(residual))
        with pytest.raises(RuntimeError, match="unexpected_active_runtime_module"):
            runtime_evidence.collect_source_evidence(project)
    finally:
        sys.modules.clear()
        sys.modules.update(original_modules)


@pytest.mark.parametrize("path", ["python_compat.py", "run_sra_api.sh"])
def test_modified_runtime_root_file_blocks_incremental_evidence(tmp_path, path):
    from sra_api.services.requirement_e2e_runtime_evidence import collect_source_evidence

    reviewed = "a" * 40
    files = {path: b"reviewed", "requirement_scheduler/cli.py": b"worker"}
    _manifest(tmp_path, reviewed, files)
    (tmp_path / path).write_bytes(b"modified")
    with pytest.raises(RuntimeError, match="active_runtime_source_mismatch"):
        collect_source_evidence(tmp_path, active_paths=[])


def test_generator_operator_and_deployment_share_runtime_path_policy():
    import operator_e2e.test_requirement_schedule_e2e as harness
    import sra_api.services.requirement_e2e_runtime_evidence as runtime_evidence
    import tools.requirement_e2e_provenance as generator
    from shared.runtime_provenance import RUNTIME_PATHS

    assert generator.RUNTIME_PATHS is RUNTIME_PATHS
    assert harness.RUNTIME_PATHS is RUNTIME_PATHS
    assert runtime_evidence.RUNTIME_PATHS is RUNTIME_PATHS


def test_provenance_generator_remains_directly_executable():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tools" / "requirement_e2e_provenance.py"), "--help"],
        cwd=root, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_generator_rejects_crlf_worktree_bytes_before_emitting_provenance(tmp_path):
    from tools.requirement_e2e_provenance import generate

    repo, reviewed = _repo(tmp_path)
    runtime = repo / "sra_api" / "main.py"
    runtime.write_bytes(b"VALUE = 1\r\n")
    output = tmp_path / "provenance.json"
    with pytest.raises(RuntimeError, match="runtime_worktree_bytes_differ_from_reviewed_source: sra_api/main.py"):
        generate(repo, reviewed, output)
    assert not output.exists()


def test_generator_emits_provenance_when_worktree_bytes_exactly_match(tmp_path):
    from tools.requirement_e2e_provenance import generate

    repo, reviewed = _repo(tmp_path)
    output = tmp_path / "provenance.json"
    generate(repo, reviewed, output)
    assert json.loads(output.read_text())["reviewed_runtime_sha"] == reviewed
