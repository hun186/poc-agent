from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth_store import AUTH_STORE, AuthUser
from .dependencies import current_user

router = APIRouter(tags=["auth"])


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
    by_client_host: dict[str, int] = {}
    for event in events:
        action = str(event.get("action") or "auth.login")
        username = str(event.get("username") or "")
        client_host = str(event.get("client_host") or "-")
        by_action[action] = by_action.get(action, 0) + 1
        by_client_host[client_host] = by_client_host.get(client_host, 0) + 1
        if username:
            by_user[username] = by_user.get(username, 0) + 1
    return {"total_events": len(events), "changed_paths_total": 0, "by_action": by_action, "by_index": {}, "by_user": by_user, "by_client_host": by_client_host}


@router.get("/v1/editor/usage-stats")
def account_usage_stats(
    category: str = Query("account"),
    username: str | None = Query(None),
    action: str | None = Query(None),
    client_host: str | None = Query(None),
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
    client_host_values = [part.strip().lower() for part in (client_host or "").split(",") if part.strip()]
    if client_host_values:
        events = [event for event in events if str(event.get("client_host") or "-").lower() in client_host_values]
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
