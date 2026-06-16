from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any



PBKDF2_ITERATIONS = 260_000
TOKEN_TTL_SECONDS = 60 * 60 * 12
PASSWORD_RESET_TTL_SECONDS = 60 * 60
LOGIN_AUDIT_LIMIT = 1000
AUTH_THROTTLE_WINDOW_SECONDS = 15 * 60
AUTH_THROTTLE_BLOCK_SECONDS = 5 * 60
AUTH_THROTTLE_FAILURE_LIMIT = 5
PRODUCTION_ENVS = {"prod", "production"}

ROLE_SUPERUSER = "superuser"
ROLE_DB_OPERATOR = "db_operator"
ROLE_DATA_EDITOR = "data_editor"
ROLE_DATA_READER = "data_reader"
LEGACY_ROLE_ALIASES = {"user": ROLE_DATA_EDITOR}
ROLE_HIERARCHY = [ROLE_DATA_READER, ROLE_DATA_EDITOR, ROLE_DB_OPERATOR, ROLE_SUPERUSER]
ROLE_LABELS = {
    ROLE_SUPERUSER: "最高級全能者",
    ROLE_DB_OPERATOR: "資料庫操作者",
    ROLE_DATA_EDITOR: "資料修改者",
    ROLE_DATA_READER: "資料閱讀者",
}
VALID_ROLES = set(ROLE_HIERARCHY)
ROLE_LEVELS = {role: level for level, role in enumerate(ROLE_HIERARCHY)}


def normalize_role(role: str | None) -> str:
    value = (role or "").strip().lower()
    value = LEGACY_ROLE_ALIASES.get(value, value)
    return value if value in VALID_ROLES else ROLE_DATA_READER


def has_role_at_least(role: str | None, minimum_role: str) -> bool:
    return ROLE_LEVELS.get(normalize_role(role), -1) >= ROLE_LEVELS[minimum_role]


def public_role_options() -> list[dict[str, str]]:
    return [{"value": role, "label": ROLE_LABELS[role]} for role in reversed(ROLE_HIERARCHY)]


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str
    status: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> int:
    return int(time.time())


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _auth_config_dir() -> Path:
    return _project_root() / "config" / "auth"


def _bootstrap_superusers_file() -> Path:

    configured = (os.getenv("AUTH_BOOTSTRAP_SUPERUSERS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _auth_config_dir() / "bootstrap_superusers.json"


def _auth_file() -> Path:

    configured = (os.getenv("AUTH_USERS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / ".auth_users.json"


def _login_audit_file() -> Path:

    configured = (os.getenv("AUTH_LOGIN_AUDIT_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    auth_path = _auth_file()
    return auth_path.with_name(f"{auth_path.stem}.login_audit.json")


def _is_production_env() -> bool:
    app_env = (
        os.getenv("AUTH_ENV")
        or os.getenv("APP_ENV")
        or os.getenv("ENV")
        or os.getenv("PY_ENV")
        or ""
    ).strip().lower()
    return app_env in PRODUCTION_ENVS


def _token_secret() -> bytes:

    secret = (os.getenv("AUTH_SECRET") or os.getenv("SECRET_KEY") or "").strip()
    if not secret:
        if _is_production_env():
            raise RuntimeError("AUTH_SECRET 或 SECRET_KEY 必須在 production 環境設定。")
        # Development fallback. Deployments should set a stable auth secret so tokens survive restarts.
        secret = "portable-auth-pack-development-secret-change-me"
    if _is_production_env() and len(secret.encode("utf-8")) < 32:
        raise RuntimeError("production 環境的 AUTH_SECRET/SECRET_KEY 長度至少需要 32 bytes。")
    return secret.encode("utf-8")


def _token_ttl_seconds() -> int:

    raw = (os.getenv("AUTH_TOKEN_TTL_SECONDS") or "").strip()
    if not raw:
        return TOKEN_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return TOKEN_TTL_SECONDS


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密碼至少需要 8 個字元。")


def _hash_password(password: str, *, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_s, salt, expected = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations_s),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


DUMMY_PASSWORD_HASH = _hash_password(
    "portable-auth-dummy-password-for-timing-balance",
    salt="0" * 32,
)


def _normalize_throttle_part(value: str | None) -> str:
    return (value or "").strip().lower() or "unknown"


def _throttle_key(scope: str, username: str | None, client_host: str | None = None) -> str:
    return ":".join([scope, _normalize_throttle_part(username), _normalize_throttle_part(client_host)])


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _collect_superusers_from_parsed(parsed: Any) -> list[dict[str, str]]:
    if isinstance(parsed, dict):
        parsed = parsed.get("superusers") or parsed.get("users") or []
    users: list[dict[str, str]] = []
    if not isinstance(parsed, list):
        return users
    for item in parsed:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username") or "").strip()
        password = str(item.get("password") or "")
        if username and password:
            users.append({"username": username, "password": password})
    return users


def _load_bootstrap_superusers() -> list[dict[str, str]]:

    users: list[dict[str, str]] = []

    fixed_file = _bootstrap_superusers_file()
    if fixed_file.exists():
        try:
            with fixed_file.open("r", encoding="utf-8") as f:
                users.extend(_collect_superusers_from_parsed(json.load(f)))
        except (OSError, json.JSONDecodeError):
            pass

    raw_json = (os.getenv("AUTH_BOOTSTRAP_SUPERUSERS") or "").strip()
    if raw_json:
        try:
            users.extend(_collect_superusers_from_parsed(json.loads(raw_json)))
        except json.JSONDecodeError:
            pass

    single_username = (os.getenv("AUTH_BOOTSTRAP_SUPERUSER_USERNAME") or "").strip()
    single_password = os.getenv("AUTH_BOOTSTRAP_SUPERUSER_PASSWORD") or ""
    if single_username and single_password:
        users.append({"username": single_username, "password": single_password})

    deduped: dict[str, dict[str, str]] = {}
    for item in users:
        deduped[item["username"]] = item
    return list(deduped.values())
