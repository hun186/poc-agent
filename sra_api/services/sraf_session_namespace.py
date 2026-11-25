"""Reserved session namespace for authenticated external chat adapters.

The prefix is deliberately short enough for FileSessionStore's 120-character
filename limit. Legacy callers cannot select a reserved storage ID directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from fastapi import HTTPException
from api.security.models import AuthPrincipal

SCOPED_CHAT_HEADER = "x-sraf-openwebui-chat-id"
PREFIX = "srafowui1-"
_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")
_KEY = re.compile(r"srafowui1-([0-9a-f]{32})-([0-9a-f]{64})\Z")


def is_reserved_session(value) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(PREFIX)


def _owner_tag(principal):
    from api.services.sraf_deep_scope_policy import binding_for_principal
    if type(principal) is not AuthPrincipal or principal.kind != "user":
        return None
    binding = binding_for_principal(principal)
    if binding is None:
        return None
    return sha256(("sraf-chat-owner-v1:" + binding).encode()).hexdigest()[:32]


@dataclass(frozen=True, repr=False)
class ScopedChatSession:
    key: str


def bind_openwebui_session(principal, values: tuple[str, ...]) -> ScopedChatSession:
    if type(values) is not tuple or len(values) != 1 or type(values[0]) is not str or not _ID.fullmatch(values[0]):
        raise HTTPException(400, "Invalid scoped chat ID")
    owner_tag = _owner_tag(principal)
    if owner_tag is None:
        raise HTTPException(403, "Scoped chat requires an authenticated user")
    chat_tag = sha256(("sraf-openwebui-chat-v1:" + values[0]).encode()).hexdigest()
    return ScopedChatSession(PREFIX + owner_tag + "-" + chat_tag)


def scoped_session_owned(session_id: str, principal) -> bool:
    match = _KEY.fullmatch(session_id)
    owner = _owner_tag(principal)
    return match is not None and owner is not None and match[1] == owner


def require_legacy_session(value: str) -> str:
    if is_reserved_session(value):
        raise HTTPException(400, "Reserved chat session namespace")
    return value
