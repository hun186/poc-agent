"""Private Chat-only bridge from verified backend assertion to scoped context.

This module is not a public auth dependency or a mounted route. The caller
must be the protected server ingress; HTTP headers alone never attest TLS or
the local listener. No login token is issued and no admin scopes are granted.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from api.security.models import AuthPrincipal
from api.security.scopes import (
    DOCUMENT_READ, MODEL_INVOKE, REPORT_JOB_CREATE, REPORT_JOB_READ,
    REPORT_JOB_DOWNLOAD, REPORT_LEGACY_DOWNLOAD, scopes_for_user_role,
)
from api.security.sraf_handoff_assertion import HandoffDenied, HandoffTrust
from api.security.sraf_handoff_mapping import (
    HandoffSubjectMap, MappedChatIdentity, map_verified_chat_once,
)
from api.security.sraf_handoff_replay import HandoffReplayStore
from api.services.sraf_session_namespace import ScopedChatSession, bind_openwebui_session
from api.services.sraf_deep_scope_policy import binding_for_principal

_ASSERTION = b"x-sraf-backend-assertion"
# All session and turn IDs come only from the signed assertion, not HTTP
# headers, browser tokens or client-provided aliases.
_FORBIDDEN = frozenset((
    b"authorization", b"proxy-authorization", b"cookie", b"idempotency-key",
    b"x-sraf-openwebui-chat-id", b"x-openwebui-chat-id", b"x-conversation-id",
    b"x-session-id",
))
_CHAT_SCOPES = frozenset((DOCUMENT_READ, MODEL_INVOKE, REPORT_JOB_CREATE,
                         REPORT_JOB_READ, REPORT_JOB_DOWNLOAD, REPORT_LEGACY_DOWNLOAD))


def _digest(domain: str, values: list[str]) -> str:
    return hashlib.sha256(json.dumps([domain, *values], separators=(",", ":"),
                         ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, repr=False)
class HandoffChatContext:
    identity: MappedChatIdentity
    principal: AuthPrincipal
    session: ScopedChatSession
    turn_token: str


def _build(identity: MappedChatIdentity, mapping: HandoffSubjectMap) -> HandoffChatContext:
    if type(identity) is not MappedChatIdentity or type(mapping) is not HandoffSubjectMap:
        raise HandoffDenied("handoff_chat_denied")
    match = next((b for b in mapping.bindings
                  if (b.issuer, b.audience, b.external_subject)
                  == (identity.issuer, identity.audience, identity.external_subject)), None)
    if (match is None or match.owner_id != identity.owner_id
            or match.account_created_at != identity.account_created_at):
        raise HandoffDenied("handoff_chat_denied")
    scopes = scopes_for_user_role(identity.role) & _CHAT_SCOPES
    if MODEL_INVOKE not in scopes:
        raise HandoffDenied("handoff_chat_denied")
    principal = AuthPrincipal("user", identity.owner_id, identity.role, scopes,
                              "handoff-chat-v1:" + identity.assertion_id,
                              account_created_at=identity.account_created_at)
    if binding_for_principal(principal) is None:
        raise HandoffDenied("handoff_chat_denied")
    prefix = [identity.issuer, identity.audience, identity.external_subject, identity.chat_id]
    # Preserve stable session across key rotation and IP migration, but not
    # across external account/installation/chat changes.
    chat = _digest("sraf-handoff-chat-v1", prefix)
    turn = _digest("sraf-handoff-turn-v1", prefix + [identity.message_id])
    session = bind_openwebui_session(principal, (chat,))
    return HandoffChatContext(identity, principal, session, turn)


def prepare_handoff_chat(trust: HandoffTrust, mapping: HandoffSubjectMap,
                         replay: HandoffReplayStore, *, headers: tuple[tuple[bytes, bytes], ...],
                         body: bytes, method: str, path: str,
                         query_string: bytes = b"") -> HandoffChatContext:
    """Consume one signed request; never fallback to ordinary credentials.

    Called only after separate, trusted listener/transport policy enforcement.
    Read all raw header values to reject duplicate and conflicting auth.
    No protected side effects or public token are produced here.
    """
    if (type(headers) is not tuple or len(headers) > 128
            or method != "POST" or path != "/v1/chat/completions"
            or query_string != b""):
        raise HandoffDenied("handoff_chat_denied")
    assertions = []
    for pair in headers:
        if (type(pair) is not tuple or len(pair) != 2
                or type(pair[0]) is not bytes or type(pair[1]) is not bytes):
            raise HandoffDenied("handoff_chat_denied")
        name, value = pair
        name = name.lower()
        if name in _FORBIDDEN:
            raise HandoffDenied("handoff_chat_denied")
        if name == _ASSERTION:
            assertions.append(value)
    if len(assertions) != 1 or not 1 <= len(assertions[0]) <= 8192:
        raise HandoffDenied("handoff_chat_denied")
    try:
        token = assertions[0].decode("ascii")
        identity = map_verified_chat_once(trust, mapping, replay, token,
            body=body, method=method, path=path)
        return _build(identity, mapping)
    except Exception:
        raise HandoffDenied("handoff_chat_denied") from None


def revalidate_handoff_chat(context: HandoffChatContext, mapping: HandoffSubjectMap) -> None:
    """Recheck current mapping and live generation/role before trusted use.

    No re-consumption or expiry extension: this is for the already admitted
    HTTP request only, not permission to reuse it on a different request.
    """
    if type(context) is not HandoffChatContext:
        raise HandoffDenied("handoff_chat_denied")
    try:
        expected = _build(context.identity, mapping)
        if expected != context:
            raise HandoffDenied("handoff_chat_denied")
    except Exception:
        raise HandoffDenied("handoff_chat_denied") from None
