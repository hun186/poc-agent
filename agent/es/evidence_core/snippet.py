#agent/es/evidence_core/snippet.py
from __future__ import annotations

import re
from typing import Optional

from .models import Citation, EvidenceSnippet, HitDoc
from .date_utils import normalize_iso_date
from ..temporal import parse_temporal_interval


def make_fallback_snippet(text: str, q: str, width: int) -> Optional[str]:
    if not text:
        return None
    terms = [t for t in re.split(r"\s+", q or "") if t]
    positions = [text.find(t) for t in terms if t]
    pos = min([p for p in positions if p != -1] or [-1])
    if pos == -1:
        return text[:width]
    start = max(0, pos - width // 2)
    end = min(len(text), start + width)
    return text[start:end]


def build_evidence_snippet(
    h: HitDoc,
    c: Citation,
    *,
    date_from: Optional[str],
    date_to: Optional[str],
) -> Optional[EvidenceSnippet]:
    """
    把單一 hit + citation 轉成一筆 evidence_snippet：
    - 自動處理 date_iso / event_dates → article_date_iso
    - 套用 date_from / date_to 篩選
    - 帶上 uuid / subject / article_title / paragraph_id / source_id
    """
    if not c.text:
        return None

    lower_input = parse_temporal_interval(date_from) if date_from else None
    upper_input = parse_temporal_interval(date_to) if date_to else None
    lower = lower_input.start if lower_input else None
    upper = upper_input.end if upper_input else None
    limited = bool(date_from or date_to)
    article_norm = normalize_iso_date(h.article_date_iso)
    chosen = parse_temporal_interval(c.date_iso, "day") if c.date_iso else None

    if chosen is not None:
        # Explicit date in the citation text is stronger than article metadata.
        if limited and not chosen.intersects(lower, upper):
            return None
    elif c.linked_dates:
        # Only the citation's event_ids and (when known) multidim block may
        # authorize use of an extracted Event or Timeline date.
        candidates = [
            record for record in c.linked_dates
            if not limited or record.interval.intersects(lower, upper)
        ]
        if limited and not candidates:
            return None  # A genuinely linked but out-of-range citation.
        event_candidates = [record for record in candidates if record.source == "Event"]
        preferred = event_candidates or candidates
        periods = {(r.interval.start, r.interval.end) for r in preferred}
        if len(periods) == 1:
            chosen = preferred[0].interval
        # Multiple incompatible linked dates: retain an uncertain citation,
        # never invent a unique event day.
    elif not h.event_time_records and article_norm:
        # Legacy material with no structured event timestamps at all may still
        # use its publication date, preserving old article-only semantics.
        chosen = parse_temporal_interval(article_norm, "day")
        if limited and chosen and not chosen.intersects(lower, upper):
            return None

    # For a coarse month/year, reporting its first day as an observed event
    # day is false precision. Keep date_iso empty and expose an explicit window.
    snippet_date = chosen.iso if chosen and chosen.precision == "day" else ""
    uncertain = chosen is None and (limited or bool(h.event_time_records))

    uuid = h.uuid or c.uuid
    if not uuid:
        return None

    return EvidenceSnippet(
        uuid=uuid,
        text=c.text,
        date_iso=snippet_date,
        article_date_iso=article_norm or "",
        event_time_precision=chosen.precision if chosen else None,
        event_time_start_iso=chosen.start.isoformat() if chosen else None,
        event_time_end_iso=chosen.end.isoformat() if chosen else None,
        weak_evidence=uncertain,
        event_time_unresolved=uncertain,
        subject=h.subject,
        article_title=h.article_title,
        paragraph_id=c.paragraph_id,
        source_id=c.source_id,
        event_ids=c.event_ids,
    )
