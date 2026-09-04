from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import RecurrenceSpec


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_naive")
    if value.microsecond:
        raise ValueError("recurrence_second_precision_required")
    return value.astimezone(timezone.utc)


def _zone(name: str) -> ZoneInfo:
    try: return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError): raise ValueError("timezone_invalid") from None


def _resolve_local(day: date, local_time, zone: ZoneInfo) -> datetime:
    naive = datetime.combine(day, local_time)
    # fold=0 gives the earlier ambiguous instant. A valid local time round trips.
    for minutes in range(24 * 60):
        candidate_naive = naive + timedelta(minutes=minutes)
        if candidate_naive.date() != day: break
        candidate = candidate_naive.replace(tzinfo=zone, fold=0)
        back = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if back == candidate_naive:
            return candidate.astimezone(timezone.utc)
    raise ValueError("recurrence_nonexistent_day")


def next_occurrence(spec: RecurrenceSpec, timezone_name: str, after_utc: datetime) -> datetime:
    after = _aware_utc(after_utc)
    zone = _zone(timezone_name)
    if spec.kind == "interval":
        anchor = _aware_utc(spec.anchor_at)
        seconds = spec.every * {"minutes": 60, "hours": 3600, "days": 86400}[spec.unit]
        elapsed = (after - anchor).total_seconds()
        steps = max(0, int(elapsed // seconds) + 1)
        candidate = anchor + timedelta(seconds=steps * seconds)
        return candidate if candidate > after else candidate + timedelta(seconds=seconds)
    local_after = after.astimezone(zone)
    start = local_after.date()
    for offset in range(3700):
        day = start + timedelta(days=offset)
        if spec.kind == "weekly" and day.isoweekday() not in spec.weekdays: continue
        if spec.kind == "monthly":
            target = min(spec.day, calendar.monthrange(day.year, day.month)[1])
            if day.day != target: continue
        candidate = _resolve_local(day, spec.local_time, zone)
        if candidate > after: return candidate
    raise RuntimeError("recurrence_iteration_limit")


def coalesce_latest(spec: RecurrenceSpec, timezone_name: str, next_run_at: datetime, now_utc: datetime):
    due, now = _aware_utc(next_run_at), _aware_utc(now_utc)
    if due > now: return None
    if spec.kind == "interval":
        seconds = spec.every * {"minutes": 60, "hours": 3600, "days": 86400}[spec.unit]
        latest = due + timedelta(seconds=int((now - due).total_seconds() // seconds) * seconds)
        return latest, latest + timedelta(seconds=seconds)
    latest = due
    for _ in range(3700):
        following = next_occurrence(spec, timezone_name, latest)
        if following > now: return latest, following
        latest = following
    raise RuntimeError("recurrence_iteration_limit")
