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


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


TOKEN_TTL_SECONDS = int(_env_value("AUTH_TOKEN_TTL_SECONDS") or str(60 * 60 * 12))


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str
    status: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    configured = (_env_value("AUTH_PROJECT_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd().resolve()


def _auth_config_dir() -> Path:
    return _project_root() / "config" / "auth"


def _bootstrap_superusers_file() -> Path:
    configured = (_env_value("AUTH_BOOTSTRAP_SUPERUSERS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _auth_config_dir() / "bootstrap_superusers.json"


def _auth_file() -> Path:
    configured = (_env_value("AUTH_USERS_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / ".auth_users.json"


def _token_secret() -> bytes:
    secret = (
        _env_value("AUTH_SECRET")
        or os.getenv("SECRET_KEY")
        or ""
    ).strip()
    if not secret:
        secret = "auth-development-secret-change-me"
    return secret.encode("utf-8")


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

    raw_json = (_env_value("AUTH_BOOTSTRAP_SUPERUSERS") or "").strip()
    if raw_json:
        try:
            users.extend(_collect_superusers_from_parsed(json.loads(raw_json)))
        except json.JSONDecodeError:
            pass

    single_username = (_env_value("AUTH_BOOTSTRAP_SUPERUSER_USERNAME") or "").strip()
    single_password = _env_value("AUTH_BOOTSTRAP_SUPERUSER_PASSWORD")
    if single_username and single_password:
        users.append({"username": single_username, "password": single_password})

    deduped: dict[str, dict[str, str]] = {}
    for item in users:
        deduped[item["username"]] = item
    return list(deduped.values())


class AuthStore:
    def __init__(self, path: Path | None = None) -> None:
        self._lock = RLock()
        self.path = path or _auth_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()
        self.ensure_bootstrap_superusers()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        self._write({"users": {}, "created_at": _utc_now(), "updated_at": _utc_now()})

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                data = {"users": {}}
            if not isinstance(data, dict):
                data = {"users": {}}
            if not isinstance(data.get("users"), dict):
                data["users"] = {}
            return data

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            data["updated_at"] = _utc_now()
            fd, tmp_name = tempfile.mkstemp(prefix=".auth_users.", suffix=".json", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
                    f.write("\n")
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)

    def ensure_bootstrap_superusers(self) -> None:
        bootstrap_users = _load_bootstrap_superusers()
        if not bootstrap_users:
            return
        data = self._read()
        changed = False
        users = data.setdefault("users", {})
        for item in bootstrap_users:
            username = item["username"]
            password = item["password"]
            existing = users.get(username)
            if not isinstance(existing, dict):
                users[username] = {
                    "username": username,
                    "password_hash": _hash_password(password),
                    "role": "superuser",
                    "status": "active",
                    "created_at": _utc_now(),
                    "approved_at": _utc_now(),
                    "approved_by": "bootstrap",
                }
                changed = True
            else:
                if not _verify_password(password, str(existing.get("password_hash") or "")):
                    existing["password_hash"] = _hash_password(password)
                    changed = True
                if existing.get("role") != "superuser" or existing.get("status") != "active":
                    existing["role"] = "superuser"
                    existing["status"] = "active"
                    existing["approved_at"] = _utc_now()
                    existing["approved_by"] = "bootstrap"
                    changed = True
        if changed:
            self._write(data)

    def register(
        self,
        username: str,
        password: str,
        *,
        full_name: str | None = None,
        department: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        username = username.strip()
        if not username or len(username) > 64:
            raise ValueError("帳號不可為空，且長度需小於 64。")
        if len(password) < 8:
            raise ValueError("密碼至少需要 8 個字元。")
        data = self._read()
        users = data.setdefault("users", {})
        if username in users:
            raise ValueError("帳號已存在。")
        users[username] = {
            "username": username,
            "password_hash": _hash_password(password),
            "role": "user",
            "status": "pending",
            "created_at": _utc_now(),
            "approved_at": None,
            "approved_by": None,
            "full_name": (full_name or "").strip() or None,
            "department": (department or "").strip() or None,
            "note": (note or "").strip() or None,
        }
        self._write(data)
        return self.public_user(users[username])

    def authenticate(self, username: str, password: str) -> AuthUser | None:
        data = self._read()
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict):
            return None
        if not _verify_password(password, str(user.get("password_hash") or "")):
            return None
        if user.get("status") != "active":
            return AuthUser(username=username, role=str(user.get("role") or "user"), status=str(user.get("status") or "pending"))
        return AuthUser(username=username, role=str(user.get("role") or "user"), status="active")

    def get_user(self, username: str) -> dict[str, Any] | None:
        user = self._read().get("users", {}).get(username)
        return user if isinstance(user, dict) else None

    def list_users(self) -> list[dict[str, Any]]:
        users = self._read().get("users", {})
        return [self.public_user(user) for user in users.values() if isinstance(user, dict)]

    def approve_user(self, username: str, role: str, approved_by: str) -> dict[str, Any]:
        if role not in {"user", "superuser"}:
            raise ValueError("role 必須是 user 或 superuser。")
        data = self._read()
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict):
            raise KeyError("帳號不存在。")
        user["role"] = role
        user["status"] = "active"
        user["approved_at"] = _utc_now()
        user["approved_by"] = approved_by
        self._write(data)
        return self.public_user(user)

    def reject_user(self, username: str, rejected_by: str) -> dict[str, Any]:
        data = self._read()
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict):
            raise KeyError("帳號不存在。")
        user["status"] = "rejected"
        user["rejected_at"] = _utc_now()
        user["rejected_by"] = rejected_by
        self._write(data)
        return self.public_user(user)

    def delete_user(self, username: str) -> dict[str, Any]:
        data = self._read()
        users = data.get("users", {})
        user = users.get(username)
        if not isinstance(user, dict):
            raise KeyError("帳號不存在。")
        removed = dict(user)
        del users[username]
        self._write(data)
        return self.public_user(removed)

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in user.items() if k != "password_hash"}


def create_token(user: AuthUser) -> str:
    payload = {
        "sub": user.username,
        "role": user.role,
        "status": user.status,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_token_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url(sig)}"


def parse_token(token: str) -> dict[str, Any] | None:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected = hmac.new(_token_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        actual = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


AUTH_STORE = AuthStore()
