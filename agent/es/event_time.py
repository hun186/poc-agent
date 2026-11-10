"""Structured GLM event-time contract shared by ES query and Evidence parsing.

Never turn a year/month precision into an asserted day. No ES/network access.
"""
from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


_TIME_PREFIX = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T.+)?)?)?$")
_PRECISIONS = {"year": 1, "month": 2, "day": 3, "hour": 4, "minute": 5, "second": 6}


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
    raw = value.strip()
    match = _TIME_PREFIX.fullmatch(raw)
    if not match:
        return None
    if "T" in raw:
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    year_s, month_s, day_s = match.groups()
    granularity = (6 if "T" in raw else (3 if day_s else (2 if month_s else 1)))
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
        if level > 3:
            # Missing/empty precision is legacy data: infer the canonical
            # granularity from the timestamp instead of serializing "none"/"".
            # An ISO timestamp with unspecified precision conservatively
            # expresses its literal (normalized) second-level resolution.
            effective_precision = (
                str(precision).strip().lower() if precision else
                {4: "hour", 5: "minute", 6: "second"}[level]
            )
            return StructuredTime(raw, effective_precision, ymd, ymd, source)
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


def event_ids_in_block(block: dict) -> set[str]:
    """Return all declared local IDs, including undated or invalid Events.

    An ID occurring in an undated block still reserves that ID locally;
    absent parent offsets must not make it globally unique merely because
    only another block happens to have a valid time.
    """
    result: set[str] = set()
    for record in _records(block, "Event"):
        result.update(_ids(record.get("event_id")))
    for record in _records(block, "Event_Timeline"):
        result.update(_ids(record.get("event_ids")))
    return result


def collect_linked_times(blocks: List[dict]) -> Tuple[Dict[str, List[StructuredTime]], bool]:
    """Build an event-id lookup, refusing conflicting ID reuse across blocks.

    GLM event IDs are only guaranteed in a local structured block. When the
    same identifier reappears in multiple blocks with incompatible temporal
    claims, _source Evidence without reliable block context must not be
    joined to another block's event date.
    """
    events: Dict[str, List[StructuredTime]] = {}
    timeline: Dict[str, List[StructuredTime]] = {}
    block_claims: Dict[str, tuple] = {}
    conflicts = set()
    has_structure = False
    for block in blocks:
        local_events: Dict[str, List[StructuredTime]] = {}
        local_timeline: Dict[str, List[StructuredTime]] = {}
        mentioned = set()
        for item in _records(block, "Event"):
            has_structure = True
            eid = item.get("event_id")
            if eid is None or not str(eid).strip():
                continue
            eid = str(eid).strip()
            mentioned.add(eid)
            point = parse_structured_time(item.get("time_iso"), item.get("time_precision"), "Event")
            if point:
                events.setdefault(eid, []).append(point)
                local_events.setdefault(eid, []).append(point)
        for item in _records(block, "Event_Timeline"):
            has_structure = True
            ids = _ids(item.get("event_ids"))
            mentioned.update(ids)
            point = parse_structured_time(item.get("time_iso"), item.get("time_precision"), "Event_Timeline")
            if point:
                for eid in ids:
                    timeline.setdefault(eid, []).append(point)
                    local_timeline.setdefault(eid, []).append(point)

        for eid in mentioned:
            signature = tuple(sorted({
                (p.source, p.precision, p.start, p.end)
                for p in local_events.get(eid, []) + local_timeline.get(eid, [])
            }))
            if eid in block_claims and block_claims[eid] != signature:
                conflicts.add(eid)
            block_claims[eid] = signature

    answer: Dict[str, List[StructuredTime]] = {}
    for eid in events.keys() | timeline.keys():
        if eid in conflicts:
            continue
        unique: List[StructuredTime] = []
        for point in events.get(eid, []) + timeline.get(eid, []):
            # Year/month/day periods can be de-duplicated by interval. Finer
            # timestamps on the same day must retain distinct hours/minutes.
            def identity(p: StructuredTime) -> tuple:
                subday = p.precision in ("hour", "minute", "second")
                return (p.start, p.end, p.precision, p.time_iso if subday else None)
            if not any(identity(p) == identity(point) for p in unique):
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


def query_untyped_period_bounds(date_from: Optional[str], date_to: Optional[str]) -> dict:
    """Conservative ES candidate bounds for legacy absent/empty precision.

    A missing time_precision can mean year, month, day, or a timestamp with
    an explicit offset. ES cannot infer which from a date-mapped time_iso,
    so the year-wide envelope must include partial periods' normalized first
    day, plus one UTC conversion guard day at both boundaries. The subsequent
    block-local Evidence parser always enforces the real source precision.
    """
    bounds = query_period_bounds(date_from, date_to, "year")
    if "gte" in bounds:
        bounds["gte"] = (date.fromisoformat(bounds["gte"]) - timedelta(days=1)).isoformat()
    if "lt" in bounds:
        bounds["lt"] = (date.fromisoformat(bounds["lt"]) + timedelta(days=1)).isoformat()
    return bounds


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
    subday = precision in ("hour", "minute", "second")
    # An ISO timestamp with +14:00/-12:00 can be indexed by Elasticsearch
    # on the adjacent UTC day. Date queries are only candidate retrieval:
    # widen a day for subday timestamps, then apply local-calendar checks to
    # the ORIGINAL literal and event_id scope in the Evidence stage.
    if date_from:
        lower = date.fromisoformat(floor(date_from))
        bounds["gte"] = (lower - timedelta(days=1) if subday else lower).isoformat()
    if date_to:
        upper = date.fromisoformat(ceiling(date_to)) + timedelta(days=1)
        bounds["lt"] = (upper + timedelta(days=1) if subday else upper).isoformat()
    return bounds
