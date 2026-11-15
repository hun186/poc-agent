"""Opt-in bounded rescue of topic-weak but date-qualified Evidence.

This module never queries ES or an LLM and never broadens the date contract.
Only citations from a document already anchored by a strong *strict* match may
enter a capped candidate pool. No rejected candidate is returned or logged.
"""
from __future__ import annotations

import math
from typing import List, Optional, Set

from .models import EvidenceSnippet, HitDoc
from .snippet import build_evidence_snippet
from .topic_match import match_topic


MIN_STRICT_TO_RESCUE = 1
TARGET_EVIDENCE_COUNT = 3
MAX_ANCHOR_DOCUMENTS = 12
MAX_CITATIONS_INSPECTED = 96
MAX_CITATIONS_PER_DOCUMENT = 8
MAX_POOL_CANDIDATES = 24
MAX_RESCUE_PER_DOCUMENT = 2
MAX_CANDIDATE_CHARACTERS = 2048
MAX_POOL_CHARACTERS = 65536


def _score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return score if math.isfinite(score) else 0.0


def bounded_rescue(
    hits: List[HitDoc],
    strict_evidence: List[EvidenceSnippet],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    allowed_years: Optional[Set[int]],
    term_groups: List[Set[str]],
) -> List[EvidenceSnippet]:
    """Return up to two extra, marked-weak citations, never altering anchors.

    Trigger only when there are 1-2 strict citations and at least two separate
    query axes. Only documents already confirmed by an *Evidence text* strict
    match can contribute. Candidate must independently match query text in at
    least one axis, but not already satisfy strict matching. Date qualification
    still uses the canonical `build_evidence_snippet` fail-closed validator.

    Caps apply to scanned citations, candidate text length, total inspected
    candidate characters, candidate pool and number of source documents.
    """
    if not (MIN_STRICT_TO_RESCUE <= len(strict_evidence) < TARGET_EVIDENCE_COUNT):
        return []
    if len(term_groups) < 2:
        return []

    trusted_origins = {
        evidence.source_hit_ordinal for evidence in strict_evidence
        if not evidence.weak_evidence and evidence.match_scope in ("text", "mixed")
    }
    if not trusted_origins:
        return []

    # Stable source-hit ordinal, never application uuid: uuid is not unique
    # across ES indices or across different multidim event blocks.
    candidates = []
    inspected = 0
    considered_chars = 0
    anchor_documents = 0
    for hit in hits:
        if hit.source_hit_ordinal not in trusted_origins:
            continue
        if anchor_documents >= MAX_ANCHOR_DOCUMENTS or inspected >= MAX_CITATIONS_INSPECTED:
            break
        anchor_documents += 1

        existing = {
            ev.text for ev in strict_evidence
            if ev.source_hit_ordinal == hit.source_hit_ordinal
        }
        for citation_order, citation in enumerate(hit.citations[:MAX_CITATIONS_PER_DOCUMENT]):
            if inspected >= MAX_CITATIONS_INSPECTED or len(candidates) >= MAX_POOL_CANDIDATES:
                break
            inspected += 1
            text = citation.text or ""
            if not text or text in existing or len(text) > MAX_CANDIDATE_CHARACTERS:
                continue
            if considered_chars + len(text) > MAX_POOL_CHARACTERS:
                break
            considered_chars += len(text)

            # No date-invalid citation can enter the candidate pool.
            evidence = build_evidence_snippet(
                hit, citation,
                date_from=date_from,
                date_to=date_to,
                allowed_years=allowed_years,
            )
            if evidence is None:
                continue
            ok, _, _, _ = match_topic(
                evidence.text, hit.subject, hit.article_title, term_groups
            )
            if ok:
                continue
            weak_ok, hit_terms, scope, groups = match_topic(
                evidence.text, hit.subject, hit.article_title, term_groups,
                min_groups_required=1,
            )
            # A title-only match is not enough for rescuing a citation.
            if not weak_ok or scope not in ("text", "mixed"):
                continue
            evidence.match_policy = "bounded_rescue"
            evidence.match_scope = scope
            evidence.group_hits = groups
            evidence.weak_evidence = True
            evidence.synonym_hits = sorted(hit_terms)
            candidates.append((
                -groups, -_score(hit.score), hit.source_hit_ordinal,
                citation_order, evidence,
            ))
        if len(candidates) >= MAX_POOL_CANDIDATES:
            break

    # Prefer more axes, then ES source ranking, then earliest citation;
    # cap additional Evidence and avoid a single hit monopolizing refill.
    candidates.sort(key=lambda item: item[:4])
    selected = []
    added_per_origin = {}
    used_text = set()
    for _, _, origin, _, evidence in candidates:
        if len(selected) >= TARGET_EVIDENCE_COUNT - len(strict_evidence):
            break
        if added_per_origin.get(origin, 0) >= MAX_RESCUE_PER_DOCUMENT:
            continue
        text_key = (origin, evidence.text)
        if text_key in used_text:
            continue
        used_text.add(text_key)
        added_per_origin[origin] = added_per_origin.get(origin, 0) + 1
        selected.append(evidence)
    return selected
