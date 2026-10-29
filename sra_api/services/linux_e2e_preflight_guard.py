"""Linux same-host, same-UID advisory guard for operator-only E2E preflight.

Not a durable queue, a distributed lock, a global plan, or a process kill.
Non-Linux platforms retain only the existing process-local tracker.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if sys.platform == "linux":
    import fcntl


class HostPreflightBusy(RuntimeError):
    """Another same-host handler still holds the operator lock."""


class HostPreflightUnavailable(RuntimeError):
    """Fail closed when the Linux coordination lock cannot be verified."""


def _secure_lock_fd() -> int:
    """Open a private 0700 directory and 0600 lock via no-follow descriptors."""
    project = str(Path(__file__).resolve().parents[2])
    tag = hashlib.sha256(os.fsencode(project)).hexdigest()[:24]
    directory = os.path.join(
        tempfile.gettempdir(), f"sraf-operator-e2e-{os.getuid()}-{tag}"
    )
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    dir_fd = os.open(
        directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        info = os.fstat(dir_fd)
        if (not stat.S_ISDIR(info.st_mode) or
                info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) != 0o700):
            raise HostPreflightUnavailable("external_e2e_host_guard_unavailable")
        file_fd = os.open(
            "preflight.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=dir_fd,
        )
        try:
            info = os.fstat(file_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600):
                raise HostPreflightUnavailable("external_e2e_host_guard_unavailable")
            return file_fd
        except BaseException:
            os.close(file_fd)
            raise
    except OSError as exc:
        raise HostPreflightUnavailable("external_e2e_host_guard_unavailable") from exc
    finally:
        os.close(dir_fd)


@contextmanager
def host_preflight_guard() -> Iterator[None]:
    if sys.platform != "linux":
        yield
        return
    try:
        fd = _secure_lock_fd()
    except OSError as exc:
        raise HostPreflightUnavailable("external_e2e_host_guard_unavailable") from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HostPreflightBusy("external_e2e_preflight_in_progress") from exc
        except OSError as exc:
            raise HostPreflightUnavailable("external_e2e_host_guard_unavailable") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def linux_host_guard_held() -> bool:
    """Only returns an observational busy bit; never recovers owner or state."""
    if sys.platform != "linux":
        return False
    try:
        with host_preflight_guard():
            return False
    except HostPreflightBusy:
        return True
