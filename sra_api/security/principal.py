from __future__ import annotations

from collections.abc import Callable
from fastapi import Depends, Header, HTTPException, Request

import api.services.auth_store as auth_store_module
from api.security.models import AuthPrincipal
from api.security.scopes import scopes_for_user_role, validate_scopes
import api.security.service_key_store as service_key_module
from api.security.signed_urls import verify_resource_token
from api.services.editor_audit import append_audit_event


def _audit_denied(action: str, *, reason: str, principal: AuthPrincipal | None = None, required_scopes=()) -> None:
    """Write only non-secret security-boundary metadata."""
    event = {"action": action, "reason": reason}
    if principal is not None:
        event.update({"principal_kind": principal.kind, "subject": principal.subject})
    if required_scopes:
        event["required_scopes"] = sorted(required_scopes)
    append_audit_event(event)


def optional_principal(authorization: str | None = Header(default=None)) -> AuthPrincipal | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or separator != " " or not token or " " in token:
        _audit_denied("security.authentication_denied", reason="malformed_authorization")
        raise HTTPException(401, "Invalid credential")
    if token.startswith("sra_sk_"):
        item = service_key_module.SERVICE_KEY_STORE.resolve(token)
        if not item:
            _audit_denied("security.authentication_denied", reason="invalid_service_key")
            raise HTTPException(401, "Invalid credential")
        return AuthPrincipal("service", item["name"], None, frozenset(item["scopes"]), item["key_id"])
    payload = auth_store_module.parse_token(token)
    if not payload:
        _audit_denied("security.authentication_denied", reason="invalid_user_token")
        raise HTTPException(401, "Invalid credential")
    username = str(payload.get("sub") or "")
    stored = auth_store_module.AUTH_STORE.get_user(username)
    if not stored or stored.get("status") != "active":
        _audit_denied("security.authentication_denied", reason="inactive_user")
        raise HTTPException(401, "Invalid credential")
    if auth_store_module.AUTH_STORE.is_token_denied(str(payload.get("jti") or "")):
        _audit_denied("security.authentication_denied", reason="denied_user_token")
        raise HTTPException(401, "Invalid credential")
    if not auth_store_module.AUTH_STORE.is_token_current(username, int(payload.get("ver") or 0)):
        _audit_denied("security.authentication_denied", reason="stale_user_token")
        raise HTTPException(401, "Invalid credential")
    role = auth_store_module.normalize_role(stored.get("role"))
    return AuthPrincipal("user", username, role, scopes_for_user_role(role), str(payload.get("jti") or "") or None)


def current_principal(principal: AuthPrincipal | None = Depends(optional_principal)) -> AuthPrincipal:
    if principal is None:
        _audit_denied("security.authentication_denied", reason="missing_credential")
        raise HTTPException(401, "Authentication required")
    return principal


def require_scopes(*required: str) -> Callable:
    wanted = validate_scopes(required)
    def dependency(principal: AuthPrincipal = Depends(current_principal)) -> AuthPrincipal:
        if not wanted.issubset(principal.scopes):
            _audit_denied(
                "security.authorization_denied",
                reason="insufficient_scope",
                principal=principal,
                required_scopes=wanted,
            )
            raise HTTPException(403, "Insufficient scope")
        return principal
    return dependency


def require_principal_or_capability(
    request: Request,
    principal: AuthPrincipal | None,
    *,
    required_scope: str,
    resource_type: str,
    binding: dict[str, str],
    allowed_query_keys: set[str],
) -> bool:
    """Authorize a direct principal or an exact, canonical browser capability.

    Returns True for capability mode.  Resource lookup must happen afterwards.
    An invalid Authorization header is rejected by ``optional_principal`` and
    therefore can never fall through to this function's capability branch.
    """
    if principal is not None:
        if required_scope not in principal.scopes:
            _audit_denied(
                "security.authorization_denied",
                reason="insufficient_scope",
                principal=principal,
                required_scopes={required_scope},
            )
            raise HTTPException(403, "Insufficient scope")
        return False
    keys = set(request.query_params.keys())
    if not keys.issubset(allowed_query_keys | {"sig"}):
        raise HTTPException(401, "Invalid capability parameters")
    if any(len(request.query_params.getlist(key)) != 1 for key in keys):
        raise HTTPException(401, "Invalid capability parameters")
    sigs = request.query_params.getlist("sig")
    if len(sigs) != 1:
        raise HTTPException(401, "Valid capability required")
    try:
        verify_resource_token(sigs[0], resource_type, **binding)
    except ValueError as exc:
        raise HTTPException(401, "Invalid capability") from exc
    return True
