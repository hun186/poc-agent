"""Bounded, count-only 3-to-2 topic threshold shadow for ONE Evidence builder slice.

#406: not an anchor validation, automatic relaxation, cross-page recall score,
or permission for an ES/LLM call. The existing strict matcher remains authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set

from .models import Citation, EvidenceSnippet, HitDoc
from .snippet import build_evidence_snippet
from .topic_match import match_topic
from .question_anchor import ExplicitQuestionAnchor, text_explicitly_mentions_anchor
from .event_anchor import same_event_as_strict_anchor


MAX_SHADOW_CITATIONS = 256
MAX_SHADOW_TEXT_CHARS = 262_144
MAX_SHADOW_SINGLE_TEXT_CHARS = 4096
# Max local strict-text anchors used to establish same-Event provenance in
# this *diagnostic*. Drop later anchors conservatively rather than scan any
# unbounded article/actor context or build an unconstrained Cartesian product.
MAX_SHADOW_STRICT_SUBJECT_ANCHORS = 128
MAX_SHADOW_STRICT_SUBJECT_ANCHORS_PER_HIT = 16


@dataclass(frozen=True)
class TopicShadowCounts:
    inspected: int = 0
    date_eligible: int = 0
    strict_in_sample: int = 0
    unanchored_text_two_group_only: int = 0
    meta_only_two_group_only: int = 0
    oversized_or_over_budget: int = 0
    uninspected_by_cap: int = 0
    explicit_subject_available: int = 0
    explicit_subject_direct_two_group_only: int = 0
    explicit_subject_not_direct_two_group_only: int = 0
    strict_subject_text_anchors_in_sample: int = 0
    same_event_subject_context_two_group_only: int = 0
    no_same_event_subject_context_two_group_only: int = 0
    subject_anchors_dropped_by_cap: int = 0
    # Existing "text/mixed" means >=1 group mentioned in the passage.
    # The following split requires TWO independent groups from text alone.
    text_two_axis_only: int = 0
    metadata_assisted_two_axis_only: int = 0
    same_event_two_text_axis_only: int = 0
    no_same_event_two_text_axis_only: int = 0


def observe_topic_shadow(
    hits: List[HitDoc],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    allowed_years: Optional[Set[int]],
    term_groups: List[Set[str]],
    explicit_anchor: Optional[ExplicitQuestionAnchor] = None,
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
    explicit_direct = explicit_not_direct = 0
    two_text = metadata_assisted = 0
    same_event_two_text = no_event_two_text = 0
    strict_subject_anchors: dict[int, list[EvidenceSnippet]] = {}
    no_direct_candidates: list[tuple[HitDoc, Citation, bool]] = []
    anchors_count = anchors_dropped = 0

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
                if (
                    explicit_anchor is not None
                    and hit.has_structured_events
                    and text_explicitly_mentions_anchor(evidence.text, explicit_anchor)
                    # The anchor's three semantic axes must be validated
                    # independently by its TEXT, not borrowed from metadata.
                    and match_topic(evidence.text, None, None, term_groups)[0]
                ):
                    current = strict_subject_anchors.setdefault(
                        hit.source_hit_ordinal, [],
                    )
                    if (
                        anchors_count < MAX_SHADOW_STRICT_SUBJECT_ANCHORS
                        and len(current) < MAX_SHADOW_STRICT_SUBJECT_ANCHORS_PER_HIT
                    ):
                        current.append(evidence)
                        anchors_count += 1
                    else:
                        anchors_dropped += 1
            elif groups_hit >= 2:
                if scope in ("text", "mixed"):
                    unanchored_text += 1
                    # A mixed-scope candidate can have only ONE text group
                    # and borrow the other from article title/metadata. For
                    # quality comparison, independently count TEXT-only axes
                    # using the same canonical match_topic semantics.
                    _, _, _, text_axis_count = match_topic(
                        evidence.text, None, None, term_groups,
                    )
                    is_two_text_axes = text_axis_count >= 2
                    if is_two_text_axes:
                        two_text += 1
                    else:
                        metadata_assisted += 1
                    # This is literal subject presence in the passage only,
                    # not validated 2-group precision nor an Event borrow.
                    # A subject in document metadata is NOT a direct anchor.
                    if explicit_anchor is not None:
                        if text_explicitly_mentions_anchor(evidence.text, explicit_anchor):
                            explicit_direct += 1
                        else:
                            explicit_not_direct += 1
                            no_direct_candidates.append((
                                hit, citation, is_two_text_axes,
                            ))
                elif scope == "meta":
                    meta_only += 1

    # Resolve missing-literal candidates only against *already date-qualified*
    # strictly text-matched subject evidence in the SAME original source hit,
    # SAME structured block and overlapping Event ID. In particular, legacy
    # docs cannot claim "same Event" from an article-wide match.
    same_event_context = no_context = 0
    for hit, citation, is_two_text_axes in no_direct_candidates:
        has_event_context = hit.has_structured_events and any(
            same_event_as_strict_anchor(hit, citation, anchor)
            for anchor in strict_subject_anchors.get(hit.source_hit_ordinal, ())
        )
        if has_event_context:
            same_event_context += 1
            if is_two_text_axes:
                same_event_two_text += 1
        else:
            no_context += 1
            if is_two_text_axes:
                no_event_two_text += 1

    return TopicShadowCounts(
        inspected=inspected,
        date_eligible=date_eligible,
        strict_in_sample=strict_count,
        unanchored_text_two_group_only=unanchored_text,
        meta_only_two_group_only=meta_only,
        oversized_or_over_budget=oversized,
        uninspected_by_cap=min(max(0, total - inspected), 1_000_000),
        explicit_subject_available=int(explicit_anchor is not None),
        explicit_subject_direct_two_group_only=explicit_direct,
        explicit_subject_not_direct_two_group_only=explicit_not_direct,
        strict_subject_text_anchors_in_sample=anchors_count,
        same_event_subject_context_two_group_only=same_event_context,
        no_same_event_subject_context_two_group_only=no_context,
        subject_anchors_dropped_by_cap=anchors_dropped,
        text_two_axis_only=two_text,
        metadata_assisted_two_axis_only=metadata_assisted,
        same_event_two_text_axis_only=same_event_two_text,
        no_same_event_two_text_axis_only=no_event_two_text,
    )
