# api/routers/editor_auth.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from api.routers.editor_dependencies import bearer_token, current_user, require_superuser
from api.routers.editor_auth_logging import log_failed_login_attempt
from api.routers.editor_models import (
    ApprovePayload,
    AuthPayload,
    ChangePasswordPayload,
    ForgotPasswordPayload,
    RecoverPasswordPayload,
    ResetPasswordPayload,
)
from api.services import auth_store
from api.services.auth_store import AuthUser
from api.services.editor_audit import append_audit_event

router = APIRouter(tags=["editor"])
AUTH_FAILURE_MESSAGE = "帳號或密碼錯誤，或帳號尚未啟用。"
REGISTER_SUCCESS_MESSAGE = "若資料符合申請條件，帳號申請已送出；請等待系統管理員審核。"
REGISTER_THROTTLE_SCOPE = "register"


def _client_host(request: Request) -> str | None:
    return request.client.host if request.client else None


def _rate_limit_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="嘗試次數過多，請稍後再試。",
        headers={"Retry-After": str(max(1, retry_after))},
    )



@router.post("/v1/auth/register")
def register(payload: AuthPayload, request: Request) -> dict[str, Any]:
    client_host = _client_host(request)
    retry_after = auth_store.AUTH_STORE.throttle_retry_after(REGISTER_THROTTLE_SCOPE, None, client_host)
    if retry_after:
        append_audit_event({
            "action": "auth.user_registered",
            "username": payload.username,
            "success": False,
            "reason": "rate_limited",
            "client_host": client_host,
        })
        raise _rate_limit_exception(retry_after)

    success = False
    reason = "ok"
    try:
        auth_store.AUTH_STORE.register(
            payload.username,
            payload.password,
            full_name=payload.full_name,
            department=payload.department,
            note=payload.note,
        )
        success = True
    except ValueError as exc:
        reason = "duplicate_username" if str(exc) == "帳號已存在。" else "invalid_request"
        if reason != "duplicate_username":
            append_audit_event({
                "action": "auth.user_registered",
                "username": payload.username,
                "success": False,
                "reason": reason,
                "client_host": client_host,
            })
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    append_audit_event({
        "action": "auth.user_registered",
        "username": payload.username,
        "success": success,
        "reason": reason,
        "client_host": client_host,
    })
    retry_after = auth_store.AUTH_STORE.record_auth_failure(REGISTER_THROTTLE_SCOPE, None, client_host)
    if retry_after:
        # Apply the block to following attempts while preserving the generic response for this one.
        pass
    return {"message": REGISTER_SUCCESS_MESSAGE}


@router.post("/v1/auth/login")
def login(payload: AuthPayload, request: Request) -> dict[str, Any]:
    client_host = _client_host(request)
    user_agent = request.headers.get("user-agent")
    retry_after = auth_store.AUTH_STORE.throttle_retry_after("login", payload.username, client_host)
    if retry_after:
        auth_store.AUTH_STORE.record_login_audit(
            payload.username,
            success=False,
            reason="rate_limited",
            client_host=client_host,
            user_agent=user_agent,
        )
        log_failed_login_attempt(payload.username, reason="rate_limited", client_host=client_host, user_agent=user_agent)
        append_audit_event({"action": "auth.login", "username": payload.username, "success": False, "reason": "rate_limited", "client_host": client_host})
        raise _rate_limit_exception(retry_after)

    user = auth_store.AUTH_STORE.authenticate(payload.username, payload.password)
    if user is None:
        retry_after = auth_store.AUTH_STORE.record_auth_failure("login", payload.username, client_host)
        auth_store.AUTH_STORE.record_login_audit(
            payload.username,
            success=False,
            reason="invalid_credentials",
            client_host=client_host,
            user_agent=user_agent,
        )
        log_failed_login_attempt(payload.username, reason="invalid_credentials", client_host=client_host, user_agent=user_agent)
        append_audit_event({"action": "auth.login", "username": payload.username, "success": False, "reason": "invalid_credentials", "client_host": client_host})
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_FAILURE_MESSAGE)
    if user.status != "active":
        retry_after = auth_store.AUTH_STORE.record_auth_failure("login", payload.username, client_host)
        auth_store.AUTH_STORE.record_login_audit(
            payload.username,
            success=False,
            reason="inactive_account",
            role=user.role,
            status_value=user.status,
            client_host=client_host,
            user_agent=user_agent,
        )
        log_failed_login_attempt(payload.username, reason="inactive_account", client_host=client_host, user_agent=user_agent, role=user.role, status_value=user.status)
        append_audit_event({"action": "auth.login", "username": payload.username, "success": False, "reason": "inactive_account", "status": user.status, "client_host": client_host})
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_FAILURE_MESSAGE)
    auth_store.AUTH_STORE.clear_auth_failures("login", payload.username, client_host)
    auth_store.AUTH_STORE.record_login_audit(
        payload.username,
        success=True,
        reason="ok",
        role=user.role,
        status_value=user.status,
        client_host=client_host,
        user_agent=user_agent,
    )
    append_audit_event({"action": "auth.login", "username": payload.username, "success": True, "role": user.role, "client_host": client_host})
    return {"access_token": auth_store.create_token(user), "token_type": "bearer", "user": user.__dict__}


@router.post("/v1/auth/logout")
def logout(
    request: Request,
    user: AuthUser = Depends(current_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    payload = auth_store.parse_token(bearer_token(authorization))
    if payload:
        auth_store.AUTH_STORE.deny_token(payload)
    append_audit_event({"action": "auth.logout", "username": user.username, "client_host": _client_host(request)})
    return {"message": "已登出；此 token 已失效。"}


@router.post("/v1/auth/change-password")
def change_password(payload: ChangePasswordPayload, request: Request, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    try:
        updated = auth_store.AUTH_STORE.change_password(user.username, payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({"action": "auth.password_changed", "username": user.username, "client_host": _client_host(request)})
    return {"user": updated, "message": "密碼已變更，既有 token 已失效；請重新登入。"}


@router.post("/v1/auth/forgot-password")
def forgot_password(payload: ForgotPasswordPayload, request: Request) -> dict[str, Any]:
    # Do not issue or return a reset token from the public endpoint. Returning a token
    # here would let anyone who knows a username take over that account.
    append_audit_event({"action": "auth.password_reset_requested", "username": payload.username, "client_host": _client_host(request)})
    return {"message": "若帳號存在，已收到忘記密碼申請；請聯絡系統管理員核身後取得一次性重設 token。"}


@router.post("/v1/auth/reset-password")
def recover_password(payload: RecoverPasswordPayload, request: Request) -> dict[str, Any]:
    client_host = _client_host(request)
    retry_after = auth_store.AUTH_STORE.throttle_retry_after("password_reset", payload.username, client_host)
    if retry_after:
        append_audit_event({"action": "auth.password_recovered", "username": payload.username, "success": False, "reason": "rate_limited", "client_host": client_host})
        raise _rate_limit_exception(retry_after)
    try:
        updated = auth_store.AUTH_STORE.recover_password(payload.username, payload.reset_token, payload.new_password)
    except ValueError as exc:
        retry_after = auth_store.AUTH_STORE.record_auth_failure("password_reset", payload.username, client_host)
        append_audit_event({"action": "auth.password_recovered", "username": payload.username, "success": False, "reason": "invalid_or_expired_token", "client_host": client_host})
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.AUTH_STORE.clear_auth_failures("password_reset", payload.username, client_host)
    append_audit_event({"action": "auth.password_recovered", "username": payload.username, "success": True, "client_host": client_host})
    return {"user": updated, "message": "密碼已重設，既有 token 已失效；請重新登入。"}


@router.get("/v1/auth/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"user": user.__dict__, "role_options": auth_store.public_role_options()}


@router.get("/v1/auth/users")
def list_users(_: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"users": auth_store.AUTH_STORE.list_users(), "role_options": auth_store.public_role_options()}


@router.post("/v1/auth/users/{username}/approve")
def approve_user(username: str, payload: ApprovePayload, request: Request, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        approved = auth_store.AUTH_STORE.approve_user(username, payload.role, approved_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_approved",
        "username": username,
        "actor": user.username,
        "role": payload.role,
        "client_host": _client_host(request),
    })
    return {"user": approved}


@router.post("/v1/auth/users/{username}/reject")
def reject_user(username: str, request: Request, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        rejected = auth_store.AUTH_STORE.reject_user(username, rejected_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_rejected",
        "username": username,
        "actor": user.username,
        "client_host": _client_host(request),
    })
    return {"user": rejected}


@router.delete("/v1/auth/users/{username}")
def delete_user(username: str, request: Request, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    if username == user.username:
        raise HTTPException(status_code=400, detail="不可刪除目前登入的超級使用者。")
    try:
        deleted = auth_store.AUTH_STORE.delete_user(username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_deleted",
        "username": username,
        "actor": user.username,
        "client_host": _client_host(request),
    })
    return {"user": deleted}


@router.post("/v1/auth/users/{username}/password-reset-token")
def issue_password_reset_token(username: str, request: Request, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    reset_token = auth_store.AUTH_STORE.request_password_reset(username)
    if not reset_token:
        raise HTTPException(status_code=404, detail="帳號不存在或尚未啟用，無法建立重設 token。")
    append_audit_event({"action": "auth.password_reset_token_issued", "username": username, "actor": user.username, "client_host": _client_host(request)})
    return {"username": username, "reset_token": reset_token, "message": "一次性重設 token 已建立；請用安全管道交付給該使用者。"}


@router.post("/v1/auth/users/{username}/reset-password")
def reset_user_password(username: str, payload: ResetPasswordPayload, request: Request, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        updated = auth_store.AUTH_STORE.reset_user_password(username, payload.new_password, reset_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({"action": "auth.password_reset_by_superuser", "username": username, "actor": user.username, "client_host": _client_host(request)})
    return {"user": updated, "message": "密碼已由超級使用者重設，該帳號既有 token 已失效。"}


@router.get("/v1/auth/login-audit")
def list_login_audit(limit: int = Query(100, ge=1, le=1000), _: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"events": auth_store.AUTH_STORE.list_login_audit(limit)}
