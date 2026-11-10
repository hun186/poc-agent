"""Precision-aware ES date constraints for GLM's two nested time sources."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from .temporal import parse_temporal_interval

MD = "multidim_event_json"


def _child_clause(child: str, lower: Optional[date], upper: Optional[date]) -> Dict[str, Any]:
    time = f"{MD}.{child}.time_iso"
    precision = f"{MD}.{child}.time_precision"

    def rng(start: Optional[date], stop: Optional[date]) -> Dict[str, Any]:
        bounds = {}
        if start:
            bounds["gte"] = start.isoformat()
        if stop:
            bounds["lt"] = stop.isoformat()
        return {"range": {time: bounds}}

    following_day = upper + timedelta(days=1) if upper else None
    following_month = date(upper.year + (upper.month == 12), upper.month % 12 + 1, 1) if upper else None
    following_year = date(upper.year + 1, 1, 1) if upper else None
    cases = [
        rng(lower, following_day),  # day, missing/unknown precision: literal date
        {"bool": {"filter": [
            {"term": {precision: "month"}},
            rng(date(lower.year, lower.month, 1) if lower else None, following_month),
        ]}},
        {"bool": {"filter": [
            {"term": {precision: "year"}},
            rng(date(lower.year, 1, 1) if lower else None, following_year),
        ]}},
    ]
    return {"nested": {"path": MD, "score_mode": "none", "query": {
        "nested": {"path": f"{MD}.{child}", "score_mode": "none", "query": {
            "bool": {"should": cases, "minimum_should_match": 1}
        }}
    }}}


def dual_event_date_filter(date_from: Optional[str], date_to: Optional[str]) -> Dict[str, Any]:
    """OR across Event and Timeline; AND precision with the same nested row."""
    start = parse_temporal_interval(date_from) if date_from else None
    end = parse_temporal_interval(date_to) if date_to else None
    if (date_from and start is None) or (date_to and end is None):
        # Never silently discard an invalid filter; keep old ES validation.
        clauses = []
        for child in ("Event", "Event_Timeline"):
            raw = {}
            if date_from:
                raw["gte"] = date_from
            if date_to:
                raw["lte"] = date_to
            clauses.append({"nested": {"path": MD, "score_mode": "none", "query": {
                "nested": {"path": f"{MD}.{child}", "score_mode": "none",
                           "query": {"range": {f"{MD}.{child}.time_iso": raw}}}
            }}})
        return {"bool": {"should": clauses, "minimum_should_match": 1}}
    lower = start.start if start else None
    upper = end.end if end else None
    if lower and upper and lower > upper:
        return {"match_none": {}}
    return {"bool": {
        "should": [_child_clause(child, lower, upper) for child in ("Event", "Event_Timeline")],
        "minimum_should_match": 1,
    }}
