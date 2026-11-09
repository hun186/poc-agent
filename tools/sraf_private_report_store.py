"""Dependency-light, reviewed private evidence store shared by operator CLIs.

No application, dotenv, pyodbc, HTTP, LLM or worker imports. Maintains OFF-1
directory FD pinning, trusted ancestor ownership, no-follow and exclusive 0600
evidence writes. Do not weaken this contract for convenience.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import stat


class ObservationError(Exception):
    """Only fixed, non-sensitive error codes can escape to evidence."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _secure_output_dir(path: Path):
    """Pin every path component with Linux no-follow dirfds; return an owned fd.

    Ancestors must be root/current-UID-owned and not writable by another user,
    except for a root-owned sticky directory such as /tmp. The final directory
    must be current-UID-owned and private (0700 or stricter). All later output
    writes are relative to this pinned fd, never the path after validation.
    """
    if os.name != "posix" or not all(hasattr(os, flag) for flag in
                                       ("O_NOFOLLOW", "O_DIRECTORY")):
        raise ObservationError("output_dirfd_unsupported")
    if ".." in path.parts:
        raise ObservationError("output_dir_invalid")
    components = Path(os.path.abspath(path)).parts[1:]
    if not components:
        raise ObservationError("output_dir_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for index, component in enumerate(components):
            last = index == len(components) - 1
            if last:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, flags, dir_fd=fd)
            try:
                mode = os.fstat(child)
                if mode.st_uid not in (os.geteuid(), 0):
                    raise ObservationError("output_ancestor_untrusted")
                if last:
                    if mode.st_uid != os.geteuid() or mode.st_mode & 0o077:
                        raise ObservationError("output_permissions_unsafe")
                elif mode.st_mode & 0o022 and not (
                    mode.st_uid == 0 and mode.st_mode & stat.S_ISVTX
                ):
                    raise ObservationError("output_ancestor_writable")
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _secure_write(name: str, raw: bytes, result_fd: int):
    """Create one private, unique file in the already verified output dirfd."""
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", name) is None or name in (".", ".."):
        raise ObservationError("output_filename_invalid")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=result_fd)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        try:
            os.unlink(name, dir_fd=result_fd)
        except OSError:
            pass
        raise


