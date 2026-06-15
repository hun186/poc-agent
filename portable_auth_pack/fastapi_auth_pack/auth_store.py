# portable_auth_pack/fastapi_auth_pack/auth_store.py
from __future__ import annotations

import copy
import json
import os
import secrets
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from .auth_support import (
    AUTH_THROTTLE_BLOCK_SECONDS,
    AUTH_THROTTLE_FAILURE_LIMIT,
    AUTH_THROTTLE_WINDOW_SECONDS,
    DUMMY_PASSWORD_HASH,
    LEGACY_ROLE_ALIASES,
    LOGIN_AUDIT_LIMIT,
    PASSWORD_RESET_TTL_SECONDS,
    ROLE_DATA_EDITOR,
    ROLE_DATA_READER,
    ROLE_DB_OPERATOR,
    ROLE_SUPERUSER,
    VALID_ROLES,
    AuthUser,
    _auth_file,
    _b64url,
    _b64url_decode,
    _hash_password,
    _load_bootstrap_superusers,
    _now_ts,
    _sha256,
    _throttle_key,
    _token_secret,
    _token_ttl_seconds,
    _utc_now,
    _validate_password,
    _verify_password,
    has_role_at_least,
    normalize_role,
    public_role_options,
)


class AuthStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._throttle_lock = RLock()
        self._auth_failures: dict[str, dict[str, int]] = {}
        self.path = _auth_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()
        self.ensure_bootstrap_superusers()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        self._write(self._normalize_data({"users": {}, "created_at": _utc_now(), "updated_at": _utc_now()}))

    def _normalize_data(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data.get("users"), dict):
            data["users"] = {}
        if not isinstance(data.get("token_denylist"), dict):
            data["token_denylist"] = {}
        if not isinstance(data.get("password_reset_tokens"), dict):
            data["password_reset_tokens"] = {}
        if not isinstance(data.get("login_audit"), list):
            data["login_audit"] = []
        return data

    def _read(self) -> dict[str, Any]:
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                data = {"users": {}}
            if not isinstance(data, dict):
                data = {"users": {}}
            return self._normalize_data(data)

    def _write(self, data: dict[str, Any]) -> None:
        with self._lock:
            data = self._normalize_data(data)
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

    def _prune_token_denylist(self, data: dict[str, Any]) -> bool:
        now = _now_ts()
        denylist = data.setdefault("token_denylist", {})
        removed = False
        for jti, item in list(denylist.items()):
            if not isinstance(item, dict) or int(item.get("expires_at") or 0) < now:
                denylist.pop(jti, None)
                removed = True
        return removed

    @staticmethod
    def _invalidate_user_tokens(user: dict[str, Any]) -> None:
        user["token_version"] = int(user.get("token_version") or 0) + 1
        user["tokens_invalidated_at"] = _utc_now()

    def ensure_bootstrap_superusers(self) -> None:
        bootstrap_users = _load_bootstrap_superusers()
        if not bootstrap_users:
            return
        data = self._read()
        changed = self._prune_token_denylist(data)
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
                    "token_version": 0,
                    "created_at": _utc_now(),
                    "approved_at": _utc_now(),
                    "approved_by": "bootstrap",
                }
                changed = True
            else:
                if not _verify_password(password, str(existing.get("password_hash") or "")):
                    existing["password_hash"] = _hash_password(password)
                    self._invalidate_user_tokens(existing)
                    changed = True
                if existing.get("role") != "superuser" or existing.get("status") != "active":
                    existing["role"] = "superuser"
                    existing["status"] = "active"
                    existing["approved_at"] = _utc_now()
                    existing["approved_by"] = "bootstrap"
                    changed = True
                if "token_version" not in existing:
                    existing["token_version"] = 0
                    changed = True
        if changed:
            self._write(data)

    def register(self, username: str, password: str, *, full_name: str | None = None, department: str | None = None, note: str | None = None) -> dict[str, Any]:
        username = username.strip()
        if not username or len(username) > 64:
            raise ValueError("帳號不可為空，且長度需小於 64。")
        _validate_password(password)
        data = self._read()
        users = data.setdefault("users", {})
        if username in users:
            raise ValueError("帳號已存在。")
        users[username] = {
            "username": username,
            "password_hash": _hash_password(password),
            "role": ROLE_DATA_READER,
            "status": "pending",
            "token_version": 0,
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
        password_hash = str(user.get("password_hash") or DUMMY_PASSWORD_HASH) if isinstance(user, dict) else DUMMY_PASSWORD_HASH
        password_ok = _verify_password(password, password_hash)
        if not isinstance(user, dict) or not password_ok:
            return None
        if user.get("status") != "active":
            return AuthUser(username=username, role=normalize_role(str(user.get("role") or "")), status=str(user.get("status") or "pending"))
        return AuthUser(username=username, role=normalize_role(str(user.get("role") or "")), status="active")

    def get_user(self, username: str) -> dict[str, Any] | None:
        user = self._read().get("users", {}).get(username)
        return user if isinstance(user, dict) else None

    def list_users(self) -> list[dict[str, Any]]:
        users = self._read().get("users", {})
        return [self.public_user(user) for user in users.values() if isinstance(user, dict)]

    def approve_user(self, username: str, role: str, approved_by: str) -> dict[str, Any]:
        requested_role = (role or "").strip().lower()
        if requested_role not in VALID_ROLES and requested_role not in LEGACY_ROLE_ALIASES:
            raise ValueError("role 必須是 superuser、db_operator、data_editor 或 data_reader。")
        role = normalize_role(requested_role)
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
        self._invalidate_user_tokens(user)
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

    def change_password(self, username: str, current_password: str, new_password: str) -> dict[str, Any]:
        _validate_password(new_password)
        data = self._read()
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict):
            raise KeyError("帳號不存在。")
        if not _verify_password(current_password, str(user.get("password_hash") or "")):
            raise ValueError("目前密碼不正確。")
        user["password_hash"] = _hash_password(new_password)
        user["password_changed_at"] = _utc_now()
        self._invalidate_user_tokens(user)
        self._write(data)
        return self.public_user(user)

    def reset_user_password(self, username: str, new_password: str, reset_by: str) -> dict[str, Any]:
        _validate_password(new_password)
        data = self._read()
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict):
            raise KeyError("帳號不存在。")
        user["password_hash"] = _hash_password(new_password)
        user["password_reset_at"] = _utc_now()
        user["password_reset_by"] = reset_by
        self._invalidate_user_tokens(user)
        self._write(data)
        return self.public_user(user)

    def request_password_reset(self, username: str) -> str | None:
        data = self._read()
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict) or user.get("status") != "active":
            return None
        token = secrets.token_urlsafe(32)
        tokens = data.setdefault("password_reset_tokens", {})
        tokens[_sha256(token)] = {
            "username": username,
            "created_at": _utc_now(),
            "expires_at": _now_ts() + PASSWORD_RESET_TTL_SECONDS,
            "used_at": None,
        }
        self._write(data)
        return token

    def recover_password(self, username: str, reset_token: str, new_password: str) -> dict[str, Any]:
        _validate_password(new_password)
        data = self._read()
        token_hash = _sha256(reset_token)
        token_record = data.setdefault("password_reset_tokens", {}).get(token_hash)
        if not isinstance(token_record, dict):
            raise ValueError("重設密碼連結已失效。")
        if token_record.get("used_at") or int(token_record.get("expires_at") or 0) < _now_ts():
            raise ValueError("重設密碼連結已失效。")
        if token_record.get("username") != username:
            raise ValueError("重設密碼連結已失效。")
        user = data.get("users", {}).get(username)
        if not isinstance(user, dict) or user.get("status") != "active":
            raise ValueError("重設密碼連結已失效。")
        user["password_hash"] = _hash_password(new_password)
        user["password_recovered_at"] = _utc_now()
        self._invalidate_user_tokens(user)
        token_record["used_at"] = _utc_now()
        self._write(data)
        return self.public_user(user)

    def deny_token(self, payload: dict[str, Any]) -> None:
        jti = str(payload.get("jti") or "")
        if not jti:
            return
        data = self._read()
        self._prune_token_denylist(data)
        data.setdefault("token_denylist", {})[jti] = {
            "username": str(payload.get("sub") or ""),
            "denied_at": _utc_now(),
            "expires_at": int(payload.get("exp") or _now_ts()),
        }
        self._write(data)

    def is_token_denied(self, jti: str) -> bool:
        if not jti:
            return True
        data = self._read()
        changed = self._prune_token_denylist(data)
        item = data.get("token_denylist", {}).get(jti)
        if changed:
            self._write(data)
        return isinstance(item, dict)

    def is_token_current(self, username: str, token_version: int) -> bool:
        user = self.get_user(username)
        if not isinstance(user, dict):
            return False
        return int(user.get("token_version") or 0) == token_version

    def record_login_audit(self, username: str, *, success: bool, reason: str, role: str | None = None, status_value: str | None = None, client_host: str | None = None, user_agent: str | None = None) -> None:
        data = self._read()
        audit = data.setdefault("login_audit", [])
        audit.append({
            "ts": _utc_now(),
            "username": username,
            "success": success,
            "reason": reason,
            "role": role,
            "status": status_value,
            "client_host": client_host,
            "user_agent": user_agent,
        })
        if len(audit) > LOGIN_AUDIT_LIMIT:
            del audit[:-LOGIN_AUDIT_LIMIT]
        self._write(data)

    def list_login_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        audit = self._read().get("login_audit", [])
        if not isinstance(audit, list):
            return []
        limit = max(1, min(limit, LOGIN_AUDIT_LIMIT))
        return [item for item in audit[-limit:] if isinstance(item, dict)]

    def throttle_retry_after(self, scope: str, username: str | None, client_host: str | None = None) -> int:
        key = _throttle_key(scope, username, client_host)
        now = _now_ts()
        with self._throttle_lock:
            state = self._auth_failures.get(key)
            if not state:
                return 0
            blocked_until = int(state.get("blocked_until") or 0)
            if blocked_until <= now:
                if int(state.get("first_failed_at") or 0) + AUTH_THROTTLE_WINDOW_SECONDS <= now:
                    self._auth_failures.pop(key, None)
                return 0
            return blocked_until - now

    def record_auth_failure(self, scope: str, username: str | None, client_host: str | None = None) -> int:
        key = _throttle_key(scope, username, client_host)
        now = _now_ts()
        with self._throttle_lock:
            state = self._auth_failures.get(key)
            if not state or int(state.get("first_failed_at") or 0) + AUTH_THROTTLE_WINDOW_SECONDS <= now:
                state = {"first_failed_at": now, "failures": 0, "blocked_until": 0}
                self._auth_failures[key] = state
            state["failures"] = int(state.get("failures") or 0) + 1
            if state["failures"] >= AUTH_THROTTLE_FAILURE_LIMIT:
                state["blocked_until"] = now + AUTH_THROTTLE_BLOCK_SECONDS
                return AUTH_THROTTLE_BLOCK_SECONDS
            return 0

    def clear_auth_failures(self, scope: str, username: str | None, client_host: str | None = None) -> None:
        key = _throttle_key(scope, username, client_host)
        with self._throttle_lock:
            self._auth_failures.pop(key, None)

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        public = {k: v for k, v in user.items() if k != "password_hash"}
        public["role"] = normalize_role(str(public.get("role") or ""))
        return public


from .auth_tokens import parse_token as parse_token
from .auth_tokens import create_token as _create_token


def create_token(user: AuthUser) -> str:
    return _create_token(user, AUTH_STORE.get_user)


AUTH_STORE = AuthStore()
