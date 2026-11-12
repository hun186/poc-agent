"""Bounded source-only Evidence refill for ES inner_hits omissions.

Uses the existing parser's block-local Event/Timeline linker on a narrow,
source-only projection. No new ES query, LLM call, source text log, or date
relaxation. Returns candidates; the builder owns actual acceptance.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

from .json_utils import as_blocks, json_load_maybe
from .models import Citation, EvidenceBuildConfig, EvidenceSnippet, HitDoc
from .parser import parse_es_hits
from .snippet import build_evidence_snippet
from .topic_match import match_topic


MAX_SOURCE_DOCUMENTS = 3
MAX_SOURCE_BLOCKS = 8
MAX_SOURCE_EVENTS_PER_FIELD = 64
MAX_SOURCE_CITATIONS_SCANNED = 48
MAX_SOURCE_CITATIONS_PARSED = 12
MAX_SOURCE_TEXT_CHARS = 2048
MAX_SOURCE_TOTAL_CHARS = 32768
MAX_SOURCE_JSON_CHARS = 160000
MAX_SOURCE_CANDIDATES = 12


def _bounded_records(value: Any, max_count: int) -> bool:
    """Reject oversized structured Event/Timeline collections without parsing."""
    if isinstance(value, str) and len(value) > MAX_SOURCE_JSON_CHARS:
        return False
    value = json_load_maybe(value)
    if isinstance(value, list):
        return len(value) <= max_count
    return value is None or isinstance(value, dict)


def _source_projection(source: Any) -> Optional[dict]:
    """Bound the source excerpts *before* invoking the normal date linker."""
    if not isinstance(source, dict):
        return None
    raw_blocks = source.get("multidim_event_json")
    if isinstance(raw_blocks, str) and len(raw_blocks) > MAX_SOURCE_JSON_CHARS:
        return None
    blocks = as_blocks(raw_blocks)
    if not blocks or len(blocks) > MAX_SOURCE_BLOCKS:
        return None

    projected: List[dict] = []
    seen_citations = 0
    kept_citations = 0
    total_chars = 0
    has_structured = False
    for block in blocks:
        if not _bounded_records(block.get("Event"), MAX_SOURCE_EVENTS_PER_FIELD):
            return None
        if not _bounded_records(block.get("Event_Timeline"), MAX_SOURCE_EVENTS_PER_FIELD):
            return None
        events = json_load_maybe(block.get("Event"))
        timeline = json_load_maybe(block.get("Event_Timeline"))
        if events or timeline:
            has_structured = True

        snippets = block.get("evidence_snippets")
        if isinstance(snippets, str) and len(snippets) > MAX_SOURCE_JSON_CHARS:
            return None
        snippets = json_load_maybe(snippets)
        if isinstance(snippets, dict):
            snippets = [snippets]
        if not isinstance(snippets, list):
            snippets = []

        output_snippets = []
        for item in snippets:
            if seen_citations >= MAX_SOURCE_CITATIONS_SCANNED:
                break
            seen_citations += 1
            if kept_citations >= MAX_SOURCE_CITATIONS_PARSED:
                break
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if len(text) > MAX_SOURCE_TEXT_CHARS:
                continue
            if total_chars + len(text) > MAX_SOURCE_TOTAL_CHARS:
                break
            # Minimal allowlisted fields prevent copying arbitrary ES properties.
            output_snippets.append({
                "text": text,
                "source_id": item.get("source_id"),
                "paragraph_id": item.get("paragraph_id"),
                "event_ids": item.get("event_ids"),
            })
            kept_citations += 1
            total_chars += len(text)
        projected.append({
            "article_title": block.get("article_title"),
            "article_date_iso": block.get("article_date_iso"),
            "Event": events,
            "Event_Timeline": timeline,
            "evidence_snippets": output_snippets,
        })
    if not has_structured or not kept_citations:
        return None
    return {
        "uuid": source.get("uuid"),
        "communication": {"subject": None},
        "multidim_event_json": projected,
    }


def _identity(citation: Citation) -> tuple:
    return (
        citation.text, citation.source_id, citation.paragraph_id,
        tuple(citation.event_ids),
        tuple((p.source, p.precision, p.time_iso, p.start, p.end)
              for p in citation.linked_times),
    )


def _score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return score if math.isfinite(score) else 0.0


# (original HitDoc, parsed Citation, validated Evidence)
SourceCandidate = Tuple[HitDoc, Citation, EvidenceSnippet]


def source_refill_candidates(
    es_hits: List[Dict[str, Any]],
    parsed_hits: List[HitDoc],
    strict_evidence: List[EvidenceSnippet],
    *,
    query_for_snippet: str,
    date_from: Optional[str],
    date_to: Optional[str],
    allowed_years: Optional[Set[int]],
    term_groups: List[Set[str]],
) -> Tuple[List[SourceCandidate], List[SourceCandidate]]:
    """Find strict-first then weak source citations from anchored ES documents.

    The original source-hit ordinal is the only cross-stage document identity.
    Only a strict Evidence TEXT anchor can authorize examining its own _source.
    """
    if not 1 <= len(strict_evidence) < 3 or len(term_groups) < 2:
        return [], []
    anchors = {
        ev.source_hit_ordinal for ev in strict_evidence
        if not ev.weak_evidence and ev.match_scope in ("text", "mixed")
    }
    if not anchors:
        return [], []
    candidates = []
    examined_docs = 0
    for h in parsed_hits:
        ordinal = h.source_hit_ordinal
        if ordinal not in anchors or ordinal < 0 or ordinal >= len(es_hits):
            continue
        if examined_docs >= MAX_SOURCE_DOCUMENTS:
            break
        examined_docs += 1
        es_hit = es_hits[ordinal]
        if not isinstance(es_hit, dict) or not isinstance(es_hit.get("inner_hits"), dict):
            # Parser already scanned _source when inner_hits were unavailable.
            continue
        projected = _source_projection(es_hit.get("_source"))
        if projected is None or projected.get("uuid") != h.uuid:
            continue
        source_hits, _ = parse_es_hits(
            [{"_source": projected, "_score": h.score}],
            query_for_snippet=query_for_snippet,
            config=EvidenceBuildConfig(
                citations_per_doc=MAX_SOURCE_CITATIONS_PARSED,
                inner_hit_topk=1, fallback_width=0,
            ),
        )
        if len(source_hits) != 1:
            continue
        used = {_identity(c) for c in h.citations}
        for index, citation in enumerate(source_hits[0].citations):
            if len(candidates) >= MAX_SOURCE_CANDIDATES:
                break
            if citation.block_index is None or not citation.linked_complete or not citation.linked_times:
                # No borrowing dates from article or unknown Event linkage.
                continue
            identity = _identity(citation)
            if identity in used:
                continue
            used.add(identity)
            evidence = build_evidence_snippet(
                h, citation,
                date_from=date_from, date_to=date_to, allowed_years=allowed_years,
            )
            if evidence is None:
                continue
            text_ok, _, _, _ = match_topic(
                evidence.text, None, None, term_groups,
                min_groups_required=1,
            )
            if not text_ok:
                continue
            strict_ok, terms, scope, groups = match_topic(
                evidence.text, h.subject, h.article_title, term_groups,
            )
            evidence.match_policy = "strict" if strict_ok else "bounded_rescue"
            evidence.match_scope = scope if strict_ok else "text"
            evidence.group_hits = groups
            evidence.synonym_hits = sorted(terms)
            evidence.weak_evidence = not strict_ok
            candidates.append((
                (0 if strict_ok else 1, -groups, -_score(h.score), ordinal, index),
                h, citation, evidence,
            ))
        if len(candidates) >= MAX_SOURCE_CANDIDATES:
            break

    candidates.sort(key=lambda c: c[0])
    strict = [(h, c, ev) for key, h, c, ev in candidates if key[0] == 0]
    weak = [(h, c, ev) for key, h, c, ev in candidates if key[0] == 1]
    return strict, weak
