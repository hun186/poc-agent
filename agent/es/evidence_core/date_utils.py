# agent/es/evidence_core/date_utils.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Set, Tuple

from ..temporal import TemporalInterval, parse_temporal_interval
from .json_utils import as_blocks, json_load_maybe


_YMD = re.compile(r'(?P<y>20\d{2}|19\d{2})[年/\-\.](?P<m>\d{1,2})[月/\-\.](?P<d>\d{1,2})日?')
_MD = re.compile(r'(?P<m>\d{1,2})月(?P<d>\d{1,2})日')
_TODAY_D = re.compile(r'今[（(](?P<d>\d{1,2})[）)]日')
_PAREN_D = re.compile(r'[（(](?P<d>\d{1,2})日[）)]')


@dataclass(frozen=True)
class EventTimeRecord:
    interval: TemporalInterval
    event_ids: Tuple[str, ...]
    source: str  # Event or Event_Timeline
    block_index: int


def norm_date(y: int, m: int, d: int) -> Optional[str]:
    parsed = parse_temporal_interval(f"{y:04d}-{m:02d}-{d:02d}", "day")
    return parsed.iso if parsed else None


def normalize_iso_date(di: Any) -> Optional[str]:
    """Only return a genuine Gregorian calendar date, not an invalid prefix."""
    parsed = parse_temporal_interval(di)
    return parsed.iso if parsed else None


def parse_article_date_iso(raw: str) -> Optional[str]:
    if not raw:
        return None
    m = _YMD.search(raw)
    if not m:
        return None
    return norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))


def _as_items(value: Any) -> List[dict]:
    value = json_load_maybe(value)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _ids(value: Any) -> Tuple[str, ...]:
    value = json_load_maybe(value)
    if value is None:
        return ()
    if not isinstance(value, list):
        value = [value]
    return tuple(dict.fromkeys(str(v).strip() for v in value if v is not None and str(v).strip()))


def collect_event_time_records(src: dict, *, limit: int = 500) -> List[EventTimeRecord]:
    """Keep Event dates and linked Timeline dates separate and block-local.

    Event IDs from different multidim blocks must never silently be treated as
    interchangeable. Undated or malformed rows contribute no temporal fact.
    """
    records: List[EventTimeRecord] = []
    for block_i, block in enumerate(as_blocks((src or {}).get("multidim_event_json"))):
        for source in ("Event", "Event_Timeline"):
            for item in _as_items(block.get(source)):
                parsed = parse_temporal_interval(item.get("time_iso"), item.get("time_precision"))
                if parsed is None:
                    continue
                linked = _ids(item.get("event_id") if source == "Event" else item.get("event_ids"))
                records.append(EventTimeRecord(parsed, linked, source, block_i))
                if len(records) >= limit:
                    return records
    return records


def collect_timeline_dates(src: dict, *, topk: int) -> List[str]:
    uniq: List[str] = []
    seen: Set[str] = set()
    for block in as_blocks((src or {}).get("multidim_event_json")):
        for item in _as_items(block.get("Event_Timeline")):
            di = normalize_iso_date(item.get("time_iso"))
            if di and di not in seen:
                seen.add(di)
                uniq.append(di)
                if len(uniq) >= topk:
                    return uniq
    return uniq


def infer_date_for_snippet(text: str, article_date_iso: Optional[str], timeline_dates: List[str], *, day_precision_dates: Optional[List[str]] = None) -> Optional[str]:
    if not text:
        return None
    # The citation's own full date has precedence over the article metadata.
    m = _YMD.search(text)
    if m:
        return norm_date(int(m.group('y')), int(m.group('m')), int(m.group('d')))

    art_y = art_m = None
    normalized_article = normalize_iso_date(article_date_iso)
    if normalized_article:
        art_y = int(normalized_article[0:4])
        art_m = int(normalized_article[5:7])

    tl_years = sorted({int(di[0:4]) for di in timeline_dates if normalize_iso_date(di)})

    m = _MD.search(text)
    if m:
        mm, dd = int(m.group('m')), int(m.group('d'))
        year = art_y or (tl_years[0] if len(tl_years) == 1 else None)
        if year:
            return norm_date(year, mm, dd)

    m = _TODAY_D.search(text) or _PAREN_D.search(text)
    if m:
        dd = int(m.group('d'))
        if art_y and art_m:
            return norm_date(art_y, art_m, dd)
        # A year/month period's first day is an interval boundary, not an
        # observed calendar day. Only real day-resolution records may supply
        # a bare parenthesized day (e.g. 今(1)日).
        for di in (timeline_dates if day_precision_dates is None else day_precision_dates):
            valid = normalize_iso_date(di)
            if valid and int(valid[8:10]) == dd:
                return valid

    return None


def is_valid_year(di: str) -> bool:
    return normalize_iso_date(di) is not None
