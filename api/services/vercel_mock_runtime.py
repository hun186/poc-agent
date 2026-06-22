from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path


def is_vercel_environment() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.getenv("NOW_REGION"))


@lru_cache(maxsize=1)
def is_filesystem_readonly() -> bool:
    probe_dir = Path(tempfile.gettempdir())
    try:
        probe = probe_dir / ".sra_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return False
    except Exception:
        return True


def mock_mode_requested() -> str:
    return (os.getenv("SRA_VERCEL_MOCK_MODE") or "auto").strip().lower()


def should_prefer_mock_runtime() -> bool:
    mode = mock_mode_requested()
    if mode in {"1", "true", "yes", "on", "always", "force"}:
        return True
    if mode in {"0", "false", "no", "off", "never", "disabled"}:
        return False
    return is_vercel_environment() or is_filesystem_readonly()
