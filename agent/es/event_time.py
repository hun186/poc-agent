"""Structured GLM event-time contract shared by ES query and Evidence parsing.

Never turn a year/month precision into an asserted day. No ES/network access.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple


_TIME_PREFIX = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T.+)?)?)?$")
_PRECISIONS = {"year": 1, "month": 2, "day": 3}


@dataclass(frozen=True)
class StructuredTime:
    time_iso: str
    precision: str
    start: str
    end: str
    source: str  # Event or Event_Timeline

    def overlaps(self, date_from: Optional[str], date_to: Optional[str]) -> bool:
        return (not date_from or self.end >= date_from) and (
            not date_to or self.start <= date_to
        )


def parse_structured_time(value: Any, precision: Any, source: str) -> Optional[StructuredTime]:
    """Parse trusted date and precision; reject invalid/unknown instead of guessing.

    A legacy value without time_precision can infer granularity from its ISO shape.
    Explicit year/month precision wins over a more detailed normalized time_iso.
    """
    if not isinstance(value, str):
        return None
    match = _TIME_PREFIX.fullmatch(value.strip())
    if not match:
        return None
    year_s, month_s, day_s = match.groups()
    granularity = 3 if day_s else (2 if month_s else 1)
    if precision is None or precision == "":
        level = granularity
    elif isinstance(precision, str) and precision.strip().lower() in _PRECISIONS:
        level = _PRECISIONS[precision.strip().lower()]
    else:
        return None  # unknown/invalid precision is not an exact date
    if level > granularity:
        return None
    try:
        year = int(year_s)
        if not (1900 <= year <= 2100):
            return None
        month = int(month_s) if month_s else 1
        day = int(day_s) if day_s else 1
        date(year, month, day)  # calendar-valid input, including leap days
        if level == 1:
            return StructuredTime(year_s, "year", f"{year_s}-01-01", f"{year_s}-12-31", source)
        if level == 2:
            last = calendar.monthrange(year, month)[1]
            ym = f"{year_s}-{month:02d}"
            return StructuredTime(ym, "month", f"{ym}-01", f"{ym}-{last:02d}", source)
        ymd = f"{year_s}-{month:02d}-{day:02d}"
        return StructuredTime(ymd, "day", ymd, ymd, source)
    except (TypeError, ValueError):
        return None


def _records(block: dict, key: str) -> List[dict]:
    value = block.get(key) or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ids(value: Any) -> List[str]:
    if isinstance(value, str):
        # Scalar IDs and JSON-encoded arrays are both present in old ES documents.
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
        except (TypeError, ValueError):
            pass
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value if item is not None and str(item).strip()]


def collect_linked_times(blocks: List[dict]) -> Tuple[Dict[str, List[StructuredTime]], bool]:
    """Find Event times first, then Timeline time for IDs without Event dates.

    Detect structure independently of valid dates, so a dangling event_id cannot
    silently fall back to the unrelated article publication date.
    """
    events: Dict[str, List[StructuredTime]] = {}
    timeline: Dict[str, List[StructuredTime]] = {}
    has_structure = False
    for block in blocks:
        for item in _records(block, "Event"):
            has_structure = True
            eid = item.get("event_id")
            if eid is None or not str(eid).strip():
                continue
            point = parse_structured_time(item.get("time_iso"), item.get("time_precision"), "Event")
            if point:
                events.setdefault(str(eid).strip(), []).append(point)
        for item in _records(block, "Event_Timeline"):
            has_structure = True
            point = parse_structured_time(item.get("time_iso"), item.get("time_precision"), "Event_Timeline")
            if point:
                for eid in _ids(item.get("event_ids")):
                    timeline.setdefault(eid, []).append(point)

    answer: Dict[str, List[StructuredTime]] = {}
    for eid in events.keys() | timeline.keys():
        unique = []
        for point in (events.get(eid) or timeline.get(eid) or []):
            if point not in unique:
                unique.append(point)
        answer[eid] = unique
    return answer, has_structure


def linked_dates_for_ids(
    ids: List[str], lookup: Dict[str, List[StructuredTime]]
) -> Tuple[List[StructuredTime], bool]:
    points: List[StructuredTime] = []
    complete = bool(ids) and all(eid in lookup and lookup[eid] for eid in ids)
    for eid in ids:
        for point in lookup.get(eid, []):
            if point not in points:
                points.append(point)
    return points, complete


def query_period_bounds(date_from: Optional[str], date_to: Optional[str], precision: str) -> dict:
    """Broaden ES range for stored partial dates, never alter caller's date range."""
    def floor(value: str) -> str:
        return value[:4] + "-01-01" if precision == "year" else (
            value[:7] + "-01" if precision == "month" else value
        )

    def ceiling(value: str) -> str:
        if precision == "year":
            return value[:4] + "-12-31"
        if precision == "month":
            year, month = int(value[:4]), int(value[5:7])
            return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        return value

    bounds = {}
    if date_from:
        bounds["gte"] = floor(date_from)
    if date_to:
        # ES date values may contain hours; using lte YYYY-MM-DD excludes times
        # later that day. A next-midnight exclusive boundary is exact.
        bounds["lt"] = (date.fromisoformat(ceiling(date_to)) + timedelta(days=1)).isoformat()
    return bounds
