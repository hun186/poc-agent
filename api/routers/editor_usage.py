# api/routers/editor_usage.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.routers.editor_dependencies import current_user
from api.services.auth_store import AuthUser
from api.services.editor_audit_queries import (
    build_audit_time_series,
    build_usage_stats,
    filter_audit_records,
    load_audit_records,
    normalize_chart_bucket,
)

router = APIRouter(tags=["editor"])


@router.get("/v1/editor/usage-stats")
def usage_stats(
    category: str = Query("all", description="統計類別：all、document、account"),
    username: str | None = Query(None, description="依使用者篩選；非 superuser 一律限定自己"),
    action: str | None = Query(None, description="依操作類型篩選"),
    index: str | None = Query(None, description="依 index 篩選"),
    start_ts: str | None = Query(None, description="起始時間（ISO 8601）"),
    end_ts: str | None = Query(None, description="結束時間（ISO 8601）"),
    chart_bucket: str = Query("day", description="統計曲線區間：hour、6_hours、12_hours、day、week、month"),
    events_limit: int = Query(100, ge=1, le=500, description="回傳套用同一篩選條件的 audit 事件筆數"),
    timezone_offset_minutes: int = 0,
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    records = load_audit_records(limit=20000)
    mine = [r for r in records if str(r.get("username") or "") == user.username]
    out = {"me": build_usage_stats(mine)}
    if user.role == "superuser":
        out["all"] = build_usage_stats(records)

    normalized_bucket, bucket_label = normalize_chart_bucket(chart_bucket)
    category_value = (category or "all").strip().lower()
    action_prefix = ""
    if category_value == "document":
        action_prefix = "editor."
    elif category_value == "account":
        action_prefix = "auth."
    elif category_value != "all":
        raise HTTPException(status_code=400, detail="category 僅支援 all、document、account。")

    filtered_username = username if user.role == "superuser" else user.username
    filtered = filter_audit_records(
        records,
        username=filtered_username,
        action=action,
        action_prefix=action_prefix or None,
        index=index,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    out["filtered"] = {
        "category": category_value,
        "stats": build_usage_stats(filtered),
        "series": build_audit_time_series(filtered, normalized_bucket, timezone_offset_minutes),
        "events": filtered[:events_limit],
        "events_total": len(filtered),
        "events_limit": events_limit,
        "chart_bucket": normalized_bucket,
        "chart_bucket_label": bucket_label,
        "timezone_offset_minutes": timezone_offset_minutes,
        "is_restricted_to_self": user.role != "superuser",
    }
    return out


@router.get("/v1/editor/audit-logs")
def list_audit_logs(
    username: str | None = Query(None, description="依操作者帳號篩選"),
    action: str | None = Query(None, description="依操作類型篩選"),
    action_prefix: str | None = Query(None, description="依操作類型 prefix 篩選，例如 editor. 或 auth."),
    index: str | None = Query(None, description="依 index 篩選"),
    id: str | None = Query(None, description="依文件 ID 篩選"),
    changed_path: str | None = Query(None, description="依異動欄位路徑篩選（部分比對）"),
    start_ts: str | None = Query(None, description="起始時間（ISO 8601）"),
    end_ts: str | None = Query(None, description="結束時間（ISO 8601）"),
    limit: int = Query(100, ge=1, le=500),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    action_prefix_value = (action_prefix or "").strip().lower()
    if user.role != "superuser" and not action_prefix_value.startswith("auth."):
        raise HTTPException(status_code=403, detail="一般使用者只能查詢自己的帳號操作紀錄。")
    effective_username = username if user.role == "superuser" else user.username
    records = load_audit_records(limit=5000)
    filtered = filter_audit_records(
        records,
        username=effective_username,
        action=action,
        action_prefix=action_prefix,
        index=index,
        id=id,
        changed_path=changed_path,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    return {"total": len(filtered), "limit": limit, "hits": filtered[:limit]}
