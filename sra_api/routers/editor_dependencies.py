from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, Header, HTTPException, status

from api.services.auth_store import (
    AUTH_STORE,
    ROLE_DATA_EDITOR,
    ROLE_DB_OPERATOR,
    ROLE_SUPERUSER,
    AuthUser,
    has_role_at_least,
    normalize_role,
    parse_token,
)
from api.services.editor_audit import append_audit_event
from api.services.vercel_mock_runtime import should_prefer_mock_runtime


def static_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "static" / filename


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="請先登入。")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or separator != " " or not token.strip() or " " in token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="請先登入。")
    return token.strip()


def scope_resource_id(user: AuthUser, resource_id: str) -> str:
    """Compatibility shim for mixed-version workers; agent routes no longer use it."""
    return resource_id


def current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    payload = parse_token(bearer_token(authorization))
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已失效，請重新登入。")
    username = str(payload.get("sub") or "")
    stored = AUTH_STORE.get_user(username)
    if not stored or stored.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="帳號尚未啟用。")
    if AUTH_STORE.is_token_denied(str(payload.get("jti") or "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已失效，請重新登入。")
    if not AUTH_STORE.is_token_current(username, int(payload.get("ver") or 0)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已失效，請重新登入。")
    mock_preview = bool(payload.get("mock_preview"))
    if mock_preview and not should_prefer_mock_runtime():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vercel mock preview token 已停用。")
    return AuthUser(username=username, role=normalize_role(str(stored.get("role") or "")), status="active", mock_preview=mock_preview)


def require_role(minimum_role: str, reason: str, detail: str) -> Callable[[AuthUser], AuthUser]:
    def dependency(user: AuthUser = Depends(current_user)) -> AuthUser:
        if not has_role_at_least(user.role, minimum_role):
            append_audit_event({
                "action": "authz.denied",
                "username": user.username,
                "role": user.role,
                "reason": reason,
            })
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        return user

    return dependency


require_data_editor = require_role(ROLE_DATA_EDITOR, "require_data_editor", "需要資料修改者以上權限。")
require_db_operator = require_role(ROLE_DB_OPERATOR, "require_db_operator", "需要資料庫操作者以上權限。")
require_superuser = require_role(ROLE_SUPERUSER, "require_superuser", "需要最高級全能者權限。")
