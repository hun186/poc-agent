# config/bootstrap.py
from __future__ import annotations
import os
from pathlib import Path
from typing import List, Tuple
from dotenv import dotenv_values

_BOOTSTRAPPED = False

def _project_root_from_here() -> Path:
    # .../poc-agent/config/bootstrap.py -> 專案根目錄（poc-agent）
    return Path(__file__).resolve().parents[1]

def bootstrap_env(
    env_key: str = "APP_ENV",
    default_env: str = "dev",
    project_root: Path | None = None,
    force: bool = False,
) -> Tuple[str, List[str]]:
    """
    只做一次：合併 env 檔並寫入 os.environ（不覆蓋已存在的 OS env）
    優先順序：OS env > .env.local > .env.{APP_ENV} > .env
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED and not force:
        return (os.getenv(env_key) or default_env).strip().lower(), []

    if force:
        _BOOTSTRAPPED = False
        
    env = (os.getenv(env_key) or default_env).strip().lower()
    project_root = project_root or _project_root_from_here()

    files = [
        project_root / ".env",
        project_root / f".env.{env}",
        project_root / ".env.local",
    ]

    merged: dict[str, str] = {}
    loaded: List[str] = []

    for f in files:
        if f.exists():
            merged.update({k: v for k, v in dotenv_values(f).items() if v is not None})
            loaded.append(str(f))

    # 不覆蓋 OS env：正式環境用 Secret/環境變數注入優先
    for k, v in merged.items():
        if k not in os.environ:
            os.environ[k] = v

    _BOOTSTRAPPED = True
    print(f"env:{env}")
    print(f"loaded env files:{loaded}")
    return env, loaded


def validate_required_env(keys: List[str]) -> None:
    missing = [k for k in keys if not (os.getenv(k) or "").strip()]
    if missing:
        raise RuntimeError("缺少必要環境變數：" + ", ".join(missing))


def mask_secret(v: str, keep: int = 3) -> str:
    if v is None:
        return ""
    s = str(v)
    if len(s) <= keep:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep)
