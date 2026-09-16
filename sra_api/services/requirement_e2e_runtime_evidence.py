"""Safe, read-only deployment-host evidence for remote Requirement acceptance."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath

from operator_e2e.requirement_e2e_support import output_root_fingerprint, verify_worker_identity


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
        "deployment_source": _git(project_root),
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
