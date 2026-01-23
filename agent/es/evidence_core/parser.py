#agent/es/evidence_core/parser.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import EvidenceBuildConfig, HitDoc, Citation
from .json_utils import as_blocks
from .date_utils import (
    parse_article_date_iso,
    collect_timeline_dates,
    infer_date_for_snippet,
    is_valid_year,
)
from .snippet import make_fallback_snippet


def parse_es_hits(
    es_hits: List[Dict[str, Any]],
    *,
    query_for_snippet: str,
    config: EvidenceBuildConfig,
) -> Tuple[List[HitDoc], Dict[str, int]]:
    stats = {
        "n_es_hits": len(es_hits or []),
        "n_inner_used": 0,
        "n_fallback_used": 0,
        "n_total_citations": 0,
    }

    out_hits: List[HitDoc] = []

    for h in es_hits or []:
        src = h.get("_source", {}) or {}
        raw_content = ((src.get("rawInfo") or {}).get("content") or "").strip()

        subject = (src.get("communication", {}) or {}).get("subject")

        # article_title：從 multidim_event_json blocks 擷取（避免 str/dict/list 不一致）
        article_title = None
        blocks = as_blocks(src.get("multidim_event_json"))
        if blocks:
            article_title = blocks[0].get("article_title")

        # timeline / article date
        tl_dates = collect_timeline_dates(src, topk=config.timeline_dates_topk)
        article_date_iso = parse_article_date_iso(raw_content) or (tl_dates[0] if tl_dates else None)
        
        # citations: inner_hits 優先
        citations: List[Citation] = []
        ih = (h.get("inner_hits") or {}).get("evi") or {}
        ih_hits = (ih.get("hits") or {}).get("hits") or []
        if ih_hits:
            for eh in ih_hits[:config.inner_hit_topk]:
                esrc = (eh.get("_source") or {})
                txt = esrc.get("text")
                sid = esrc.get("source_id")
                pid = esrc.get("paragraph_id")

                if not txt:
                    nested = (esrc.get("multidim_event_json", {}) or {}).get("evidence_snippets", {}) or {}
                    txt = nested.get("text")
                    sid = nested.get("source_id")
                    pid = nested.get("paragraph_id")

                if txt:
                    citations.append(Citation(text=txt, source_id=sid, paragraph_id=pid))

            if citations:
                stats["n_inner_used"] += 1

        # fallback
        if not citations:
            snippet = make_fallback_snippet(raw_content, query_for_snippet or "", width=config.fallback_width)
            if snippet:
                stats["n_fallback_used"] += 1
                citations.append(Citation(text=snippet))

        stats["n_total_citations"] += len(citations)

        # per-citation date inference + attach uuid/subject
        uuid = src.get("uuid")
        for c in citations:
            di = infer_date_for_snippet(c.text or "", article_date_iso, tl_dates)
            if di:
                c.date_iso = di
            c.uuid = uuid
            c.subject = subject

        for c in citations:
            if c.date_iso and not is_valid_year(c.date_iso):
                c.date_iso = None

        out_hits.append(HitDoc(
            uuid=uuid,
            subject=subject,
            article_title=article_title,
            score=h.get("_score"),
            raw_content=raw_content,
            citations=citations[:config.citations_per_doc],
            article_date_iso=article_date_iso,
            event_dates=tl_dates[:config.timeline_dates_topk],
            selectedMessage=src.get("selectedMessage"),
            highValue=(((src.get("ai") or {}).get("classLabels") or {}).get("highValue")),
        ))

    return out_hits, stats
