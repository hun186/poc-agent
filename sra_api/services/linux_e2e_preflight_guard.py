"""Linux same-host, same-UID advisory guard for operator-only E2E preflight.

Not a durable queue, a distributed lock, a global plan, or a process kill.
Non-Linux platforms retain only the existing process-local tracker.
"""
from __future__ import annotations

import hashlib
import os
import secrets
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
        yield None
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
            yield fd
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


# Only non-secret opaque generation markers are stored in the original private
# lock file. The kernel flock is still the exclusive same-host preflight gate.
_EPOCH_BYTES = 32


def advance_host_preflight_epoch(lock_fd: int | None) -> str | None:
    """Rotate under an already held exclusive guard; never share a plan."""
    if sys.platform != "linux":
        return None
    if lock_fd is None:
        raise HostPreflightUnavailable("external_e2e_host_guard_unavailable")
    epoch = secrets.token_hex(16)
    try:
        # A crash while writing yields missing/corrupt data, which readers
        # reject instead of trusting a stale plan.
        payload = epoch.encode("ascii")
        if os.pwrite(lock_fd, payload, 0) != _EPOCH_BYTES:
            raise HostPreflightUnavailable("external_e2e_host_guard_unavailable")
        os.ftruncate(lock_fd, _EPOCH_BYTES)
        os.fsync(lock_fd)
    except OSError as exc:
        raise HostPreflightUnavailable("external_e2e_host_guard_unavailable") from exc
    return epoch


def read_host_preflight_epoch() -> str:
    """Read a complete generation or fail closed (including busy preflight)."""
    if sys.platform != "linux":
        raise HostPreflightUnavailable("external_e2e_host_guard_unavailable")
    try:
        fd = _secure_lock_fd()
    except OSError as exc:
        raise HostPreflightUnavailable("external_e2e_host_guard_unavailable") from exc
    try:
        try:
            # No wait for an in-progress operator SDK call: new E2E jobs
            # cannot enter while another worker owns the host-level guard.
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HostPreflightBusy("external_e2e_preflight_in_progress") from exc
        except OSError as exc:
            raise HostPreflightUnavailable("external_e2e_host_guard_unavailable") from exc
        try:
            raw = os.pread(fd, _EPOCH_BYTES + 1, 0)
            if (len(raw) != _EPOCH_BYTES or any(ch not in b"0123456789abcdef" for ch in raw)):
                raise HostPreflightUnavailable("external_e2e_host_guard_unavailable")
            return raw.decode("ascii")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
