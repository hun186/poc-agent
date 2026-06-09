from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from .auth_store import AUTH_STORE, AuthUser, parse_token


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="請先登入。")
    return authorization.split(" ", 1)[1].strip()


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
    return AuthUser(username=username, role=str(stored.get("role") or "user"), status="active")


def require_superuser(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "superuser":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要超級使用者權限。")
    return user
