from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException


def load_audit_records(limit: int = 5000) -> list[dict[str, Any]]:
    from api.services.editor_audit import audit_log_path

    path = audit_log_path()
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    if len(records) > limit:
        return records[-limit:]
    return records


def _parse_ts(ts_text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts_text or '').replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_chart_bucket(bucket: str | None) -> tuple[str, str]:
    value = (bucket or 'day').strip().lower().replace('-', '_')
    aliases = {
        '1h': 'hour',
        'hourly': 'hour',
        '6h': '6_hours',
        '6_hour': '6_hours',
        '12h': '12_hours',
        '12_hour': '12_hours',
        'daily': 'day',
        'weekly': 'week',
        'monthly': 'month',
    }
    normalized = aliases.get(value, value)
    labels = {
        'hour': '每小時',
        '6_hours': '每 6 小時',
        '12_hours': '每 12 小時',
        'day': '每日',
        'week': '每週',
        'month': '每月',
    }
    if normalized not in labels:
        raise HTTPException(status_code=400, detail='不支援的 audit 統計區間。')
    return normalized, labels[normalized]


def _bucket_start(dt: datetime, bucket: str, timezone_offset_minutes: int = 0) -> datetime:
    dt = dt.astimezone(timezone.utc) + timedelta(minutes=timezone_offset_minutes)
    if bucket == 'hour':
        return dt.replace(minute=0, second=0, microsecond=0)
    if bucket == '6_hours':
        return dt.replace(hour=(dt.hour // 6) * 6, minute=0, second=0, microsecond=0)
    if bucket == '12_hours':
        return dt.replace(hour=(dt.hour // 12) * 12, minute=0, second=0, microsecond=0)
    if bucket == 'week':
        start = dt - timedelta(days=dt.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == 'month':
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def build_audit_time_series(rows: list[dict[str, Any]], bucket: str = 'day', timezone_offset_minutes: int = 0) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        dt = _parse_ts(str(row.get('ts') or ''))
        if not dt:
            continue
        key = _bucket_start(dt, bucket, timezone_offset_minutes).isoformat().replace('+00:00', 'Z')
        counts[key] = counts.get(key, 0) + 1
    return [{'bucket_start': key, 'count': counts[key]} for key in sorted(counts)]


def build_usage_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    by_index: dict[str, int] = {}
    by_user: dict[str, int] = {}
    by_client_host: dict[str, int] = {}
    changed_paths_total = 0
    for r in rows:
        action = str(r.get("action") or "unknown")
        idx = str(r.get("index") or "-")
        uname = str(r.get("username") or "-")
        client_host = str(r.get("client_host") or "-")
        by_action[action] = by_action.get(action, 0) + 1
        by_index[idx] = by_index.get(idx, 0) + 1
        by_user[uname] = by_user.get(uname, 0) + 1
        by_client_host[client_host] = by_client_host.get(client_host, 0) + 1
        changed_paths_total += len(r.get("changed_paths") or [])
    return {
        "total_events": len(rows),
        "changed_paths_total": changed_paths_total,
        "by_action": by_action,
        "by_index": by_index,
        "by_user": by_user,
        "by_client_host": by_client_host,
    }


def filter_audit_records(
    records: list[dict[str, Any]],
    *,
    username: str | None = None,
    action: str | None = None,
    action_prefix: str | None = None,
    index: str | None = None,
    id: str | None = None,
    changed_path: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[dict[str, Any]]:
    username_values = [part.strip().lower() for part in (username or "").split(',') if part.strip()]
    action_q = (action or "").strip().lower()
    action_prefix_q = (action_prefix or "").strip().lower()
    index_q = (index or "").strip()
    id_q = (id or "").strip()
    path_q = (changed_path or "").strip().lower()
    start_q = (start_ts or "").strip()
    end_q = (end_ts or "").strip()

    def in_range(ts_text: str) -> bool:
        if not (start_q or end_q):
            return True
        try:
            ts = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
        except Exception:
            return False
        if start_q:
            try:
                start = datetime.fromisoformat(start_q.replace("Z", "+00:00"))
                if ts < start:
                    return False
            except Exception:
                raise HTTPException(status_code=400, detail="start_ts 格式錯誤，請使用 ISO 8601。")
        if end_q:
            try:
                end = datetime.fromisoformat(end_q.replace("Z", "+00:00"))
                if ts > end:
                    return False
            except Exception:
                raise HTTPException(status_code=400, detail="end_ts 格式錯誤，請使用 ISO 8601。")
        return True

    filtered: list[dict[str, Any]] = []
    for r in records:
        if username_values and str(r.get("username") or "").lower() not in username_values:
            continue
        action_value = str(r.get("action") or "").lower()
        if action_q and action_q not in action_value:
            continue
        if action_prefix_q and not action_value.startswith(action_prefix_q):
            continue
        if index_q and index_q != str(r.get("index") or ""):
            continue
        if id_q and id_q != str(r.get("id") or ""):
            continue
        if path_q:
            paths = r.get("changed_paths") or []
            if not any(path_q in str(p or "").lower() for p in paths):
                continue
        if not in_range(str(r.get("ts") or "")):
            continue
        filtered.append(r)

    filtered.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    return filtered
