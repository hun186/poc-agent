import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.deployment_manifest import (
    ManifestError,
    canonical_json_bytes,
    compute_files_root,
    load_policy,
    normalize_manifest_path,
    validate_unique_paths,
    git_file_map,
    require_runtime_equivalence,
    build_manifest,
    verify_deployment,
)


POLICY_PATH = Path(__file__).parents[1] / "tools" / "deployment_manifest_policy.json"


def test_policy_declares_expected_runtime_and_release_tool_scope():
    policy = load_policy(POLICY_PATH)
    assert policy["schema_version"] == 1
    assert policy["repository"] == "hun186/poc-agent"
    assert {"agent", "sra_api", "requirement_scheduler"} <= set(policy["managed_roots"])
    assert "run_sra_api.sh" in policy["managed_files"]
    assert "tools/deployment_manifest.py" in policy["release_tool_files"]


def test_policy_has_no_overlap_or_unsafe_paths():
    policy = load_policy(POLICY_PATH)
    paths = policy["managed_roots"] + policy["managed_files"] + policy["release_tool_files"]
    assert all(not item.startswith("/") and ".." not in item.split("/") for item in paths)
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize("value", ["../x.py", "a/../x.py", "/tmp/x.py", "", "a//b"])
def test_normalize_manifest_path_rejects_traversal_and_absolute(value):
    with pytest.raises(ManifestError):
        normalize_manifest_path(value)


def test_manifest_bytes_are_deterministic():
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}\n'


def test_files_root_is_order_independent():
    entries = [
        {"class": "runtime", "path": "b.py", "git_mode": "100644", "size": 1, "sha256": "b" * 64},
        {"class": "runtime", "path": "a.py", "git_mode": "100644", "size": 1, "sha256": "a" * 64},
    ]
    assert compute_files_root(entries) == compute_files_root(list(reversed(entries)))


def test_casefold_collisions_fail():
    with pytest.raises(ManifestError, match="path_case_collision"):
        validate_unique_paths(["agent/X.py", "agent/x.py"])


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def runtime_repo(tmp_path: Path) -> tuple[Path, str, dict]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Manifest Test")
    (repo / "agent").mkdir()
    (repo / "tools").mkdir()
    (repo / "agent/runtime.py").write_text("VALUE = 1\n")
    (repo / "tools/deployment_manifest.py").write_text("TOOL = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    policy = {"managed_roots": ["agent"], "managed_files": [], "release_tool_files": ["tools/deployment_manifest.py"]}
    return repo, git(repo, "rev-parse", "HEAD"), policy


def maps(repo, commit, policy):
    return git_file_map(repo, commit, policy, file_class="runtime")


def test_runtime_equivalence_accepts_release_tool_only_change(tmp_path):
    repo, base, policy = runtime_repo(tmp_path)
    (repo / "tools/deployment_manifest.py").write_text("TOOL = 2\n")
    git(repo, "commit", "-qam", "tool")
    require_runtime_equivalence(maps(repo, base, policy), maps(repo, "HEAD", policy))


@pytest.mark.parametrize("kind", ["blob", "addition", "mode"])
def test_runtime_equivalence_rejects_runtime_change(tmp_path, kind):
    repo, base, policy = runtime_repo(tmp_path)
    if kind == "blob":
        (repo / "agent/runtime.py").write_text("VALUE = 2\n")
    elif kind == "addition":
        (repo / "agent/new.py").write_text("NEW = 1\n")
    else:
        os.chmod(repo / "agent/runtime.py", 0o755)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", kind)
    with pytest.raises(ManifestError, match="runtime_source_not_equivalent"):
        require_runtime_equivalence(maps(repo, base, policy), maps(repo, "HEAD", policy))


def build_repo(tmp_path: Path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Manifest Test")
    for path, data in {
        "agent/runtime.py": b"VALUE = 1\n",
        "run.sh": b"#!/usr/bin/env bash\n",
        "tools/__init__.py": b'"""tools"""\n',
        "tools/deployment_manifest.py": b"TOOL = 1\n",
    }.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    policy = {
        "schema_version": 1, "repository": "hun186/poc-agent",
        "managed_roots": ["agent"], "managed_files": ["run.sh"],
        "release_tool_files": ["tools/__init__.py", "tools/deployment_manifest.py", "tools/deployment_manifest_policy.json"],
        "allowed_runtime_extra_globs": ["**/__pycache__/**"],
        "guarded_root_extensions": [".py", ".sh", ".pth"],
    }
    (repo / "tools/deployment_manifest_policy.json").write_text(json.dumps(policy))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "release")
    commit = git(repo, "rev-parse", "HEAD")
    package = tmp_path / "package"
    package.mkdir()
    for path in ["agent/runtime.py", "run.sh", *policy["release_tool_files"]]:
        target = package / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((repo / path).read_bytes())
    return repo, commit, package


def do_build(tmp_path: Path):
    repo, commit, package = build_repo(tmp_path)
    receipt = tmp_path / "receipt.json"
    result = build_manifest(repo_root=repo, package_root=package, source_commit=commit,
                            reviewed_runtime_commit=commit, receipt_out=receipt)
    return repo, commit, package, receipt, result


def test_build_accepts_exact_staged_package(tmp_path):
    _, _, package, receipt, result = do_build(tmp_path)
    assert result[0] == package / "DEPLOYMENT_MANIFEST.json"
    assert receipt.is_file() and len(result[2]) == 64


def test_build_rejects_crlf_or_other_byte_change(tmp_path):
    repo, commit, package = build_repo(tmp_path)
    (package / "run.sh").write_bytes(b"#!/usr/bin/env bash\r\n")
    with pytest.raises(ManifestError, match="managed_file_hash_mismatch"):
        build_manifest(repo_root=repo, package_root=package, source_commit=commit,
                       reviewed_runtime_commit=commit, receipt_out=tmp_path / "receipt")


@pytest.mark.parametrize("mutation", ["missing", "symlink", "unexpected"])
def test_build_rejects_invalid_staging(tmp_path, mutation):
    repo, commit, package = build_repo(tmp_path)
    target = package / "agent/runtime.py"
    if mutation == "missing": target.unlink()
    elif mutation == "symlink": target.unlink(); target.symlink_to(package / "run.sh")
    else: (package / "agent/extra.py").write_text("bad\n")
    with pytest.raises(ManifestError):
        build_manifest(repo_root=repo, package_root=package, source_commit=commit,
                       reviewed_runtime_commit=commit, receipt_out=tmp_path / "receipt")


def test_build_allows_declared_cache_extra(tmp_path):
    repo, commit, package = build_repo(tmp_path)
    cache = package / "agent/__pycache__/runtime.pyc"
    cache.parent.mkdir(); cache.write_bytes(b"cache")
    build_manifest(repo_root=repo, package_root=package, source_commit=commit,
                   reviewed_runtime_commit=commit, receipt_out=tmp_path / "receipt")


def test_receipt_must_be_outside_package_root(tmp_path):
    repo, commit, package = build_repo(tmp_path)
    with pytest.raises(ManifestError, match="receipt_inside_package"):
        build_manifest(repo_root=repo, package_root=package, source_commit=commit,
                       reviewed_runtime_commit=commit, receipt_out=package / "receipt")


def test_repeated_builds_produce_identical_manifest_bytes(tmp_path):
    _, _, package, _, _ = do_build(tmp_path)
    first = (package / "DEPLOYMENT_MANIFEST.json").read_bytes()
    # An existing generated manifest is deliberately ignored as build output.
    repo = tmp_path / "source"; commit = git(repo, "rev-parse", "HEAD")
    build_manifest(repo_root=repo, package_root=package, source_commit=commit,
                   reviewed_runtime_commit=commit, receipt_out=tmp_path / "receipt2")
    assert (package / "DEPLOYMENT_MANIFEST.json").read_bytes() == first


def verify(package: Path, digest: str | None):
    return verify_deployment(deployment_root=package,
                             manifest_path=package / "DEPLOYMENT_MANIFEST.json",
                             expected_manifest_sha256=digest)


def test_verify_without_trusted_digest_is_blocked(tmp_path, capsys):
    *_, package, _, result = do_build(tmp_path)
    assert verify(package, None) == 2
    assert "trusted_manifest_digest_missing" in capsys.readouterr().out


def test_verify_wrong_or_tampered_manifest_fails(tmp_path):
    *_, package, _, result = do_build(tmp_path)
    assert verify(package, "0" * 64) == 1
    (package / "DEPLOYMENT_MANIFEST.json").write_bytes(b"{}\n")
    assert verify(package, result[2]) == 1


def test_verify_tampered_runtime_file_fails(tmp_path):
    *_, package, _, result = do_build(tmp_path)
    (package / "agent/runtime.py").write_text("tampered\n")
    assert verify(package, result[2]) == 1


def test_verify_unexpected_managed_file_fails(tmp_path):
    *_, package, _, result = do_build(tmp_path)
    (package / "agent/extra.py").write_text("bad\n")
    assert verify(package, result[2]) == 1


def test_verify_ignores_unrelated_historical_git_metadata(tmp_path):
    *_, package, _, result = do_build(tmp_path)
    (package / ".git").mkdir()
    (package / ".git/HEAD").write_text("unrelated")
    assert verify(package, result[2]) == 0


def test_verify_exact_release_passes(tmp_path, capsys):
    *_, package, _, result = do_build(tmp_path)
    assert verify(package, result[2]) == 0
    assert "SD_1=PASS identity_mode=release_manifest" in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["missing", "symlink", "root_guarded"])
def test_verify_rejects_incomplete_or_unsafe_deployment(tmp_path, mutation):
    *_, package, _, result = do_build(tmp_path)
    target = package / "agent/runtime.py"
    if mutation == "missing":
        target.unlink()
    elif mutation == "symlink":
        target.unlink(); target.symlink_to(package / "run.sh")
    else:
        (package / "sitecustomize.py").write_text("bad\n")
    assert verify(package, result[2]) == 1
