"""Explicit external subject -> current SRAF account generation.

Only for internal trusted code. Does not mount a route, issue a token,
create an AuthPrincipal, infer authorization from a name, or grant access.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from api.security.sraf_handoff_assertion import HandoffDenied, HandoffTrust
from api.security.sraf_handoff_replay import HandoffReplayStore

_ID = re.compile(r"[A-Za-z0-9._~-]{1,128}\Z")


def _bounded(value, size):
    return (type(value) is str and 1 <= len(value) <= size
            and value == value.strip() and all(ord(c) >= 32 and ord(c) != 127 for c in value))


@dataclass(frozen=True, repr=False)
class ExternalAccountBinding:
    issuer: str
    audience: str
    external_subject: str
    owner_id: str
    account_created_at: str

    def __post_init__(self):
        if (not all(type(v) is str and _ID.fullmatch(v) is not None
                    for v in (self.issuer, self.audience, self.external_subject))
                or not _bounded(self.owner_id, 64)
                or not _bounded(self.account_created_at, 80)):
            raise HandoffDenied("handoff_mapping_invalid")


@dataclass(frozen=True, repr=False)
class HandoffSubjectMap:
    bindings: tuple[ExternalAccountBinding, ...]

    def __post_init__(self):
        if (type(self.bindings) is not tuple or not 1 <= len(self.bindings) <= 256
                or any(type(b) is not ExternalAccountBinding for b in self.bindings)
                or len({(b.issuer, b.audience, b.external_subject) for b in self.bindings})
                    != len(self.bindings)
                or len({(b.issuer, b.audience, b.owner_id) for b in self.bindings})
                    != len(self.bindings)):
            raise HandoffDenied("handoff_mapping_invalid")


@dataclass(frozen=True, repr=False)
class MappedChatIdentity:
    """Fresh mapping observation; future receiver must recheck before side effects."""
    owner_id: str
    account_created_at: str
    role: str
    issuer: str
    audience: str
    chat_id: str
    message_id: str


def map_verified_chat_once(trust: HandoffTrust, mapping: HandoffSubjectMap,
                           replay: HandoffReplayStore, token: str, *, body: bytes,
                           method: str, path: str, now: int | None = None) -> MappedChatIdentity:
    """Combine signature, durable nonce and explicit real account mapping.

    No external user can supply the mapping, trust, database or clock.
    A valid signed assertion for an unmapped/disabled account is consumed and
    denied; retry requires a new signature. No account/role auto-provisioning.
    This is not general login or permission to access an artifact.
    """
    if type(mapping) is not HandoffSubjectMap or type(replay) is not HandoffReplayStore:
        raise HandoffDenied("handoff_mapping_invalid")
    assertion = replay.verify_once(trust, token, body=body, method=method,
                                    path=path, now=now).assertion
    binding = next((b for b in mapping.bindings
                    if (b.issuer, b.audience, b.external_subject)
                    == (assertion.issuer, assertion.audience, assertion.external_subject)), None)
    if binding is None:
        raise HandoffDenied("handoff_account_denied")
    import api.services.auth_store as auth_store_module
    from api.services.auth_support import VALID_ROLES, normalize_role
    from api.security.scopes import MODEL_INVOKE, scopes_for_user_role
    try:
        row = auth_store_module.AUTH_STORE.get_user(binding.owner_id)
        if (type(row) is not dict or row.get("username") != binding.owner_id
                or row.get("status") != "active"
                or row.get("created_at") != binding.account_created_at
                or row.get("role") not in VALID_ROLES
                or binding.owner_id == "vercel_mock_reader"):
            raise HandoffDenied("handoff_account_denied")
        role = normalize_role(row["role"])
        if MODEL_INVOKE not in scopes_for_user_role(role):
            raise HandoffDenied("handoff_account_denied")
        return MappedChatIdentity(binding.owner_id, binding.account_created_at, role,
                                  assertion.issuer, assertion.audience,
                                  assertion.chat_id, assertion.message_id)
    except Exception:
        raise HandoffDenied("handoff_account_denied") from None
