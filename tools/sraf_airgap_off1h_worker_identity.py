"""OFF-1H: bounded, local Schedule/Handoff process-identity observations only.

No network, SQL calls, PID discovery, signals, worker mutation, lease
operations or user-controlled paths. Reuse the deployment E2E authority's
existing worker identity verifier for genuine /proc consistency checks.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

from operator_e2e.requirement_e2e_support import verify_worker_identity
from tools.sraf_airgap_off1_probes import Observation


IDENTITY_FILES = {
    "schedule": ".run_sra_api_schedule.identity",
    "handoff": ".run_sra_api_handoff.identity",
}
MAX_IDENTITY_BYTES = 256
MAX_PID = 4_194_304


def _result(status: str, reason: str, *, executed: bool,
            verified: int = 0) -> Observation:
    return Observation(
        "WORKER-01", "worker-identities",
        "schedule_handoff_process_identity_only",
        status, reason, executed, {"verified_role_count": verified},
    )


def probe_worker_process_identities(project_root: Path) -> Observation:
    """Check two exact launcher-managed identities, not worker readiness.

    PASS only if the canonical verifier confirms each recorded PID,
    process start time, process effective UID, deployment working directory,
    and role-specific requirement_scheduler.cli command. Zero trust in
    unchecked PID files, other launchers, or current shell metadata.
    """
    if sys.platform != "linux" or not isinstance(project_root, Path):
        return _result("SKIP", "worker_process_host_unsupported",
                       executed=False)
    try:
        if not project_root.is_dir() or project_root.is_symlink():
            return _result("SKIP", "worker_process_host_unsupported",
                           executed=False)
        real_root = project_root.resolve(strict=True)
    except OSError:
        return _result("SKIP", "worker_process_host_unsupported",
                       executed=False)

    seen_pids: set[int] = set()
    verified = 0
    for role in ("schedule", "handoff"):
        identity = real_root / IDENTITY_FILES[role]
        try:
            info = identity.lstat()
            if (not stat.S_ISREG(info.st_mode) or
                    stat.S_ISLNK(info.st_mode) or
                    info.st_size <= 0 or info.st_size > MAX_IDENTITY_BYTES or
                    info.st_uid != os.geteuid()):
                return _result("SKIP", "worker_process_identity_unverified",
                               executed=True, verified=verified)
            # This is the existing deployment-authoritative verifier; it
            # checks live /proc PID reuse, role-specific command, start time
            # and effective UID. Never expose its returned PID / start tick.
            observed = verify_worker_identity(identity, role, real_root)
            pid = observed.get("pid") if isinstance(observed, dict) else None
            start = observed.get("process_start_time") if isinstance(observed, dict) else None
            if (not isinstance(observed, dict) or observed.get("role") != role
                    or observed.get("alive") is not True
                    or type(pid) is not int or not 2 <= pid <= MAX_PID
                    or pid in seen_pids or not isinstance(start, str)
                    or not start.isdecimal() or len(start) > 24):
                return _result("SKIP", "worker_process_identity_unverified",
                               executed=True, verified=verified)
            seen_pids.add(pid)
            verified += 1
        except Exception:
            # Canonical helper reports HarnessFailure; no path, username,
            # command line, PID, native exception or log tail may escape.
            return _result("SKIP", "worker_process_identity_unverified",
                           executed=True, verified=verified)
    return _result("PASS", "worker_process_identities_verified",
                   executed=True, verified=2)
