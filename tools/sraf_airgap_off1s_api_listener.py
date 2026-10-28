"""OFF-1S: attest launcher-owned Linux SRAF API TCP listening process.

This is a bounded operator-only process/socket identity check, not a TLS,
application, API response, Agent, or physical-airgap proof. The proof must be
rechecked immediately BEFORE the authenticated GET is sent on its socket,
and after reading the response. Socket-owner enumeration is bounded;
no signals, processes spawned, or credential reads.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import socket
import stat
import sys

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1p_docx_integrity import _pin_root_directory
from tools.sraf_airgap_off1q_remote_report_job import _port

IDENTITY_NAME = ".run_sra_api_api.identity"
MAX_PID = 4_194_304
MAX_IDENTITY = 256
MAX_PROC = 8192
MAX_CMD = 4096
MAX_TCP = 1024 * 1024
MAX_FDS = 4096


@dataclass(frozen=True)
class ListenerProof:
    pid: int
    start_tick: str
    port: int
    inode: str


def _bounded(path: Path, limit: int) -> bytes | None:
    try:
        with path.open("rb") as fd:
            data = fd.read(limit + 1)
        return data if 0 < len(data) <= limit else None
    except (OSError, ValueError):
        return None


def _identity(root_fd: int, port: int) -> tuple[int, str] | None:
    fd = None
    try:
        fd = os.open(IDENTITY_NAME,
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=root_fd)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or not 0 < info.st_size <= MAX_IDENTITY):
            return None
        raw = os.read(fd, MAX_IDENTITY + 1)
        if len(raw) != info.st_size or not raw.endswith(b"\n"):
            return None
        lines = raw.decode("ascii").splitlines()
        if len(lines) != 3:
            return None
        values = {}
        for line in lines:
            if line.count("=") != 1:
                return None
            key, value = line.split("=", 1)
            if key in values:
                return None
            values[key] = value
        if set(values) != {"api_pid", "api_start_time", "port"}:
            return None
        if (re.fullmatch(r"[0-9]{1,7}", values["api_pid"]) is None
                or re.fullmatch(r"[0-9]{1,24}", values["api_start_time"]) is None
                or values["port"] != str(port)):
            return None
        pid = int(values["api_pid"])
        if not 2 <= pid <= MAX_PID:
            return None
        return pid, values["api_start_time"]
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _start_tick(pid: int) -> str | None:
    raw = _bounded(Path(f"/proc/{pid}/stat"), MAX_PROC)
    if raw is None:
        return None
    # /proc/pid/comm is parenthesized and may contain blanks or ')'.
    end = raw.rfind(b") ")
    if end < 0 or not raw.startswith(str(pid).encode() + b" ("):
        return None
    fields = raw[end+2:].split()  # first is field 3 (state)
    if len(fields) < 20 or fields[0] in (b"Z", b"X"):
        return None
    tick = fields[19]  # field 22
    if re.fullmatch(rb"[0-9]{1,24}", tick) is None:
        return None
    return tick.decode("ascii")


def _same_process(pid: int, start_tick: str, root_stat: os.stat_result,
                  port: int) -> bool:
    if _start_tick(pid) != start_tick:
        return False
    try:
        cwd = os.stat(f"/proc/{pid}/cwd")
    except OSError:
        return False
    if (cwd.st_dev, cwd.st_ino) != (root_stat.st_dev, root_stat.st_ino):
        return False
    status = _bounded(Path(f"/proc/{pid}/status"), MAX_PROC)
    if status is None:
        return False
    uids = [line.split() for line in status.splitlines()
            if line.startswith(b"Uid:")]
    if (len(uids) != 1 or len(uids[0]) != 5
            or not uids[0][2].isdigit()
            or int(uids[0][2]) != os.geteuid()):
        return False
    command = _bounded(Path(f"/proc/{pid}/cmdline"), MAX_CMD)
    if command is None or not command.endswith(b"\0"):
        return False
    # setproctitle (called by sra_api/main.py) replaces argv memory with the
    # exact generated SRA-API title and NUL padding. It can conceal the
    # original uvicorn argv; corroborate it only with the launcher record,
    # effective UID, pinned cwd, PID start tick and exclusive socket owner.
    if command.startswith(b"SRA-API | "):
        try:
            raw_title, padding = command.split(b"\0", 1)
            title = raw_title.decode("utf-8")
            hostname = socket.gethostname()
        except (UnicodeError, ValueError):
            return False
        if any(padding):
            return False
        title_pattern = (
            rf"SRA-API \| port={port} \| "
            rf"(?:[A-Za-z0-9][A-Za-z0-9._+-]{{0,80}} \| )?"
            rf"pid={pid} \| {re.escape(hostname)}"
        )
        argv_ok = re.fullmatch(title_pattern, title) is not None
    else:
        try:
            argv = [os.fsdecode(a) for a in command[:-1].split(b"\0")]
        except UnicodeError:
            return False
        # run_sra_api.sh executes uvicorn as a console script. On Linux its
        # shebang commonly appears as: python3 /path/to/uvicorn <5 args>.
        # Preserve the original direct-executable case, without accepting
        # arbitrary python -m or a different application.
        if (len(argv) == 7
                and re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)?)?",
                                 Path(argv[0]).name) is not None
                and Path(argv[1]).is_absolute()
                and Path(argv[1]).name == "uvicorn"):
            argv = argv[1:]
        argv_ok = (len(argv) == 6
                   and Path(argv[0]).name == "uvicorn"
                   and argv[1:] == ["api.main:app", "--host", "0.0.0.0",
                                    "--port", str(port)])
    return argv_ok and _start_tick(pid) == start_tick


def _listener_inode(port: int) -> str | None:
    raw = _bounded(Path("/proc/net/tcp"), MAX_TCP)
    if raw is None:
        return None
    target = f"{port:04X}"
    found: set[str] = set()
    try:
        for line in raw.decode("ascii").splitlines()[1:]:
            columns = line.split()
            if len(columns) < 10 or columns[3] != "0A":
                continue
            address = columns[1].upper()
            if address in (f"0100007F:{target}", f"00000000:{target}"):
                if not columns[9].isdigit() or columns[9] == "0":
                    return None
                found.add(columns[9])
        # If there is an IPv6 listener on the same port, the packet's
        # destination process may not be unambiguously attributable here.
        ipv6 = _bounded(Path("/proc/net/tcp6"), MAX_TCP)
        if ipv6 is None:
            return None
        for line in ipv6.decode("ascii").splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 4 and cols[3] == "0A":
                if cols[1].upper().rsplit(":", 1)[-1] == target:
                    return None
    except (ValueError, UnicodeError):
        return None
    return next(iter(found)) if len(found) == 1 else None


def _owns_socket(pid: int, inode: str) -> bool:
    try:
        count = 0
        matched = False
        with os.scandir(f"/proc/{pid}/fd") as entries:
            for entry in entries:
                count += 1
                if count > MAX_FDS:
                    return False
                if entry.name.isdecimal():
                    try:
                        if os.readlink(entry.path) == f"socket:[{inode}]":
                            matched = True
                    except OSError:
                        continue
        return matched
    except OSError:
        return False


# Socket-inode uniqueness in /proc/net/tcp is not exclusive *process*
# ownership: fork(), inherited descriptors, or SCM_RIGHTS can give an
# unrelated PID the same listener. A partial or permission-denied process
# table must NOT be interpreted as proof of exclusivity.
MAX_PROCESSES = 32768
MAX_GLOBAL_FDS = 131072
MAX_MOUNTINFO = 1024 * 1024


def _procfs_unfiltered() -> bool:
    """Require the effective /proc mount to expose all namespace processes.

    Linux hidepid=1/2/4 may withhold other PIDs or details without raising
    PermissionError in /proc directory enumeration. Never claim an exclusive
    socket owner from a filtered PID list. Unrecognized/bind-root/ambiguous
    mounts are inconclusive; only a single ordinary full procfs mount passes.
    """
    raw = _bounded(Path("/proc/self/mountinfo"), MAX_MOUNTINFO)
    if raw is None:
        return False
    matched = 0
    try:
        for line in raw.splitlines():
            pieces = line.split(b" - ")
            if len(pieces) != 2:
                return False
            mount = pieces[0].split()
            source = pieces[1].split()
            if len(mount) < 6 or len(source) < 3:
                return False
            mountpoint = mount[4]
            if mountpoint.startswith(b"/proc/"):
                # A nested tmpfs/bind mount can silently replace another
                # process's /fd table with an empty directory while the
                # ordinary /proc mount still looks unfiltered. Inspect ALL
                # mountpoints, not only those mounted exactly at /proc.
                child = mountpoint[len(b"/proc/"):]
                if (not child or b"\\" in child or b"//" in child
                        or any(part in (b"", b".", b"..")
                               for part in child.split(b"/"))):
                    return False
                first = child.split(b"/", 1)[0]
                if (first.isdecimal()
                        or first in (b"self", b"thread-self", b"net")):
                    return False
                # Normal non-process procfs submounts (e.g. /proc/sys,
                # /proc/bus) cannot mask /proc/<PID>/fd.
                continue
            if mountpoint != b"/proc":
                continue
            matched += 1
            if (mount[3] != b"/" or source[0] != b"proc"
                    or source[1] != b"proc"):
                return False
            options = mount[5].split(b",") + source[2].split(b",")
            # hidepid may be a superblock option; reject *any* restricted or
            # ambiguous spelling rather than trusting group exemptions.
            for option in options:
                if option.startswith(b"hidepid") and option != b"hidepid=0":
                    return False
                if option == b"subset=pid":
                    return False
        return matched == 1
    except (ValueError, UnicodeError):
        return False


def _exclusive_socket_owner(pid: int, inode: str) -> bool:
    """Fail closed unless an inspectable /proc table names only this PID.

    A hidden process, inaccessible fd table, PID churn that cannot be
    distinguished, or an oversized scan yields SKIP rather than bearer
    transmission. This is conservative visibility, not cryptographic proof.
    """
    # A hidepid mount can *omit* socket co-owners silently. Check mount
    # visibility before any fd scan, and again afterwards to detect changes.
    if not _procfs_unfiltered():
        return False
    target = f"socket:[{inode}]"
    owner_seen = False
    process_count = 0
    total_fds = 0
    try:
        with os.scandir("/proc") as processes:
            for process in processes:
                if not process.name.isdecimal():
                    continue
                process_count += 1
                if process_count > MAX_PROCESSES:
                    return False
                current_pid = int(process.name)
                fd_path = f"/proc/{current_pid}/fd"
                try:
                    with os.scandir(fd_path) as descriptors:
                        per_pid_fds = 0
                        for entry in descriptors:
                            per_pid_fds += 1
                            total_fds += 1
                            if per_pid_fds > MAX_FDS or total_fds > MAX_GLOBAL_FDS:
                                return False
                            if not entry.name.isdecimal():
                                continue
                            try:
                                link = os.readlink(entry.path)
                            except FileNotFoundError:
                                # Descriptor was closed during the scan.
                                continue
                            except OSError:
                                return False
                            if link == target:
                                if current_pid != pid:
                                    return False
                                owner_seen = True
                except FileNotFoundError:
                    # A vanished process is harmless; an existing but
                    # unreadable table is NOT.
                    if os.path.exists(f"/proc/{current_pid}"):
                        return False
                except OSError:
                    return False
    except (OSError, ValueError):
        return False
    return owner_seen and _procfs_unfiltered()


def attest_api_listener(project_root: Path, api_port: str) -> ListenerProof | None:
    """One fail-closed Linux identity snapshot, with no credential access."""
    port = _port(api_port)
    if (sys.platform != "linux" or port is None
            or not isinstance(project_root, Path)
            or not project_root.is_absolute()):
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
        if inode is None or not _owns_socket(pid, inode) or not _exclusive_socket_owner(pid, inode):
            return None
        if (_identity(fd, port) != selected
                or not _same_process(pid, tick, root_stat, port)
                or _listener_inode(port) != inode
                or not _owns_socket(pid, inode)
                or not _exclusive_socket_owner(pid, inode)):
            return None
        return ListenerProof(pid, tick, port, inode)
    except (OSError, ValueError, UnicodeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def listener_still_expected(project_root: Path, proof: ListenerProof) -> bool:
    """Repeat all authority checks; don't trust an old PID or port alone."""
    if not isinstance(proof, ListenerProof):
        return False
    current = attest_api_listener(project_root, str(proof.port))
    return current == proof


def probe_api_listener(project_root: Path, api_port: str) -> Observation:
    proof = attest_api_listener(project_root, api_port)
    return Observation(
        "API-LISTENER-01", "api-listener-process",
        "launcher_record_proc_socket_owner_only",
        "PASS" if proof is not None else "SKIP",
        "api_listener_attested" if proof is not None else "api_listener_unverified",
        True, {"listener_identity_observed": proof is not None},
    )
