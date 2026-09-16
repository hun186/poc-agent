"""Safe, read-only deployment-host evidence for remote Requirement acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from operator_e2e.requirement_e2e_support import output_root_fingerprint, verify_worker_identity
from operator_e2e.source_identity import inspect_operator_source
from shared.runtime_provenance import (
    RUNTIME_FILES,
    RUNTIME_PATHS,
    RUNTIME_ROOTS,
    is_runtime_provenance_path,
)

PROVENANCE_NAME = "REQUIREMENT_E2E_PROVENANCE.json"
_MANAGED_TOP_LEVEL = set(RUNTIME_ROOTS)


def _git(project_root: Path) -> dict:
    def run(*args: str) -> str:
        return subprocess.run(args, cwd=project_root, check=True, capture_output=True, text=True).stdout.strip()
    try:
        sha = run("git", "rev-parse", "HEAD")
        dirty = bool(run("git", "status", "--porcelain"))
        verified = len(sha) == 40
    except (OSError, subprocess.SubprocessError):
        sha, dirty, verified = None, None, False
    return {"identity_kind": "git_worktree", "git_sha": sha, "clean": dirty is False,
            "identity_verified": verified}


def _active_project_paths(project_root: Path) -> list[Path]:
    paths = []
    for module in tuple(sys.modules.values()):
        value = getattr(module, "__file__", None)
        if value:
            path = Path(value).resolve(strict=False)
            if (project_root.resolve() in path.parents or path.name in RUNTIME_FILES
                    or any(part in _MANAGED_TOP_LEVEL for part in path.parts)):
                paths.append(path)
    # The workers are positively bound to this entrypoint by verify_worker_identity.
    paths.append((project_root / "requirement_scheduler" / "cli.py").resolve(strict=False))
    return sorted(set(paths), key=str)


def collect_source_evidence(project_root: Path, *, active_paths: list[Path] | None = None) -> dict:
    """Verify bounded active/runtime-critical bytes; ignore inactive overlay residue."""
    project_root = project_root.resolve()
    provenance_path = project_root / PROVENANCE_NAME
    if not provenance_path.is_file():
        git = _git(project_root)
        if not git.get("identity_verified"):
            raise RuntimeError("deployment_source_identity_unavailable")
        if not (project_root / ".git").exists():
            return git
        try:
            return inspect_operator_source(project_root, git["git_sha"])
        except Exception as exc:
            raise RuntimeError(getattr(exc, "category", "deployment_source_identity_unavailable")) from exc
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if (set(provenance) != {"schema_version", "repository", "reviewed_runtime_sha", "runtime_files"}
                or provenance["schema_version"] != 1 or provenance["repository"] != "hun186/poc-agent"
                or not re.fullmatch(r"[0-9a-f]{40}", provenance["reviewed_runtime_sha"])):
            raise ValueError
        entries = provenance["runtime_files"]
        if not isinstance(entries, list) or len(entries) > 5000:
            raise ValueError
        expected = {}
        for entry in entries:
            if set(entry) != {"path", "sha256"} or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise ValueError
            if not is_runtime_provenance_path(entry["path"]):
                raise ValueError
            if entry["path"] in expected:
                raise ValueError
            expected[entry["path"]] = entry["sha256"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        raise RuntimeError("deployment_source_provenance_invalid") from exc

    for relative, digest in expected.items():
        path = project_root / relative
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RuntimeError("active_runtime_source_mismatch") from exc
        if actual != digest:
            raise RuntimeError("active_runtime_source_mismatch")

    active = active_paths if active_paths is not None else _active_project_paths(project_root)
    active_relative = []
    for path in active:
        resolved = Path(path).resolve(strict=False)
        try:
            relative = resolved.relative_to(project_root).as_posix()
        except ValueError as exc:
            if resolved.name in RUNTIME_FILES or any(part in _MANAGED_TOP_LEVEL for part in resolved.parts):
                raise RuntimeError("runtime_module_shadowing") from exc
            continue
        if relative.endswith((".pyc", ".pyo")):
            source = Path(relative.replace("/__pycache__/", "/")).with_name(Path(relative).name.split(".")[0] + ".py").as_posix()
            relative = source
        if relative not in expected:
            raise RuntimeError("unexpected_active_runtime_module")
        active_relative.append(relative)

    residual = 0
    for top in _MANAGED_TOP_LEVEL:
        root = project_root / top
        if root.is_dir():
            residual += sum(1 for path in root.rglob("*.py")
                            if "__pycache__" not in path.parts and path.relative_to(project_root).as_posix() not in expected)
    return {
        "identity_kind": "incremental_package", "identity_verified": True,
        "reviewed_runtime_sha": provenance["reviewed_runtime_sha"],
        "runtime_files": [{"path": path, "sha256": expected[path]} for path in sorted(expected)],
        "active_runtime_files": sorted(set(active_relative)),
        "inactive_residual_count": residual,
        "warnings": ["inactive_residual_files_present"] if residual else [],
    }


def collect_runtime_evidence(project_root: Path, artifact_root: Path) -> dict:
    workers = {}
    for role in ("schedule", "handoff"):
        try:
            verify_worker_identity(project_root / f".run_sra_api_{role}.identity", role, project_root)
            workers[role] = {"alive": True, "identity_verified": True}
        except Exception:
            workers[role] = {"alive": False, "identity_verified": False}
    return {
        "schema_version": "requirement_e2e_runtime_evidence_v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "deployment_source": collect_source_evidence(project_root),
        "workers": workers,
        "artifact_root_fingerprint": output_root_fingerprint(artifact_root),
    }


def configured_runtime_evidence(project_root: Path) -> dict:
    root = os.getenv("REQUIREMENT_HANDOFF_OUTPUT_ROOT", "").strip()
    if not root: raise RuntimeError("requirement_handoff_output_root_unavailable")
    return collect_runtime_evidence(project_root, Path(root))


class ArtifactEvidenceError(RuntimeError):
    pass


def configured_published_artifact(store, batch_run_id: str, run_item_id: str) -> bytes:
    """Return bytes only after durable identity, root, DOCX, and digest validation."""
    root_value = os.getenv("REQUIREMENT_HANDOFF_OUTPUT_ROOT", "").strip()
    if not root_value:
        raise ArtifactEvidenceError("requirement_handoff_output_root_unavailable")
    try:
        evidence = store.get_operator_artifact_evidence(
            batch_run_id=batch_run_id, run_item_id=run_item_id,
        )
    except KeyError as exc:
        raise ArtifactEvidenceError("artifact_missing") from exc

    if (evidence.get("selection_status") != "selected" or not evidence.get("remote_job_id")
            or not evidence.get("artifact_relative_path")
            or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("artifact_sha256") or ""))):
        raise ArtifactEvidenceError("artifact_metadata_missing")

    root = Path(root_value).expanduser().resolve(strict=False)
    if output_root_fingerprint(root) != evidence.get("phase1a_output_root_fingerprint"):
        raise ArtifactEvidenceError("artifact_root_fingerprint_mismatch")
    relative = PurePosixPath(evidence["artifact_relative_path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".docx":
        raise ArtifactEvidenceError("artifact_invalid")
    unresolved = root / Path(*relative.parts)
    resolved = unresolved.resolve(strict=False)
    if root not in resolved.parents or unresolved.is_symlink() or not resolved.is_file():
        raise ArtifactEvidenceError("artifact_missing")
    try:
        data = resolved.read_bytes()
        with zipfile.ZipFile(BytesIO(data)) as package:
            names = package.namelist()
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError
            if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names):
                raise ValueError
            if package.testzip() is not None:
                raise ValueError
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ArtifactEvidenceError("artifact_invalid") from exc
    if hashlib.sha256(data).hexdigest() != evidence["artifact_sha256"]:
        raise ArtifactEvidenceError("artifact_sha256_mismatch")
    return data
