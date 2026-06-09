from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query, status

from .auth_store import AUTH_STORE, AuthUser, create_token, parse_token
from .dependencies import bearer_token, current_user, require_superuser
from .models import (
    ApprovePayload,
    AuthPayload,
    ChangePasswordPayload,
    ForgotPasswordPayload,
    RecoverPasswordPayload,
    ResetPasswordPayload,
)

router = APIRouter(tags=["auth"])


@router.post("/v1/auth/register")
def register(payload: AuthPayload) -> dict[str, Any]:
    try:
        user = AUTH_STORE.register(
            payload.username,
            payload.password,
            full_name=payload.full_name,
            department=payload.department,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user, "message": "帳號已建立，狀態為 pending；請等待超級使用者審核。"}


@router.post("/v1/auth/login")
def login(payload: AuthPayload, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user = AUTH_STORE.authenticate(payload.username, payload.password)
    if user is None:
        AUTH_STORE.record_login_audit(payload.username, success=False, reason="invalid_credentials", client_host=client_host, user_agent=user_agent)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="帳號或密碼錯誤。")
    if user.status != "active":
        AUTH_STORE.record_login_audit(payload.username, success=False, reason="inactive_account", role=user.role, status_value=user.status, client_host=client_host, user_agent=user_agent)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"帳號狀態為 {user.status}，尚不可使用。")
    AUTH_STORE.record_login_audit(payload.username, success=True, reason="ok", role=user.role, status_value=user.status, client_host=client_host, user_agent=user_agent)
    return {"access_token": create_token(user), "token_type": "bearer", "user": user.__dict__}


@router.post("/v1/auth/logout")
def logout(user: AuthUser = Depends(current_user), authorization: str | None = Header(default=None)) -> dict[str, Any]:
    payload = parse_token(bearer_token(authorization))
    if payload:
        AUTH_STORE.deny_token(payload)
    return {"message": "已登出；此 token 已失效。"}


@router.post("/v1/auth/change-password")
def change_password(payload: ChangePasswordPayload, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    try:
        updated = AUTH_STORE.change_password(user.username, payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": updated, "message": "密碼已變更，既有 token 已失效；請重新登入。"}


@router.post("/v1/auth/forgot-password")
def forgot_password(payload: ForgotPasswordPayload) -> dict[str, Any]:
    # Do not issue or return a reset token from the public endpoint. Returning a token
    # here would let anyone who knows a username take over that account.
    return {"message": "若帳號存在，已收到忘記密碼申請；請聯絡系統管理員核身後取得一次性重設 token。"}


@router.post("/v1/auth/reset-password")
def recover_password(payload: RecoverPasswordPayload) -> dict[str, Any]:
    try:
        updated = AUTH_STORE.recover_password(payload.username, payload.reset_token, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": updated, "message": "密碼已重設，既有 token 已失效；請重新登入。"}


@router.get("/v1/auth/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"user": user.__dict__}


@router.get("/v1/auth/users")
def list_users(_: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"users": AUTH_STORE.list_users()}


@router.post("/v1/auth/users/{username}/approve")
def approve_user(username: str, payload: ApprovePayload, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        approved = AUTH_STORE.approve_user(username, payload.role, approved_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": approved}


@router.post("/v1/auth/users/{username}/reject")
def reject_user(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        rejected = AUTH_STORE.reject_user(username, rejected_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user": rejected}


@router.delete("/v1/auth/users/{username}")
def delete_user(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    if username == user.username:
        raise HTTPException(status_code=400, detail="不可刪除目前登入的超級使用者。")
    try:
        deleted = AUTH_STORE.delete_user(username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user": deleted}


@router.post("/v1/auth/users/{username}/password-reset-token")
def issue_password_reset_token(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    reset_token = AUTH_STORE.request_password_reset(username)
    if not reset_token:
        raise HTTPException(status_code=404, detail="帳號不存在或尚未啟用，無法建立重設 token。")
    return {"username": username, "reset_token": reset_token, "message": "一次性重設 token 已建立；請用安全管道交付給該使用者。"}


@router.post("/v1/auth/users/{username}/reset-password")
def reset_user_password(username: str, payload: ResetPasswordPayload, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        updated = AUTH_STORE.reset_user_password(username, payload.new_password, reset_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": updated, "message": "密碼已由超級使用者重設，該帳號既有 token 已失效。"}


@router.get("/v1/auth/login-audit")
def list_login_audit(limit: int = Query(100, ge=1, le=1000), _: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"events": AUTH_STORE.list_login_audit(limit)}
