"""Shared stdlib-only, no-network OFF-1 path and port validation primitives.

Kept independent of SQL, pyodbc and Report Job modules so PASSIVE listener
identity can be observed even when optional native database deps cannot load.
The exact existing root-anchored O_NOFOLLOW and bounded port rules are retained.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from typing import Any


def _pin_root_directory(root: Path) -> int:
    """Pin every ancestor with openat(O_NOFOLLOW) before reading any trusted file."""
    parts = root.parts
    if (not root.is_absolute() or len(parts) < 2
            or any(part in ("", ".", "..") for part in parts[1:])):
        raise ValueError("root_path_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise ValueError("root_not_directory")
        return fd
    except Exception:
        os.close(fd)
        raise


def _port(value: Any) -> int | None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,5}", value) is None:
        return None
    n = int(value)
    return n if 1 <= n <= 65535 else None

