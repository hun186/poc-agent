"""Read-only per-role diagnostics for launcher-managed SRAF Workers.

Run: python -m tools.sraf_worker_identity_detail_readonly

Only the canonical verifier can mark a role VERIFIED. When it rejects a
role, bounded local checks suggest a fixed, non-sensitive reason. These
secondary observations are advisory and cannot grant Worker identity.
No network, SQL, ES, signal, PID scanning, runtime mutations or file writes.
No PID, UID, path, command line, native exception or environment is printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from operator_e2e import requirement_e2e_support as authority


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROLES = ("schedule", "handoff")
IDENTITIES = {
    "schedule": ".run_sra_api_schedule.identity",
    "handoff": ".run_sra_api_handoff.identity",
}
_PID_RE = re.compile(r"[0-9]{1,7}\Z")
_START_RE = re.compile(r"[0-9]{1,24}\Z")
_MAX_PID = 4_194_304
_MAX_IDENTITY_BYTES = 256


def _suspected_reason(path: Path, role: str, root: Path) -> str:
    """Diagnose a canonical rejection without copying the trust decision.

    Process/file state may change between observations. Thus even a specific
    reason is only a suspect; no secondary check can upgrade to VERIFIED.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "identity_file_missing"
    except OSError:
        return "identity_file_inaccessible"
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid()
            or not 0 < info.st_size <= _MAX_IDENTITY_BYTES):
        return "identity_file_invalid"

    try:
        # Reuse the canonical bounded, O_NOFOLLOW, dirfd-anchored reader.
        record = authority._read_worker_identity_nofollow(path)
    except (OSError, ValueError, UnicodeError):
        return "identity_record_unreadable_or_invalid"

    if (set(record) != {"role", "pid", "process_start_time"}
            or record.get("role") != role
            or _PID_RE.fullmatch(record.get("pid", "")) is None
            or _START_RE.fullmatch(record.get("process_start_time", "")) is None):
        return "identity_record_mismatch"
    pid = int(record["pid"])
    if not 2 <= pid <= _MAX_PID:
        return "identity_record_mismatch"

    try:
        started = authority._proc_start_time(pid)
    except FileNotFoundError:
        return "recorded_process_missing"
    except (OSError, ValueError, IndexError):
        return "recorded_process_unreadable"
    if started != record["process_start_time"]:
        return "process_start_time_mismatch"

    try:
        if authority._proc_uid(pid) != os.geteuid():
            return "process_effective_uid_mismatch"
        if authority._proc_cwd(pid) != root:
            return "process_workdir_mismatch"
        if not authority._worker_argv_matches(pid, role):
            return "process_command_role_mismatch"
        if authority._proc_start_time(pid) != record["process_start_time"]:
            return "process_changed_during_check"
    except FileNotFoundError:
        return "recorded_process_missing"
    except (OSError, ValueError, StopIteration, UnicodeError, IndexError):
        return "recorded_process_unreadable"

    # E.g. inode replacement, a race, or another authoritative guard.
    return "canonical_identity_unverified"


def inspect_workers(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Check BOTH roles even if the first fails, without modifying the host."""
    result: dict[str, Any] = {
        "mode": "READ_ONLY_LOCAL_NO_NETWORK",
        "authority": "canonical_worker_identity",
        "overall_status": "INCOMPLETE",
        "verified_role_count": 0,
        "roles": {},
    }
    if sys.platform != "linux" or not isinstance(root, Path):
        for role in ROLES:
            result["roles"][role] = {
                "status": "UNVERIFIED", "reason": "unsupported_host",
            }
        return result
    try:
        if not root.is_dir() or root.is_symlink():
            raise ValueError("root_invalid")
        real_root = root.resolve(strict=True)
    except (OSError, ValueError):
        for role in ROLES:
            result["roles"][role] = {
                "status": "UNVERIFIED", "reason": "project_root_unavailable",
            }
        return result

    seen_pids: set[int] = set()
    for role in ROLES:
        path = real_root / IDENTITIES[role]
        try:
            observed = authority.verify_worker_identity(path, role, real_root)
            pid = observed.get("pid") if isinstance(observed, dict) else None
            tick = observed.get("process_start_time") if isinstance(observed, dict) else None
            valid = (isinstance(observed, dict)
                     and observed.get("alive") is True
                     and observed.get("role") == role
                     and type(pid) is int and 2 <= pid <= _MAX_PID
                     and isinstance(tick, str)
                     and _START_RE.fullmatch(tick) is not None)
            if not valid:
                reason = "canonical_result_invalid"
            elif pid in seen_pids:
                reason = "verified_roles_share_pid"
            else:
                seen_pids.add(pid)
                result["roles"][role] = {
                    "status": "VERIFIED", "reason": "canonical_verified",
                }
                result["verified_role_count"] += 1
                continue
        except Exception:
            try:
                reason = _suspected_reason(path, role, real_root)
            except Exception:
                reason = "secondary_diagnosis_unavailable"
        result["roles"][role] = {"status": "UNVERIFIED", "reason": reason}

    if result["verified_role_count"] == len(ROLES):
        result["overall_status"] = "PASS"
    return result


def main() -> int:
    report = inspect_workers()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
