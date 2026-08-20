#agent/es/evidence_core/snippet.py
from __future__ import annotations

import re
from typing import Optional

from .models import Citation, EvidenceSnippet, HitDoc
from .date_utils import normalize_iso_date


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

    # 日期：citation.date_iso → 文章日期 → 第一個事件日期
    di = c.date_iso or h.article_date_iso
    if not di and h.event_dates:
        di = h.event_dates[0]
    norm_di = normalize_iso_date(di)

    if norm_di:
        if date_from and norm_di < date_from:
            return None
        if date_to and norm_di > date_to:
            return None

    article_norm = normalize_iso_date(h.article_date_iso)
    snippet_norm = normalize_iso_date(di)

    uuid = h.uuid or c.uuid
    if not uuid:
        return None

    return EvidenceSnippet(
        uuid=uuid,
        text=c.text,
        date_iso=(snippet_norm or article_norm or ""),
        article_date_iso=(article_norm or snippet_norm or ""),
        subject=h.subject,
        article_title=h.article_title,
        paragraph_id=c.paragraph_id,
        source_id=c.source_id,
        event_ids=c.event_ids,
    )
