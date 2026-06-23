from __future__ import annotations

import hmac
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from config.bootstrap import bootstrap_env


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


def is_production_like_environment() -> bool:
    app_env = (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("PY_ENV") or "").strip().lower()
    vercel_env = (os.getenv("VERCEL_ENV") or "").strip().lower()
    return app_env in {"prod", "production"} or vercel_env == "production"


def should_prefer_mock_runtime() -> bool:
    mode = mock_mode_requested()
    if mode in {"1", "true", "yes", "on", "always", "force"}:
        return True
    if mode in {"0", "false", "no", "off", "never", "disabled"}:
        return False
    if is_production_like_environment():
        return False
    return is_vercel_environment() or is_filesystem_readonly()


def preview_login_secret() -> str:
    bootstrap_env()
    return (os.getenv("SRA_VERCEL_PREVIEW_LOGIN_SECRET") or "").strip()


def is_preview_login_secret_required() -> bool:
    return bool(preview_login_secret())


def verify_preview_login_secret(candidate: str | None) -> bool:
    expected = preview_login_secret()
    if not expected:
        return True
    return hmac.compare_digest(expected, (candidate or "").strip())
