#agent/es/evidence_core/builder.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import EvidenceBuildConfig, EvidenceSnippet, HitDoc
from .parser import parse_es_hits
from .snippet import build_evidence_snippet
from .topic_match import match_topic
from .text_norm import normalize_for_match


logger = logging.getLogger(__name__)


def collect_snippets(
    hits: List[HitDoc],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    term_groups: List[Set[str]],
    min_groups_required: Optional[int],
) -> List[EvidenceSnippet]:
    out: List[EvidenceSnippet] = []
    for h in hits:
        for c in h.citations:
            ev = build_evidence_snippet(h, c, date_from=date_from, date_to=date_to)
            if ev is None:
                continue

            ok, hit_terms, scope, gh = match_topic(
                ev.text, h.subject, h.article_title, term_groups,
                min_groups_required=min_groups_required
            )
            if not ok:
                continue

            ev.match_policy = "relaxed" if min_groups_required is not None else "strict"
            ev.match_scope = scope
            ev.group_hits = gh

            if hit_terms:
                ev.synonym_hits = sorted(hit_terms)

            if scope == "meta":
                ev.weak_evidence = True

            out.append(ev)

    return out


def build_hits_and_evidence(
    es_hits: List[Dict[str, Any]],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    effective_terms: Optional[List[str]],
    term_groups: List[Set[str]],
    query_for_snippet: str,
    config: Optional[EvidenceBuildConfig] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    config = config or EvidenceBuildConfig()
    term_groups = term_groups or []
    effective_terms = effective_terms or []

    out_hits, stats = parse_es_hits(es_hits, query_for_snippet=query_for_snippet, config=config)

    logger.info(
        "build_hits_and_evidence: es_hits=%d out_hits=%d citations=%d inner_used=%d fallback_used=%d "
        "term_groups=%d effective_terms=%d date_range=%s~%s",
        stats["n_es_hits"], len(out_hits), stats["n_total_citations"], stats["n_inner_used"], stats["n_fallback_used"],
        len(term_groups), len(effective_terms),
        date_from or "N/A", date_to or "N/A",
    )

    # 1) strict
    evidence = collect_snippets(
        out_hits,
        date_from=date_from, date_to=date_to,
        term_groups=term_groups,
        min_groups_required=None,
    )
    logger.info("build_hits_and_evidence: evidence strict=%d", len(evidence))

    # 2) relax
    if not evidence and out_hits and term_groups:
        n = len(term_groups)
        strict_req = 1 if n <= 1 else (2 if n == 2 else 3)  # n>=3 -> 3
        for req in range(strict_req - 1, 0, -1):
            logger.warning(
                "build_hits_and_evidence: strict evidence=0 -> relax try (groups=%d strict_req=%d try_req=%d)",
                n, strict_req, req
            )
            tmp = collect_snippets(
                out_hits,
                date_from=date_from, date_to=date_to,
                term_groups=term_groups,
                min_groups_required=req,
            )
            logger.info("build_hits_and_evidence: evidence relaxed(req=%d)=%d", req, len(tmp))
            if tmp:
                evidence = tmp
                break

    # 3) fallback：無主題詞 → 每篇取第一段
    if not evidence and out_hits and not effective_terms:
        logger.warning("build_hits_and_evidence: evidence=0 and no effective_terms -> fallback pick first citation")
        for h in out_hits[:config.max_docs_for_fallback]:
            if not h.citations:
                continue
            ev = build_evidence_snippet(h, h.citations[0], date_from=date_from, date_to=date_to)
            if ev:
                evidence.append(ev)
        logger.info("build_hits_and_evidence: evidence fallback(no_terms)=%d", len(evidence))

    # 4) fallback：有主題詞但都 0 → any effective_term
    if not evidence and out_hits and effective_terms:
        logger.warning("build_hits_and_evidence: evidence=0 with effective_terms -> fallback contains-any-effective-term")
        eff_norm = [(normalize_for_match(t), t) for t in effective_terms if t]

        for h in out_hits:
            for c in h.citations:
                ev = build_evidence_snippet(h, c, date_from=date_from, date_to=date_to)
                if not ev:
                    continue

                haystack_norm = normalize_for_match((ev.text or "") + " " + (h.subject or "") + " " + (h.article_title or ""))
                hit_terms = [orig for norm, orig in eff_norm if norm and norm in haystack_norm]
                if not hit_terms:
                    continue

                ev.match_scope = "fallback_any_term"
                ev.weak_evidence = True
                ev.synonym_hits = sorted(set(hit_terms))
                evidence.append(ev)

        logger.info("build_hits_and_evidence: evidence fallback(effective_terms)=%d", len(evidence))

    # 5) filtered_hits：只留有 evidence 的 doc
    if evidence:
        kept = {e.uuid for e in evidence if e.uuid}
        filtered = [h for h in out_hits if h.uuid in kept]
    else:
        filtered = out_hits

    syn_snippets = sum(1 for e in evidence if e.synonym_hits)
    weak_cnt = sum(1 for e in evidence if e.weak_evidence)

    logger.info(
        "build_hits_and_evidence: filtered_hits=%d evidence=%d syn_snippets=%d weak=%d",
        len(filtered), len(evidence), syn_snippets, weak_cnt
    )

    # ---- 轉回 dict（維持舊回傳格式） ----
    filtered_hits_dict = [
        {
            "uuid": h.uuid,
            "subject": h.subject,
            "score": h.score,
            "citations": [
                {
                    "text": c.text,
                    "source_id": c.source_id,
                    "paragraph_id": c.paragraph_id,
                    **({"date_iso": c.date_iso} if c.date_iso else {}),
                    **({"uuid": c.uuid} if c.uuid else {}),
                    **({"subject": c.subject} if c.subject else {}),
                }
                for c in (h.citations or [])
            ],
            "article_date_iso": h.article_date_iso,
            "event_dates": h.event_dates,
            "event_date_span": {"min": min(h.event_dates), "max": max(h.event_dates)} if h.event_dates else None,
            "article_title": h.article_title,
            "selectedMessage": h.selectedMessage,
            "highValue": h.highValue,
        }
        for h in filtered
    ]

    evidence_dict = [
        {
            "uuid": e.uuid,
            "text": e.text,
            "date_iso": e.date_iso,
            "article_date_iso": e.article_date_iso,
            "subject": e.subject,
            "article_title": e.article_title,
            **({"paragraph_id": e.paragraph_id} if e.paragraph_id is not None else {}),
            **({"source_id": e.source_id} if e.source_id is not None else {}),
            **({"synonym_hits": e.synonym_hits} if e.synonym_hits else {}),
            "match_policy": e.match_policy,
            "match_scope": e.match_scope,
            "group_hits": e.group_hits,
            **({"weak_evidence": True} if e.weak_evidence else {}),
        }
        for e in evidence
    ]

    return filtered_hits_dict, evidence_dict, syn_snippets
