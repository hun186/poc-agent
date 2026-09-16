"""Fail-closed, repository-role based source classification for the operator harness."""
from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from operator_e2e.requirement_e2e_support import ExitCode, HarnessFailure


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=check, capture_output=True, text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HarnessFailure("operator_source_identity_unavailable", stage="CONFIG_PREFLIGHT",
                             exit_code=ExitCode.PREFLIGHT) from exc


def _non_runtime_document(path: str) -> bool:
    value = PurePosixPath(path)
    if value.parts and value.parts[0] == ".codex":
        return True
    # These trees are never imported or used as runtime templates/configuration.
    return bool(value.parts and value.parts[0] == "docs" and value.suffix.lower() == ".md")


def _generated_output(path: str) -> bool:
    value = PurePosixPath(path)
    parts = value.parts
    if len(parts) >= 2 and parts[0] == "operator_e2e" and parts[1] == "output":
        return True
    if len(parts) >= 2 and parts[0] in {"tests", "tests_code"} and "output" in parts[1:]:
        return True
    # Operator-root DOCX files are harness products, never runtime templates.
    return len(parts) == 2 and parts[0] == "operator_e2e" and value.suffix.lower() == ".docx"


def is_non_runtime_path(path: str, *, dirty: bool = False) -> bool:
    return _non_runtime_document(path) or (dirty and _generated_output(path))


def _dirty_paths(root: Path) -> list[str]:
    raw = _run(root, "status", "--porcelain=v1", "-z").stdout
    records = raw.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records) and records[index]:
        record = records[index]
        paths.append(record[3:])
        if record[:2].strip()[:1] in {"R", "C"}:
            index += 1
            if index < len(records) and records[index]:
                paths.append(records[index])
        index += 1
    return sorted(set(paths))


def inspect_operator_source(root: Path, reviewed_sha: str) -> dict:
    """Prove exact identity or a descendant containing only non-runtime commits."""
    root = Path(root)
    operator_sha = _run(root, "rev-parse", "--verify", "HEAD").stdout.strip()
    if operator_sha != reviewed_sha:
        ancestor = _run(root, "merge-base", "--is-ancestor", reviewed_sha, operator_sha, check=False)
        if ancestor.returncode != 0:
            category = "operator_source_not_reviewed_descendant" if ancestor.returncode == 1 else "operator_source_identity_unavailable"
            raise HarnessFailure(category, stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
        changed = sorted(filter(None, _run(root, "diff", "--name-only", f"{reviewed_sha}..{operator_sha}").stdout.splitlines()))
        runtime = [path for path in changed if not is_non_runtime_path(path)]
        if runtime:
            raise HarnessFailure("operator_runtime_source_changed_since_review", stage="CONFIG_PREFLIGHT",
                                 exit_code=ExitCode.PREFLIGHT)
        status, warnings = "reviewed_equivalent_descendant", ["newer_non_runtime_commits"]
    else:
        changed, runtime, status, warnings = [], [], "exact", []

    dirty = _dirty_paths(root)
    runtime_dirty = [path for path in dirty if not is_non_runtime_path(path, dirty=True)]
    non_runtime_dirty = [path for path in dirty if path not in runtime_dirty]
    if runtime_dirty:
        raise HarnessFailure("operator_runtime_dirty", stage="CONFIG_PREFLIGHT", exit_code=ExitCode.PREFLIGHT)
    if non_runtime_dirty:
        warnings.append("non_runtime_dirty_files")
    return {
        "repository": "hun186/poc-agent", "identity_kind": "git_worktree",
        "identity_verified": True, "identity_status": status,
        "reviewed_sha": reviewed_sha, "operator_sha": operator_sha, "git_sha": operator_sha,
        "runtime_relevant_committed_changes": runtime,
        "non_runtime_committed_changes": changed,
        "runtime_relevant_dirty_changes": runtime_dirty,
        "non_runtime_dirty_changes": non_runtime_dirty,
        "warnings": warnings,
    }
