from __future__ import annotations

from collections.abc import Callable
from fastapi import Depends, Header, HTTPException

import api.services.auth_store as auth_store_module
from api.security.models import AuthPrincipal
from api.security.scopes import scopes_for_user_role, validate_scopes
import api.security.service_key_store as service_key_module


def optional_principal(authorization: str | None = Header(default=None)) -> AuthPrincipal | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or separator != " " or not token or " " in token:
        raise HTTPException(401, "Invalid credential")
    if token.startswith("sra_sk_"):
        item = service_key_module.SERVICE_KEY_STORE.resolve(token)
        if not item:
            raise HTTPException(401, "Invalid credential")
        return AuthPrincipal("service", item["name"], None, frozenset(item["scopes"]), item["key_id"])
    payload = auth_store_module.parse_token(token)
    if not payload:
        raise HTTPException(401, "Invalid credential")
    username = str(payload.get("sub") or "")
    stored = auth_store_module.AUTH_STORE.get_user(username)
    if not stored or stored.get("status") != "active": raise HTTPException(401, "Invalid credential")
    if auth_store_module.AUTH_STORE.is_token_denied(str(payload.get("jti") or "")): raise HTTPException(401, "Invalid credential")
    if not auth_store_module.AUTH_STORE.is_token_current(username, int(payload.get("ver") or 0)): raise HTTPException(401, "Invalid credential")
    role = auth_store_module.normalize_role(stored.get("role"))
    return AuthPrincipal("user", username, role, scopes_for_user_role(role), str(payload.get("jti") or "") or None)


def current_principal(principal: AuthPrincipal | None = Depends(optional_principal)) -> AuthPrincipal:
    if principal is None: raise HTTPException(401, "Authentication required")
    return principal


def require_scopes(*required: str) -> Callable:
    wanted = validate_scopes(required)
    def dependency(principal: AuthPrincipal = Depends(current_principal)) -> AuthPrincipal:
        if not wanted.issubset(principal.scopes): raise HTTPException(403, "Insufficient scope")
        return principal
    return dependency
