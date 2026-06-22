from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from typing import Any

from .auth_support import AuthUser, _b64url, _b64url_decode, _now_ts, _token_secret, _token_ttl_seconds


def create_token(user: AuthUser, get_user: Callable[[str], dict[str, Any] | None] | None = None) -> str:
    stored = get_user(user.username) if get_user is not None else None
    token_version = int(stored.get("token_version") or 0) if isinstance(stored, dict) else 0
    payload = {
        "sub": user.username,
        "role": user.role,
        "status": user.status,
        "iat": _now_ts(),
        "exp": _now_ts() + _token_ttl_seconds(),
        "jti": secrets.token_urlsafe(24),
        "ver": token_version,
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
        if int(payload.get("exp") or 0) < _now_ts():
            return None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None
