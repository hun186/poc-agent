"""Opt-in, bounded low-count topic 3->2 adaptive candidates for one ES slice.

This is NOT a multi-round retrieval engine. It neither queries ES nor LLM.
It must receive a validated explicit subject from the ORIGINAL user question.
Every candidate reuses canonical Event/Timeline date validation, requires >=2
independent TEXT semantic axes, and must be subject-anchored in its own text
or in an independently validated strict same-Event passage.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional, Set

from .event_anchor import same_event_as_strict_anchor
from .models import EvidenceSnippet, HitDoc
from .question_anchor import ExplicitQuestionAnchor, text_explicitly_mentions_anchor
from .snippet import build_evidence_snippet
from .topic_match import match_topic

_LOG = logging.getLogger("sraf.topic_adaptive")
MAX_SCAN = 256
MAX_TEXT_CHARS = 262_144
MAX_SINGLE_CHARS = 4096
MIN_GROUPS = 4
TARGET_COUNT = 3
MAX_ADD = 2


@dataclass(frozen=True)
class AdaptiveResult:
    status: str
    inspected: int = 0
    date_eligible: int = 0
    two_text_axes: int = 0
    direct_subject: int = 0
    same_event_context: int = 0
    blocked_meta_only: int = 0
    blocked_unanchored: int = 0
    uninspected_by_cap: int = 0
    proposed: int = 0
    selected: int = 0
    candidates: tuple[EvidenceSnippet, ...] = ()


def consider_low_count(
    hits: list[HitDoc], strict: list[EvidenceSnippet],
    *, date_from: Optional[str], date_to: Optional[str],
    allowed_years: Optional[Set[int]],
    groups: list[set[str]], anchor: Optional[ExplicitQuestionAnchor],
    mode: str,
) -> AdaptiveResult:
    """No mutation of input; strict Evidence and source citations remain canonical.

    Only nonzero low strict count is eligible; zero keeps existing behavior.
    Shadow and on use the *same* candidate logic for meaningful A/B counts.
    """
    if mode not in {"shadow", "on"}:
        return AdaptiveResult(status="disabled")
    if len(groups) < MIN_GROUPS:
        return AdaptiveResult(status="insufficient_groups")
    if not 0 < len(strict) < TARGET_COUNT:
        return AdaptiveResult(status="strict_not_low")
    if anchor is None:
        return AdaptiveResult(status="no_trusted_anchor")

    # Only a *text* strict Evidence row with the explicit required subject
    # may anchor contextual evidence. Never treat ES title or article metadata
    # as proof about another Event, or accept a loose UUID match.
    anchors: dict[int, list[EvidenceSnippet]] = {}
    for ev in strict:
        if (ev.match_policy == "strict" and not ev.weak_evidence
                and ev.match_scope in {"text", "mixed"}
                and text_explicitly_mentions_anchor(ev.text, anchor)
                and match_topic(ev.text, None, None, groups)[0]):
            anchors.setdefault(ev.source_hit_ordinal, []).append(ev)

    inspected = eligible = text_axes = direct = contextual = meta = unanchored = chars = 0
    proposals: list[EvidenceSnippet] = []
    total = sum(len(hit.citations) for hit in hits)
    used = {(ev.source_hit_ordinal, ev.text, tuple(ev.event_ids))
            for ev in strict}
    exhausted = False

    for hit in hits:
        for citation in hit.citations:
            if inspected >= MAX_SCAN:
                exhausted = True
                break
            inspected += 1
            if (not isinstance(citation.text, str)
                    or not 0 < len(citation.text) <= MAX_SINGLE_CHARS
                    or chars + len(citation.text) > MAX_TEXT_CHARS):
                continue
            chars += len(citation.text)
            ev = build_evidence_snippet(
                hit, citation, date_from=date_from, date_to=date_to,
                allowed_years=allowed_years,
            )
            if ev is None:
                continue
            eligible += 1
            strict_match, _, _, _ = match_topic(
                ev.text, hit.subject, hit.article_title, groups,
            )
            if strict_match:
                continue
            _, body_terms, _, body_group_count = match_topic(
                ev.text, None, None, groups,
            )
            if body_group_count < 2:
                meta += 1
                continue
            text_axes += 1
            self_subject = text_explicitly_mentions_anchor(ev.text, anchor)
            same_event = (
                hit.has_structured_events
                and not self_subject
                and any(same_event_as_strict_anchor(hit, citation, matched)
                        for matched in anchors.get(hit.source_hit_ordinal, ()))
            )
            if self_subject:
                direct += 1
            elif same_event:
                contextual += 1
            else:
                unanchored += 1
                continue
            key = (ev.source_hit_ordinal, ev.text, tuple(ev.event_ids))
            if key in used:
                continue
            used.add(key)
            ev.match_policy = "adaptive_two_axis"
            ev.match_scope = "text"
            ev.group_hits = body_group_count
            ev.synonym_hits = sorted(body_terms)
            ev.weak_evidence = True
            proposals.append(ev)
        if exhausted:
            break

    accepted = min(len(proposals), MAX_ADD, TARGET_COUNT - len(strict))
    return AdaptiveResult(
        status="applied" if mode == "on" else "shadow",
        inspected=inspected, date_eligible=eligible, two_text_axes=text_axes,
        direct_subject=direct, same_event_context=contextual,
        blocked_meta_only=meta, blocked_unanchored=unanchored,
        uninspected_by_cap=max(0, total - inspected), proposed=len(proposals),
        selected=accepted if mode == "on" else 0,
        candidates=tuple(proposals[:accepted]) if mode == "on" else (),
    )


def log_adaptive(result: AdaptiveResult, *, mode: str, strict_count: int,
                 anchor_source: str = "none") -> None:
    """Mandatory privacy-safe audit whenever operator opts into shadow/on."""
    if mode not in {"shadow", "on"}:
        return
    _LOG.warning(
        "SRAF_TOPIC_ADAPTIVE mode=%s status=%s anchor_source=%s strict=%d inspected=%d "
        "date_eligible=%d two_text_axes=%d direct_subject=%d same_event=%d "
        "blocked_meta_only=%d blocked_unanchored=%d uninspected_by_cap=%d "
        "proposed=%d selected=%d",
        mode, result.status, (anchor_source if anchor_source in ("explicit", "prose")
                              else "none"), strict_count, result.inspected,
        result.date_eligible, result.two_text_axes, result.direct_subject,
        result.same_event_context, result.blocked_meta_only,
        result.blocked_unanchored, result.uninspected_by_cap,
        result.proposed, result.selected,
    )
