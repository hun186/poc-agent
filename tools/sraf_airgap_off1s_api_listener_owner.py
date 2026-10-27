"""OFF-1S: observe SRAF launcher API identity and its actual Linux TCP listener.

Read-only, operator-only local process evidence. This is not authentication,
cryptographic service provenance, exclusive socket ownership or isolation.
On supported launcher, identity file is written by run_sra_api.sh with 0600.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import socket
import stat
import sys

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1p_docx_integrity import _pin_root_directory
from tools.sraf_airgap_off1q_remote_report_job import _port

PROC = Path("/proc")
IDENTITY = ".run_sra_api_api.identity"
MAX_IDENTITY_BYTES = 256
MAX_PROC_BYTES = 1024 * 1024
MAX_CMD_BYTES = 4096
MAX_FDS = 4096
MAX_PID = 4_194_304


def _read(path: Path, limit: int) -> bytes | None:
    try:
        with path.open("rb") as file:
            data = file.read(limit + 1)
        return data if 0 < len(data) <= limit else None
    except (OSError, ValueError):
        return None


def _record(root: Path, port: int) -> tuple[int, str] | None:
    fd = file_fd = None
    try:
        # Pin each absolute root ancestor; identity file cannot be a symlink.
        fd = _pin_root_directory(root)
        file_fd = os.open(IDENTITY,
                          os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                          os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(file_fd)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or not 0 < info.st_size <= MAX_IDENTITY_BYTES):
            return None
        data = os.read(file_fd, MAX_IDENTITY_BYTES + 1)
        if len(data) != info.st_size:
            return None
        lines = data.decode("ascii").splitlines()
        if len(lines) != 3 or any(line.count("=") != 1 for line in lines):
            return None
        values = dict(line.split("=", 1) for line in lines)
        if set(values) != {"api_pid", "api_start_time", "port"}:
            return None
        pid_text, start, p = (values["api_pid"], values["api_start_time"],
                              values["port"])
        if (re.fullmatch(r"[1-9][0-9]{0,6}", pid_text) is None
                or re.fullmatch(r"[0-9]{1,24}", start) is None
                or p != str(port)):
            return None
        pid = int(pid_text)
        if not 2 <= pid <= MAX_PID:
            return None
        return pid, start
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        for f in (file_fd, fd):
            if f is not None:
                try:
                    os.close(f)
                except OSError:
                    pass


def _process(root: Path, pid: int, start: str, port: int) -> bool:
    proc = PROC / str(pid)
    raw_stat = _read(proc / "stat", 4096)
    raw_status = _read(proc / "status", 16384)
    raw_cmd = _read(proc / "cmdline", MAX_CMD_BYTES)
    if not all((raw_stat, raw_status, raw_cmd)):
        return False
    try:
        # /proc/[pid]/stat field 2 is parenthesized and may contain spaces.
        after = raw_stat[raw_stat.rfind(b")") + 2:].split()
        if (len(after) < 20 or after[0] == b"Z"
                or after[19].decode("ascii") != start):
            return False
        uid_line = next(x for x in raw_status.splitlines()
                        if x.startswith(b"Uid:"))
        uid_values = uid_line.split()[1:]
        if len(uid_values) != 4 or int(uid_values[1]) != os.geteuid():
            return False
        cwd = os.readlink(proc / "cwd")
        exe = os.readlink(proc / "exe")
        if Path(cwd) != root or not Path(exe).name.startswith("python"):
            return False
        argv = [os.fsdecode(a) for a in raw_cmd.rstrip(b"\0").split(b"\0")]
        # Exactly the invocation used by run_sra_api.sh. A generic process
        # merely including "uvicorn" in a long command is not accepted.
        if len(argv) < 7 or Path(argv[1]).name != "uvicorn":
            return False
        if argv[2:] != ["api.main:app", "--host", "0.0.0.0",
                         "--port", str(port)]:
            return False
        return True
    except (OSError, ValueError, UnicodeError, StopIteration):
        return False


def _listener_inode(port: int) -> str | None:
    """Only one IPv4 LISTEN inode serving localhost; reject IPv6 ambiguity."""
    data = _read(PROC / "net/tcp", MAX_PROC_BYTES)
    other = _read(PROC / "net/tcp6", MAX_PROC_BYTES)
    if data is None or other is None:
        return None
    target = f"{port:04X}"
    seen: set[str] = set()
    try:
        for line in other.decode("ascii").splitlines()[1:]:
            cols = line.split()
            if (len(cols) >= 10 and cols[3] == "0A"
                    and cols[1].rsplit(":", 1)[-1].upper() == target):
                return None
        for line in data.decode("ascii").splitlines()[1:]:
            cols = line.split()
            if len(cols) < 10 or cols[3] != "0A":
                continue
            local = cols[1].upper()
            if local in (f"0100007F:{target}", f"00000000:{target}"):
                if not cols[9].isdecimal() or cols[9] == "0":
                    return None
                seen.add(cols[9])
    except (UnicodeError, IndexError):
        return None
    return next(iter(seen)) if len(seen) == 1 else None


def _owns_socket(pid: int, inode: str) -> bool:
    try:
        with os.scandir(PROC / str(pid) / "fd") as entries:
            matched = False
            count = 0
            for entry in entries:
                count += 1
                if count > MAX_FDS:
                    return False
                if not entry.name.isdecimal():
                    continue
                try:
                    if os.readlink(entry.path) == f"socket:[{inode}]":
                        matched = True
                except OSError:
                    continue
            return matched
    except OSError:
        return False


def verified_listener_binding(root: Path, port_value: str | None
                             ) -> tuple[int, str, str] | None:
    """Return private PID/start/inode binding only if two snapshots agree."""
    if sys.platform != "linux" or not isinstance(root, Path):
        return None
    port = _port(port_value)
    if port is None:
        return None
    try:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            return None
        # Caller-supplied root must be its canonical live deployment path.
        if root.resolve(strict=True) != root:
            return None
        first = _record(root, port)
        if first is None:
            return None
        pid, start = first
        if not _process(root, pid, start, port):
            return None
        inode = _listener_inode(port)
        if inode is None or not _owns_socket(pid, inode):
            return None
        # Detect PID reuse, launcher restarts and listener replacement
        # between reads, while acknowledging the remaining TOCTOU window.
        if (_record(root, port) != first
                or not _process(root, pid, start, port)
                or _listener_inode(port) != inode
                or not _owns_socket(pid, inode)):
            return None
        return pid, start, inode
    except (OSError, ValueError):
        return None


def probe_api_listener_owner(root: Path, port_value: str | None) -> Observation:
    verified = verified_listener_binding(root, port_value) is not None
    return Observation(
        "API-OWNER-01", "sraf-api-listener-owner",
        "launcher_record_process_and_tcp_socket_partial_only",
        "PASS" if verified else "SKIP",
        "api_owner_observed" if verified else "api_owner_unverified",
        True, {"api_listener_owner_observed": verified},
    )
