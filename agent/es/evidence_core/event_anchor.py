"""Same-origin, same-event guard for *weak* Evidence rescue (#406).

A valid Event date is not sufficient proof that two Event snippets in the same
Elasticsearch hit share the same topic. This is an additional conservative
condition for borrowing an existing strict-text anchor, not a new date rule.
"""
from __future__ import annotations

from .models import Citation, EvidenceSnippet, HitDoc


MAX_ANCHOR_IDS = 16
MAX_ANCHOR_ID_CHARS = 128


def same_event_as_strict_anchor(
    hit: HitDoc, candidate: Citation, anchor: EvidenceSnippet,
) -> bool:
    """Permit weak borrowing only within one original hit + Event context.

    Older documents without structured Event metadata retain their original
    same-hit-only behavior. For structured documents, require a known common
    block and at least one explicit shared bounded Event ID. Never match on
    UUID, publication date or identical date string alone.
    """
    if anchor.source_hit_ordinal != hit.source_hit_ordinal:
        return False
    if not hit.has_structured_events:
        return True
    if (
        candidate.block_index is None
        or anchor.block_index is None
        or candidate.block_index != anchor.block_index
    ):
        return False
    left, right = anchor.event_ids, candidate.event_ids
    if not left or not right or len(left) > MAX_ANCHOR_IDS or len(right) > MAX_ANCHOR_IDS:
        return False
    if any(
        not isinstance(x, str) or not x or len(x) > MAX_ANCHOR_ID_CHARS
        for x in (*left, *right)
    ):
        return False
    return bool(set(left).intersection(right))
