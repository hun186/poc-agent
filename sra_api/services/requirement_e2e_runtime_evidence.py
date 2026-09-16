"""Safe, read-only deployment-host evidence for remote Requirement acceptance."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

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
