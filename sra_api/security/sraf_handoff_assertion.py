"""Private, request-bound backend handoff assertion; NOT an authentication route.

One operator-configured issuer, logical audience and dedicated signing key set.
No OpenWebUI login secret, stored user bearer, IP trust or claimed SRAF role.
Verification alone is NOT authorization: the future receiver must atomically
consume the nonce, verify an explicit live subject/account-generation mapping
and enforce normal SRAF scopes before any protected action. No network or IO.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import time

_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")
_CONTEXT = b"SRAF-BACKEND-CHAT-HANDOFF-V1\x00"
_PATH = "/v1/chat/completions"
_MAX_BODY = 2 * 1024 * 1024
_MAX_TOKEN = 8192
_MAX_TTL = 60
_FUTURE_SKEW = 5
_FIELDS = frozenset(("iss", "aud", "sub", "chat", "message", "nonce",
                     "iat", "exp", "method", "path", "body_sha256"))


class HandoffDenied(ValueError):
    """Fixed denial; do not expose assertion, body, key or account."""


def _deny():
    raise HandoffDenied("handoff_assertion_denied")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    if not _B64.fullmatch(value):
        _deny()
    raw = base64.b64decode(value + "=" * (-len(value) % 4),
                           altchars=b"-_", validate=True)
    if _b64(raw) != value:
        _deny()
    return raw


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            _deny()
        obj[key] = value
    return obj


def _body_digest(body: bytes) -> str:
    if type(body) is not bytes or not 1 <= len(body) <= _MAX_BODY:
        _deny()
    return hashlib.sha256(body).hexdigest()


def _clock(now: int | None) -> int:
    value = int(time.time()) if now is None else now
    if type(value) is not int or not 0 < value < 2**53:
        _deny()
    return value


@dataclass(frozen=True, repr=False)
class HandoffKey:
    key_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self):
        if (not _id(self.key_id) or "." in self.key_id or type(self.secret) is not bytes
                or not 32 <= len(self.secret) <= 128):
            _deny()


@dataclass(frozen=True, repr=False)
class HandoffTrust:
    issuer: str
    audience: str
    keys: tuple[HandoffKey, ...]

    def __post_init__(self):
        if (not _id(self.issuer) or not _id(self.audience)
                or type(self.keys) is not tuple or not 1 <= len(self.keys) <= 2
                or any(type(k) is not HandoffKey for k in self.keys)
                or len({k.key_id for k in self.keys}) != len(self.keys)
                or len({k.secret for k in self.keys}) != len(self.keys)):
            _deny()

    def key(self, key_id: str) -> HandoffKey:
        if not _id(key_id) or "." in key_id:
            _deny()
        key = next((k for k in self.keys if k.key_id == key_id), None)
        if key is None:
            _deny()
        return key


@dataclass(frozen=True, repr=False)
class VerifiedChatAssertion:
    """Cryptographically verified, NOT replay-consumed or authorized."""
    issuer: str
    audience: str
    external_subject: str
    chat_id: str
    message_id: str
    nonce: str
    issued_at: int
    expires_at: int
    body_sha256: str


def _mac(key: HandoffKey, payload: str) -> bytes:
    return hmac.new(key.secret, _CONTEXT + key.key_id.encode("ascii")
                    + b"\x00" + payload.encode("ascii"), hashlib.sha256).digest()


def sign_chat_assertion(trust: HandoffTrust, *, key_id: str,
                        external_subject: str, chat_id: str, message_id: str,
                        body: bytes, ttl: int = 30, now: int | None = None) -> str:
    """Trusted adapter helper. Subject must come from server-authenticated context.

    The HTTP body must be the EXACT bytes subsequently sent, not a reserialized
    object. Generate a fresh assertion for each retry; stable chat/message
    idempotency is independent of its random nonce.
    """
    if (type(trust) is not HandoffTrust
            or not all(_id(v) for v in (external_subject, chat_id, message_id))
            or type(ttl) is not int or not 1 <= ttl <= _MAX_TTL):
        _deny()
    key = trust.key(key_id)
    issued = _clock(now)
    obj = {"iss": trust.issuer, "aud": trust.audience, "sub": external_subject,
           "chat": chat_id, "message": message_id, "nonce": secrets.token_urlsafe(24),
           "iat": issued, "exp": issued + ttl, "method": "POST", "path": _PATH,
           "body_sha256": _body_digest(body)}
    payload = _b64(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("ascii"))
    return "srafh1." + key.key_id + "." + payload + "." + _b64(_mac(key, payload))


def verify_chat_assertion(trust: HandoffTrust, token: str, *, body: bytes,
                          method: str, path: str, now: int | None = None) -> VerifiedChatAssertion:
    """Exact cryptographic + time + request binding; does not establish login.

    A future receiver MUST reject duplicate assertion headers, authorize only
    authenticated server traffic over protected transport, consume nonce and
    verify current explicit mapping before converting to any principal.
    """
    try:
        if (type(trust) is not HandoffTrust or type(token) is not str
                or not 1 <= len(token) <= _MAX_TOKEN or method != "POST" or path != _PATH):
            _deny()
        version, key_id, payload, signature = token.split(".")
        if version != "srafh1" or not _B64.fullmatch(payload):
            _deny()
        key = trust.key(key_id)
        if not hmac.compare_digest(_mac(key, payload), _unb64(signature)):
            _deny()
        obj = json.loads(_unb64(payload).decode("ascii"), object_pairs_hook=_unique_pairs)
        if type(obj) is not dict or set(obj) != _FIELDS:
            _deny()
        if (obj["iss"] != trust.issuer or obj["aud"] != trust.audience
                or not all(_id(obj[k]) for k in ("sub", "chat", "message", "nonce"))
                or len(obj["nonce"]) < 32 or obj["method"] != method or obj["path"] != path
                or type(obj["body_sha256"]) is not str
                or not _HEX.fullmatch(obj["body_sha256"])
                or not hmac.compare_digest(obj["body_sha256"], _body_digest(body))):
            _deny()
        clock = _clock(now)
        iat, exp = obj["iat"], obj["exp"]
        if (type(iat) is not int or type(exp) is not int
                or not 0 < iat < 2**53 or not 1 <= exp - iat <= _MAX_TTL
                or iat > clock + _FUTURE_SKEW or exp <= clock):
            _deny()
        return VerifiedChatAssertion(obj["iss"], obj["aud"], obj["sub"], obj["chat"],
                                     obj["message"], obj["nonce"], iat, exp, obj["body_sha256"])
    except Exception:
        raise HandoffDenied("handoff_assertion_denied") from None
