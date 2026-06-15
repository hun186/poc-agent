from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any

_AUDIT_CHART_BUCKETS: dict[str, dict[str, str]] = {
    "hour": {
        "label": "每小時",
        "sql": "DATEADD(hour, DATEDIFF(hour, 0, processed_at), 0)",
    },
    "6_hours": {
        "label": "每 6 小時",
        "sql": "DATEADD(hour, (DATEDIFF(hour, 0, processed_at) / 6) * 6, 0)",
    },
    "12_hours": {
        "label": "每 12 小時",
        "sql": "DATEADD(hour, (DATEDIFF(hour, 0, processed_at) / 12) * 12, 0)",
    },
    "day": {
        "label": "每日",
        "sql": "CONVERT(datetime2, CONVERT(date, processed_at))",
    },
    "week": {
        "label": "每週",
        "sql": (
            "DATEADD(day, "
            "-(DATEDIFF(day, CAST('19000101' AS date), CONVERT(date, processed_at)) % 7), "
            "CONVERT(datetime2, CONVERT(date, processed_at)))"
        ),
    },
    "month": {
        "label": "每月",
        "sql": "CONVERT(datetime2, DATEFROMPARTS(YEAR(processed_at), MONTH(processed_at), 1))",
    },
}


def _audit_chart_bucket(bucket: str | None) -> tuple[str, str, str]:
    normalized = str(bucket or "day").strip().lower().replace("-", "_")
    aliases = {
        "daily": "day",
        "date": "day",
        "hourly": "hour",
        "6h": "6_hours",
        "six_hours": "6_hours",
        "12h": "12_hours",
        "weekly": "week",
        "monthly": "month",
    }
    normalized = aliases.get(normalized, normalized)
    meta = _AUDIT_CHART_BUCKETS.get(normalized)
    if not meta:
        allowed = "、".join(_AUDIT_CHART_BUCKETS)
        raise ValueError(f"不支援的 audit 統計區間：{bucket}；可用值：{allowed}")
    return normalized, meta["label"], meta["sql"]


def _coerce_utc_datetime(
    value: str | datetime | date | None, *, end_of_day: bool = False
) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.max if end_of_day else time.min)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            if len(text) == 10:
                dt = datetime.combine(
                    date.fromisoformat(text), time.max if end_of_day else time.min
                )
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("時間格式錯誤，請使用 ISO 8601 或 YYYY-MM-DD。") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _audit_time_window(
    days: int,
    start_ts: str | datetime | date | None,
    end_ts: str | datetime | date | None,
) -> tuple[int, datetime | None, datetime | None]:
    days = max(1, min(int(days), 365))
    start_dt = _coerce_utc_datetime(start_ts)
    end_dt = _coerce_utc_datetime(end_ts, end_of_day=True)
    if start_dt and end_dt and start_dt > end_dt:
        raise ValueError("起始時間不可晚於結束時間。")
    return days, start_dt, end_dt


def _append_time_filters(
    conditions: list[str],
    params: list[Any],
    *,
    days: int,
    start_dt: datetime | None,
    end_dt: datetime | None,
):
    if start_dt or end_dt:
        if start_dt:
            conditions.append("processed_at >= ?")
            params.append(start_dt)
        if end_dt:
            conditions.append("processed_at <= ?")
            params.append(end_dt)
    else:
        conditions.append("processed_at >= DATEADD(day, -?, SYSUTCDATETIME())")
        params.append(days)


def _where_clause(conditions: list[str]) -> str:
    if not conditions:
        return ""
    return "WHERE " + " AND ".join(conditions)


def _contains_filter(value: str | None) -> str:
    return f"%{str(value or '').strip()}%"


def _normalize_destination_table_filters(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    raw_values = [value] if isinstance(value, str) else value
    cleaned: list[str] = []
    for raw_value in raw_values:
        for table in str(raw_value or "").split(","):
            table = table.strip()
            if table and table not in cleaned:
                cleaned.append(table)
    return cleaned


def _parse_payload(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
