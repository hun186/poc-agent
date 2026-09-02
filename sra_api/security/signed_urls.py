from __future__ import annotations

import base64, hashlib, hmac, json, os, secrets, time, warnings
from api.services.auth_support import PRODUCTION_ENVS

ALLOWED_TYPES = {"doc_detail", "doc_fulltext", "legacy_word"}
_fallback_warned = False


def _secret() -> bytes:
    global _fallback_warned
    value = os.getenv("SRA_SIGNED_URL_SECRET", "").encode()
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("PY_ENV") or "").lower()
    if len(value) < 32:
        if env in PRODUCTION_ENVS: raise RuntimeError("SRA_SIGNED_URL_SECRET must contain at least 32 bytes")
        value = b"sra-development-signed-url-secret-change-me"
        if not _fallback_warned:
            warnings.warn("Using development fallback for signed URL secret", RuntimeWarning, stacklevel=2)
            _fallback_warned = True
    return value


def validate_signing_config(): _secret()


def _b64(data: bytes) -> str: return base64.urlsafe_b64encode(data).decode().rstrip("=")
def _unb64(data: str) -> bytes: return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_resource(resource_type: str, *, ttl_seconds=None, **binding) -> str:
    if resource_type not in ALLOWED_TYPES: raise ValueError("Unsupported resource type")
    ttl = int(ttl_seconds or os.getenv("SRA_SIGNED_URL_TTL_SECONDS", "86400"))
    payload = {"v": 1, "method": "GET", "resource_type": resource_type, "exp": int(time.time()) + max(1, min(ttl, 604800)), **binding}
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_resource_token(token: str, resource_type: str, **binding) -> dict:
    try:
        body, supplied = token.split(".")
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected): raise ValueError
        payload = json.loads(_unb64(body))
    except Exception as exc:
        raise ValueError("Invalid capability") from exc
    expected_payload = {"v": 1, "method": "GET", "resource_type": resource_type, **binding}
    if int(payload.get("exp", 0)) < int(time.time()): raise ValueError("Expired capability")
    if any(payload.get(k) != v for k, v in expected_payload.items()): raise ValueError("Invalid capability")
    if set(payload) != set(expected_payload) | {"exp"}: raise ValueError("Invalid capability")
    return payload
