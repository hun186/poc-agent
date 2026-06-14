from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query, status

from .auth_store import AUTH_STORE, AuthUser, create_token, parse_token, public_role_options
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
AUTH_FAILURE_MESSAGE = "帳號或密碼錯誤，或帳號尚未啟用。"


def _rate_limit_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="登入或密碼重設嘗試次數過多，請稍後再試。",
        headers={"Retry-After": str(max(1, retry_after))},
    )


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
    retry_after = AUTH_STORE.throttle_retry_after("login", payload.username, client_host)
    if retry_after:
        AUTH_STORE.record_login_audit(payload.username, success=False, reason="rate_limited", client_host=client_host, user_agent=user_agent)
        raise _rate_limit_exception(retry_after)

    user = AUTH_STORE.authenticate(payload.username, payload.password)
    if user is None:
        retry_after = AUTH_STORE.record_auth_failure("login", payload.username, client_host)
        AUTH_STORE.record_login_audit(payload.username, success=False, reason="invalid_credentials", client_host=client_host, user_agent=user_agent)
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_FAILURE_MESSAGE)
    if user.status != "active":
        retry_after = AUTH_STORE.record_auth_failure("login", payload.username, client_host)
        AUTH_STORE.record_login_audit(payload.username, success=False, reason="inactive_account", role=user.role, status_value=user.status, client_host=client_host, user_agent=user_agent)
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_FAILURE_MESSAGE)
    AUTH_STORE.clear_auth_failures("login", payload.username, client_host)
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
def recover_password(payload: RecoverPasswordPayload, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else None
    retry_after = AUTH_STORE.throttle_retry_after("password_reset", payload.username, client_host)
    if retry_after:
        raise _rate_limit_exception(retry_after)
    try:
        updated = AUTH_STORE.recover_password(payload.username, payload.reset_token, payload.new_password)
    except ValueError as exc:
        retry_after = AUTH_STORE.record_auth_failure("password_reset", payload.username, client_host)
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AUTH_STORE.clear_auth_failures("password_reset", payload.username, client_host)
    return {"user": updated, "message": "密碼已重設，既有 token 已失效；請重新登入。"}


@router.get("/v1/auth/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"user": user.__dict__, "role_options": public_role_options()}


@router.get("/v1/auth/users")
def list_users(_: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"users": AUTH_STORE.list_users(), "role_options": public_role_options()}


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
def list_login_audit(
    limit: int = Query(100, ge=1, le=1000),
    username: str | None = Query(None, description="superuser 可指定帳號；一般使用者固定自己"),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    events = AUTH_STORE.list_login_audit(limit)
    effective_username = username if user.role == "superuser" else user.username
    if effective_username:
        events = [event for event in events if str(event.get("username") or "") == effective_username]
    return {"events": events, "is_restricted_to_self": user.role != "superuser"}


def _parse_audit_ts(value: Any) -> float:
    from datetime import datetime

    if not value:
        return 0.0
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _bucket_key(ts: str, bucket: str) -> str:
    from datetime import datetime, timezone, timedelta

    text = str(ts or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(timezone.utc)
    if bucket == "hour":
        local_dt = local_dt.replace(minute=0, second=0, microsecond=0)
    elif bucket == "6_hours":
        local_dt = local_dt.replace(hour=(local_dt.hour // 6) * 6, minute=0, second=0, microsecond=0)
    elif bucket == "12_hours":
        local_dt = local_dt.replace(hour=(local_dt.hour // 12) * 12, minute=0, second=0, microsecond=0)
    elif bucket == "week":
        local_dt = (local_dt - timedelta(days=local_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif bucket == "month":
        local_dt = local_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        local_dt = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_dt.isoformat()


def _account_usage_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    by_user: dict[str, int] = {}
    for event in events:
        action = str(event.get("action") or "auth.login")
        username = str(event.get("username") or "")
        by_action[action] = by_action.get(action, 0) + 1
        if username:
            by_user[username] = by_user.get(username, 0) + 1
    return {"total_events": len(events), "changed_paths_total": 0, "by_action": by_action, "by_index": {}, "by_user": by_user}


@router.get("/v1/editor/usage-stats")
def account_usage_stats(
    category: str = Query("account"),
    username: str | None = Query(None),
    action: str | None = Query(None),
    chart_bucket: str = Query("day"),
    events_limit: int = Query(100, ge=1, le=500),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    if category not in {"account", "all"}:
        raise HTTPException(status_code=400, detail="portable_auth_pack 僅提供帳號操作記錄統計。")
    bucket = chart_bucket if chart_bucket in {"hour", "6_hours", "12_hours", "day", "week", "month"} else "day"
    events = AUTH_STORE.list_login_audit(1000)
    for event in events:
        event.setdefault("action", "auth.login")
    effective_username = username if user.role == "superuser" else user.username
    if effective_username:
        events = [event for event in events if str(event.get("username") or "") == effective_username]
    if action:
        needle = action.lower()
        events = [event for event in events if needle in str(event.get("action") or "auth.login").lower() or needle in str(event.get("reason") or "").lower()]
    events = sorted(events, key=lambda event: _parse_audit_ts(event.get("ts")), reverse=True)
    counts: dict[str, int] = {}
    for event in events:
        key = _bucket_key(str(event.get("ts") or ""), bucket)
        counts[key] = counts.get(key, 0) + 1
    series = [{"bucket": key, "count": counts[key]} for key in sorted(counts)]
    filtered = {
        "category": "account",
        "stats": _account_usage_stats(events),
        "series": series,
        "events": events[:events_limit],
        "events_total": len(events),
        "events_limit": events_limit,
        "chart_bucket": bucket,
        "chart_bucket_label": bucket,
        "is_restricted_to_self": user.role != "superuser",
    }
    mine = [event for event in AUTH_STORE.list_login_audit(1000) if str(event.get("username") or "") == user.username]
    output = {"me": _account_usage_stats(mine), "filtered": filtered}
    if user.role == "superuser":
        output["all"] = _account_usage_stats(AUTH_STORE.list_login_audit(1000))
    return output
