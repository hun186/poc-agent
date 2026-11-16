"""Fail-closed, passive SRAF Worker STARTING observation.

Used only by layered operator diagnostics. A missing Worker identity alone is
never a startup claim: require the current launcher identity, a recent /proc
birth time, exact Bash invocation, UID, cwd and a bounded identity record.
No signals, process enumeration, network, credentials, runtime writes or leases.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Callable

from tools.sraf_airgap_off1_identity_primitives import _pin_root_directory

LAUNCHER_RECORD = ".run_sra_api_launcher.identity"
MAX_LAUNCHER_AGE_SECONDS = 120
RETRIES = 6
POLL_SECONDS = 2
MAX_READ = 4096
_MAX_PID = 4_194_304
_DECIMAL = re.compile(r"[0-9]{1,24}\Z")


def _read_limited(path: Path, limit: int = MAX_READ) -> bytes:
    with path.open("rb") as stream:
        return stream.read(limit + 1)


def _proc_start(pid: int) -> str:
    data = _read_limited(Path(f"/proc/{pid}/stat"))
    if not data or len(data) > MAX_READ or not data.startswith(f"{pid} (".encode()):
        raise ValueError("process_record_invalid")
    end = data.rfind(b") ")
    if end == -1:
        raise ValueError("process_record_invalid")
    fields = data[end + 2:].split()
    if len(fields) < 20:
        raise ValueError("process_record_invalid")
    tick = fields[19].decode("ascii")
    if _DECIMAL.fullmatch(tick) is None:
        raise ValueError("process_record_invalid")
    return tick


def _proc_executable(pid: int) -> str:
    return Path(f"/proc/{pid}/exe").resolve(strict=True).name


def _proc_cwd_stat(pid: int) -> os.stat_result:
    return os.stat(f"/proc/{pid}/cwd")


def recent_verified_launcher(root: Path) -> bool:
    """Proof of a *recent launcher process*, not proof of Worker readiness.

    Return false whenever proof is missing/ambiguous; do not trust bare file
    existence or a spoofed command-line substring as sufficient evidence.
    """
    if sys.platform != "linux" or not isinstance(root, Path):
        return False
    root_fd = None
    record_fd = None
    try:
        if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root:
            return False
        root_fd = _pin_root_directory(root)
        root_stat = os.fstat(root_fd)
        record_fd = os.open(
            LAUNCHER_RECORD, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        info = os.fstat(record_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= 512):
            return False
        data = os.read(record_fd, 513)
        if not data.endswith(b"\n") or len(data) > 512:
            return False
        lines = data.decode("ascii").splitlines()
        if len(lines) != 5 or any("=" not in line for line in lines):
            return False
        values = dict(line.split("=", 1) for line in lines)
        if (len(values) != 5 or set(values) != {
                "pid", "process_start_time", "effective_uid", "cwd", "launcher_path"}):
            return False
        if (not re.fullmatch(r"[0-9]{1,7}", values["pid"])
                or _DECIMAL.fullmatch(values["process_start_time"]) is None
                or values["effective_uid"] != str(os.geteuid())
                or values["cwd"] != str(root)
                or values["launcher_path"] != str(root / "run_sra_api.sh")):
            return False
        pid = int(values["pid"])
        if not 2 <= pid <= _MAX_PID:
            return False

        started = _proc_start(pid)
        if started != values["process_start_time"]:
            return False
        proc_status = _read_limited(Path(f"/proc/{pid}/status"))
        if len(proc_status) > MAX_READ:
            return False
        uids = [line.split() for line in proc_status.splitlines() if line.startswith(b"Uid:")]
        if len(uids) != 1 or len(uids[0]) < 3 or int(uids[0][2]) != os.geteuid():
            return False
        proc_cwd = _proc_cwd_stat(pid)
        if (proc_cwd.st_dev, proc_cwd.st_ino) != (root_stat.st_dev, root_stat.st_ino):
            return False
        if _proc_executable(pid) != "bash":
            return False
        raw = _read_limited(Path(f"/proc/{pid}/cmdline"))
        if not raw or len(raw) > MAX_READ or not raw.endswith(b"\0"):
            return False
        argv = [arg.decode("utf-8") for arg in raw[:-1].split(b"\0")]
        if (len(argv) != 2 or Path(argv[0]).name != "bash"
                or (root / argv[1]).resolve(strict=True) != root / "run_sra_api.sh"):
            return False
        uptime_raw = _read_limited(Path("/proc/uptime"), 128)
        uptime = float(uptime_raw.split()[0])
        hz = os.sysconf("SC_CLK_TCK")
        age = uptime - int(started) / hz
        if not (-1 <= age <= MAX_LAUNCHER_AGE_SECONDS):
            return False
        return _proc_start(pid) == started
    except (OSError, ValueError, UnicodeError, IndexError, KeyError,
            OverflowError, ZeroDivisionError):
        return False
    finally:
        if record_fd is not None:
            os.close(record_fd)
        if root_fd is not None:
            os.close(root_fd)


def confirmed_starting(root: Path) -> bool:
    """Only missing records + verified surviving roles + young launcher qualify."""
    if not recent_verified_launcher(root):
        return False
    try:
        from tools.sraf_worker_identity_detail_readonly import inspect_workers
        observed = inspect_workers(root)
        roles = observed["roles"]
        statuses = tuple((roles[role]["status"], roles[role]["reason"])
                         for role in ("schedule", "handoff"))
        missing = ("UNVERIFIED", "identity_file_missing")
        verified = ("VERIFIED", "canonical_verified")
        return missing in statuses and all(value in (missing, verified) for value in statuses)
    except (KeyError, TypeError, ValueError, OSError):
        return False


def retry_worker_row(root: Path, initial: dict[str, object],
                     probe_worker: Callable[[Path], dict[str, object]],
                     *, sleep: Callable[[float], None] = time.sleep) -> dict[str, object]:
    """Bounded retry with no success promotion except via canonical recheck.

    Only the explicit startup gate allows a delay. STARTING is historical
    metadata, never a PASS state; after the finite window status must be
    PASS_PARTIAL from the existing verifier, or INCOMPLETE.
    """
    if (initial.get("status") != "INCOMPLETE"
            or initial.get("reason") != "worker_process_identity_unverified"
            or not confirmed_starting(root)):
        return initial
    def canonical_recheck() -> dict[str, object]:
        try:
            result = probe_worker(root)
        except Exception:
            return {}
        return result if isinstance(result, dict) else {}

    def is_verified(value: dict[str, object]) -> bool:
        return (
            value.get("id") == "worker_process_identity"
            and value.get("status") == "PASS_PARTIAL"
            and value.get("reason") == "recorded_schedule_handoff_process_identity_only"
            and type(value.get("verified_role_count")) is int
            and value["verified_role_count"] == 2
        )

    def recovered(value: dict[str, object], attempt: int) -> dict[str, object]:
        return {
            **value,
            "reason": "worker_process_identities_verified_after_startup_retry",
            "startup_phase": "STARTING",
            "startup_retry_result": "RECOVERED",
            "startup_retry_attempts": attempt,
        }

    for attempt in range(1, RETRIES + 1):
        sleep(POLL_SECONDS)
        current = canonical_recheck()
        if is_verified(current):
            return recovered(current, attempt)
        # If records have appeared or the launcher changed between the above
        # probe and this gate, STARTING is no longer justified. The two roles
        # may have JUST become ready, however: do one last authoritative
        # canonical verification rather than reporting stale INCOMPLETE.
        if not confirmed_starting(root):
            final = canonical_recheck()
            if is_verified(final):
                return recovered(final, attempt)
            return {
                **initial, "startup_phase": "STARTING",
                "startup_retry_result": "UNVERIFIED",
                "startup_retry_attempts": attempt,
            }
    return {
        **initial, "reason": "worker_startup_retry_exhausted",
        "startup_phase": "STARTING",
        "startup_retry_result": "INCOMPLETE",
        "startup_retry_attempts": RETRIES,
    }
