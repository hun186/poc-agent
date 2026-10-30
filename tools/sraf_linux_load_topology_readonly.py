#!/usr/bin/env python3
"""Read-only Linux SRAF operator sampling under existing workload.

Does NOT contact HTTP, Ollama, ES, SQL, or external network. Does not create a
lock, invoke preflight, start workers, modify data or generate load. Reuses the
the OFF-1S launcher/PID/cwd/socket *correlation* checks but deliberately
does NOT run its global exclusive-socket-owner FD scan. This weaker proof is
permitted ONLY for anonymous local read-only sampling, NEVER for bearer calls.
It then samples bounded /proc metrics.
No shared-lock, multi-worker, FULL_LIVE or physical-airgap claim is possible.

Usage on the already-running installed Linux host:
  python tools/sraf_linux_load_topology_readonly.py --project-root "$PWD" --api-port 9002
  python tools/sraf_linux_load_topology_readonly.py --project-root "$PWD" --api-port 9002 --samples 3 --interval 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off1s_api_listener import (  # noqa: E402
    ListenerProof, _identity, _same_process, _listener_inode, _owns_socket,
    _start_tick, _bounded,
)
from tools.sraf_airgap_off1p_docx_integrity import _pin_root_directory  # noqa: E402
from tools.sraf_runtime_baseline_readonly import _valid_port  # noqa: E402

SCHEMA = "sraf_linux_load_topology_readonly_v1"
MODE = "PARTIAL_ONLY_NOT_ACCEPTANCE"
MAX_PROC_BYTES = 16 * 1024
MAX_TICKS = 10**20
MAX_RSS_KIB = 10**10
MAX_THREADS = 131072


def _row(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def attest_local_sampling_process(project_root: Path, api_port: str) -> ListenerProof | None:
    """Correlate a launcher-owned PID to a live listener for /proc sampling ONLY.

    This is intentionally *not* OFF-1S's security-grade exclusive-owner
    attestation. Running its global process/thread/FD scan under container
    load can hit MAX_GLOBAL_FDS even when the actual API PID is healthy.
    No token-bearing endpoint may use this proof. It establishes only that
    the launcher-recorded API PID, start tick, cwd and UID match AND it
    currently holds the expected unique listening socket. Another process
    may share it; that's an explicitly NOT_TESTED fact.
    """
    port = _valid_port(api_port)
    if sys.platform != "linux" or port is None or not project_root.is_absolute():
        return None
    fd = None
    try:
        fd = _pin_root_directory(project_root)
        root_stat = os.fstat(fd)
        selected = _identity(fd, port)
        if selected is None:
            return None
        pid, tick = selected
        if not _same_process(pid, tick, root_stat, port):
            return None
        inode = _listener_inode(port)
        if inode is None or not _owns_socket(pid, inode):
            return None
        # Recheck both authorities before accepting a private /proc sample.
        if (_identity(fd, port) != selected or
                not _same_process(pid, tick, root_stat, port) or
                _listener_inode(port) != inode or
                not _owns_socket(pid, inode)):
            return None
        return ListenerProof(pid, tick, port, inode)
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _sample(pid: int, start_tick: str) -> dict[str, int] | None:
    """Read only bounded numeric /proc status and CPU ticks for a verified PID."""
    if _start_tick(pid) != start_tick:
        return None
    status = _bounded(Path(f"/proc/{pid}/status"), MAX_PROC_BYTES)
    process = _bounded(Path(f"/proc/{pid}/stat"), MAX_PROC_BYTES)
    if status is None or process is None:
        return None
    try:
        metrics: dict[bytes, int] = {}
        for line in status.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == b"VmRSS:" and parts[2] == b"kB":
                if re.fullmatch(rb"[0-9]{1,12}", parts[1]) is None:
                    return None
                metrics[b"rss"] = int(parts[1])
            elif len(parts) == 2 and parts[0] == b"Threads:":
                if re.fullmatch(rb"[0-9]{1,6}", parts[1]) is None:
                    return None
                metrics[b"threads"] = int(parts[1])
        if set(metrics) != {b"rss", b"threads"}:
            return None
        end = process.rfind(b") ")
        if end < 0 or not process.startswith(str(pid).encode("ascii") + b" ("):
            return None
        fields = process[end + 2:].split()
        if len(fields) < 20 or fields[0] in (b"Z", b"X"):
            return None
        if (re.fullmatch(rb"[0-9]{1,20}", fields[11]) is None
                or re.fullmatch(rb"[0-9]{1,20}", fields[12]) is None
                or fields[19].decode("ascii") != start_tick):
            return None
        ticks = int(fields[11]) + int(fields[12])
        if (not 0 < metrics[b"rss"] <= MAX_RSS_KIB
                or not 1 <= metrics[b"threads"] <= MAX_THREADS
                or ticks > MAX_TICKS):
            return None
        if _start_tick(pid) != start_tick:
            return None
        return {"rss_kib": metrics[b"rss"], "threads": metrics[b"threads"], "cpu_ticks": ticks}
    except (OSError, ValueError, UnicodeError, IndexError):
        return None


def _same_mount_namespace(pid: int) -> bool | None:
    """Compare *one* verified API process with this operator, not all workers."""
    try:
        a = os.stat("/proc/self/ns/mnt")
        b = os.stat(f"/proc/{pid}/ns/mnt")
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    except OSError:
        return None


def _local_lock_candidate(project_root: Path) -> Path:
    # Never use tempfile.gettempdir(): Python may create and delete test files
    # while selecting a writable directory. This is an untrusted *candidate*
    # only; the real API process may resolve a different TMPDIR.
    temp = (os.environ.get("TMPDIR") or os.environ.get("TEMP")
            or os.environ.get("TMP") or "/tmp")
    tag = hashlib.sha256(os.fsencode(str(project_root.resolve()))).hexdigest()[:24]
    return Path(temp) / f"sraf-operator-e2e-{os.getuid()}-{tag}"


def _local_lock_observation(project_root: Path) -> dict[str, str]:
    """No O_CREAT / mkdir / flock / epoch read; only no-follow fd metadata."""
    if sys.platform != "linux":
        return _row("SKIP", "linux_only")
    parent = _local_lock_candidate(project_root)
    dirfd = filefd = None
    try:
        dirfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(dirfd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            return _row("SKIP", "local_lock_candidate_untrusted")
        filefd = os.open("preflight.lock", os.O_RDONLY | os.O_NOFOLLOW |
                         os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dirfd)
        info = os.fstat(filefd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            return _row("SKIP", "local_lock_candidate_untrusted")
        return _row("OBSERVED", "local_lock_candidate_metadata_verified")
    except FileNotFoundError:
        return _row("SKIP", "local_lock_candidate_missing")
    except OSError:
        return _row("SKIP", "local_lock_candidate_unverified")
    finally:
        if filefd is not None:
            os.close(filefd)
        if dirfd is not None:
            os.close(dirfd)


def observe(project_root: Path, api_port: str, *,
            samples: int = 2, interval: float = 1.0) -> dict[str, object]:
    checks = {
        "API-LISTENER": _row("SKIP", "listener_identity_unverified"),
        "SOCKET-EXCLUSIVITY": _row("NOT_TESTED", "global_fd_scan_intentionally_not_run"),
        "API-MOUNT-NAMESPACE": _row("SKIP", "mount_namespace_unverified"),
        "LOCAL-LOCK-CANDIDATE": _row("SKIP", "local_lock_candidate_unverified"),
        "API-PROCESS-SAMPLES": _row("SKIP", "process_sampling_unverified"),
        "CROSS-WORKER-LOCK-SHARING": _row("NOT_TESTED", "cannot_prove_from_external_snapshot"),
        "OLLAMA-ES-TIMEOUT": _row("NOT_TESTED", "no_model_or_es_request"),
    }
    result: dict[str, object] = {
        "schema": SCHEMA, "mode": MODE, "feature_acceptance": "NOT_TESTED",
        "overall": "INCOMPLETE", "checks": checks, "samples": [],
        "network_requests": 0, "credentials_sent": False, "database_queries": 0,
        "model_inferences": 0, "mutations": 0, "processes_spawned": 0,
    }
    try:
        valid = (sys.platform == "linux" and isinstance(project_root, Path)
                 and project_root.is_absolute() and project_root.is_dir()
                 and not project_root.is_symlink()
                 and project_root.resolve() == PROJECT_ROOT
                 and _valid_port(api_port) is not None
                 and isinstance(samples, int) and 2 <= samples <= 5
                 and isinstance(interval, (int, float)) and 0 <= interval <= 20)
    except (OSError, ValueError):
        valid = False
    if not valid:
        return result

    checks["LOCAL-LOCK-CANDIDATE"] = _local_lock_observation(project_root)
    try:
        initial = attest_local_sampling_process(project_root, api_port)
    except Exception:
        initial = None
    if initial is None:
        return result
    checks["API-LISTENER"] = _row("OBSERVED", "launcher_listener_for_local_sampling_only")
    namespace = _same_mount_namespace(initial.pid)
    if namespace is True:
        checks["API-MOUNT-NAMESPACE"] = _row("OBSERVED", "same_namespace_as_operator_only")
    elif namespace is False:
        checks["API-MOUNT-NAMESPACE"] = _row("SKIP", "different_mount_namespace")
    measurements = []
    for index in range(samples):
        reading = _sample(initial.pid, initial.start_tick)
        if reading is None:
            checks["API-PROCESS-SAMPLES"] = _row("SKIP", "process_sample_unverified")
            measurements = []
            break
        # Never expose PID, inode, path, environment or raw /proc bytes.
        measurements.append({"sample": index + 1,
                             "rss_mib": round(reading["rss_kib"] / 1024, 1),
                             "threads": reading["threads"]})
        if index + 1 < samples:
            time.sleep(interval)
    try:
        stable = attest_local_sampling_process(project_root, api_port) == initial
    except Exception:
        stable = False
    if not stable:
        checks["API-LISTENER"] = _row("SKIP", "listener_identity_changed")
        checks["API-PROCESS-SAMPLES"] = _row("SKIP", "listener_identity_changed")
        return result

    if len(measurements) == samples:
        checks["API-PROCESS-SAMPLES"] = _row("OBSERVED", "process_samples_collected")
        result["samples"] = measurements
        # CPU ticks are a delta only, never an Ollama utilization inference.
        # We intentionally omit raw PID and CPU ticks from the public result.
    result["overall"] = (
        "PARTIAL_OBSERVATION"
        if (checks["API-LISTENER"]["status"] == "OBSERVED"
            and checks["API-PROCESS-SAMPLES"]["status"] == "OBSERVED")
        else "INCOMPLETE"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute deployed repository root; never printed")
    parser.add_argument("--api-port", required=True,
                        help="Numeric listener port; never printed")
    parser.add_argument("--samples", type=int, choices=range(2, 6), default=2)
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between samples [0, 20]; no generated load")
    args = parser.parse_args(argv)
    data = observe(args.project_root, args.api_port,
                   samples=args.samples, interval=args.interval)
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if data["overall"] == "PARTIAL_OBSERVATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
