"""Bounded, count-only 3-to-2 topic threshold shadow for ONE Evidence builder slice.

#406: not an anchor validation, automatic relaxation, cross-page recall score,
or permission for an ES/LLM call. The existing strict matcher remains authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set

from .models import HitDoc
from .snippet import build_evidence_snippet
from .topic_match import match_topic


MAX_SHADOW_CITATIONS = 256
MAX_SHADOW_TEXT_CHARS = 262_144
MAX_SHADOW_SINGLE_TEXT_CHARS = 4096


@dataclass(frozen=True)
class TopicShadowCounts:
    inspected: int = 0
    date_eligible: int = 0
    strict_in_sample: int = 0
    unanchored_text_two_group_only: int = 0
    meta_only_two_group_only: int = 0
    oversized_or_over_budget: int = 0
    uninspected_by_cap: int = 0


def observe_topic_shadow(
    hits: List[HitDoc],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    allowed_years: Optional[Set[int]],
    term_groups: List[Set[str]],
) -> TopicShadowCounts | None:
    """Count hypothetical 3->2 differences without selecting or storing Evidence.

    Only the already-parsed citations are sampled, in original ES hit order.
    A two-group match is NOT a trusted required-entity/topic anchor. In
    particular, unrelated articles matching generic auxiliary groups can
    appear in this diagnostic; none are promoted into the report.
    """
    if len(term_groups) < 4:
        return None

    total = sum(len(h.citations) for h in hits)
    inspected = date_eligible = strict_count = 0
    unanchored_text = meta_only = oversized = chars = 0

    for hit in hits:
        if inspected >= MAX_SHADOW_CITATIONS:
            break
        for citation in hit.citations:
            if inspected >= MAX_SHADOW_CITATIONS:
                break
            inspected += 1
            content = citation.text
            if not isinstance(content, str) or len(content) > MAX_SHADOW_SINGLE_TEXT_CHARS:
                oversized += 1
                continue
            if chars + len(content) > MAX_SHADOW_TEXT_CHARS:
                oversized += 1
                continue
            chars += len(content)

            # Use the exact canonical structured Event/Timeline date validator.
            evidence = build_evidence_snippet(
                hit, citation, date_from=date_from, date_to=date_to,
                allowed_years=allowed_years,
            )
            if evidence is None:
                continue
            date_eligible += 1

            accepted, _, scope, groups_hit = match_topic(
                evidence.text, hit.subject, hit.article_title, term_groups,
            )
            if accepted:
                strict_count += 1
            elif groups_hit >= 2:
                if scope in ("text", "mixed"):
                    unanchored_text += 1
                elif scope == "meta":
                    meta_only += 1

    return TopicShadowCounts(
        inspected=inspected,
        date_eligible=date_eligible,
        strict_in_sample=strict_count,
        unanchored_text_two_group_only=unanchored_text,
        meta_only_two_group_only=meta_only,
        oversized_or_over_budget=oversized,
        uninspected_by_cap=min(max(0, total - inspected), 1_000_000),
    )
