"""OFF-1F Linux-only proof that the *listening server* disabled cloud.

Conservative: no /proc access, hidden Docker PID namespace, unknown Ollama
binary, wildcard/IPv6 listener, ambiguity, old version -> no generation.
Never reads an arbitrary user path, changes process state or reveals secrets.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from tools.sraf_airgap_off1_probes import _http_get

PROC = Path("/proc")
MAX_TCP_BYTES = 1024 * 1024
MAX_ENV_BYTES = 128 * 1024
MAX_CMD_BYTES = 4096
MAX_FDS = 4096
MIN_NO_CLOUD_VERSION = (0, 16, 2)


def _read_bounded(path: Path, limit: int) -> bytes | None:
    try:
        with path.open("rb") as fd:
            value = fd.read(limit + 1)
        return value if len(value) <= limit else None
    except (OSError, ValueError):
        return None


def _loopback_listen_inode(port: int) -> str | None:
    """Find one exact numeric 127.0.0.1 TCP LISTEN socket, no wildcard."""
    data = _read_bounded(PROC / "net/tcp", MAX_TCP_BYTES)
    if data is None:
        return None
    target = f"0100007F:{port:04X}"
    inodes: set[str] = set()
    try:
        for line in data.decode("ascii").splitlines()[1:]:
            cols = line.split()
            if (len(cols) >= 10 and cols[1].upper() == target
                    and cols[3] == "0A" and cols[9].isdigit()
                    and cols[9] != "0"):
                inodes.add(cols[9])
    except UnicodeError:
        return None
    return next(iter(inodes)) if len(inodes) == 1 else None


def _owns_socket(pid: int, inode: str) -> bool:
    """Explicit operator PID must own the exact listening TCP socket."""
    try:
        with os.scandir(PROC / str(pid) / "fd") as entries:
            count = 0
            for entry in entries:
                count += 1
                if count > MAX_FDS:
                    return False
                if not entry.name.isdecimal():
                    continue
                try:
                    if os.readlink(entry.path) == f"socket:[{inode}]":
                        return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def server_cloud_disabled(pid: int | None, port: int) -> bool:
    """Reject unless the actual localhost listener is an Ollama serve PID.

    Only accepts OLLAMA_NO_CLOUD=1 in the *server process* environment.
    Looking at the caller's environment or a possibly stale server.json
    cannot attest that the running process disabled remote inference.
    """
    if (sys.platform != "linux" or type(pid) is not int or pid < 2
            or pid > 4_194_304 or type(port) is not int
            or not 1 <= port <= 65535):
        return False
    proc = PROC / str(pid)
    try:
        executable = os.readlink(proc / "exe")
    except OSError:
        return False
    if Path(executable).name != "ollama":
        return False
    cmd = _read_bounded(proc / "cmdline", MAX_CMD_BYTES)
    env = _read_bounded(proc / "environ", MAX_ENV_BYTES)
    if cmd is None or env is None:
        return False
    argv = cmd.rstrip(b"\0").split(b"\0")
    if (len(argv) < 2 or Path(os.fsdecode(argv[0])).name != "ollama"
            or argv[1] != b"serve"):
        return False
    flags = [item for item in env.split(b"\0")
             if item.startswith(b"OLLAMA_NO_CLOUD=")]
    if flags != [b"OLLAMA_NO_CLOUD=1"]:
        return False
    inode = _loopback_listen_inode(port)
    if inode is None or not _owns_socket(pid, inode):
        return False
    # Recheck on the same process before caller performs a POST.
    return (_loopback_listen_inode(port) == inode
            and _owns_socket(pid, inode))


def supported_local_only_version(port: int) -> bool:
    """The cloud opt-out must be implemented in the running server version.

    Ollama NoCloud() is supported from v0.16.2. Read only GET /api/version
    on the same numeric loopback endpoint; reject unknown/prerelease shapes.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        return False
    status, body = _http_get(port, "/api/version")
    if status != 200 or body is None or len(body) > 512:
        return False
    try:
        import json
        response = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return False
    if not isinstance(response, dict):
        return False
    version = response.get("version")
    if not isinstance(version, str):
        return False
    match = re.fullmatch(r"v?(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})", version)
    return match is not None and tuple(int(g) for g in match.groups()) >= MIN_NO_CLOUD_VERSION
