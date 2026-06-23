from __future__ import annotations

import secrets
from typing import Any

from .auth_passwords import _hash_password, _validate_password, _verify_password
from .auth_support import PASSWORD_RESET_TTL_SECONDS, _now_ts, _sha256, _utc_now


class AuthPasswordMixin:
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
