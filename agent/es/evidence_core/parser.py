#agent/es/evidence_core/parser.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import EvidenceBuildConfig, HitDoc, Citation
from .json_utils import as_blocks, json_load_maybe
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

    def named_inner_hits(node: Any, name: str) -> List[Dict[str, Any]]:
        """Find child inner hits in a multi-level nested ES response."""
        if isinstance(node, list):
            found: List[Dict[str, Any]] = []
            for value in node:
                found.extend(named_inner_hits(value, name))
            return found
        if not isinstance(node, dict):
            return []
        found = []
        named = (node.get("inner_hits") or {}).get(name)
        if isinstance(named, dict):
            found.extend(((named.get("hits") or {}).get("hits") or []))
        for value in node.values():
            if isinstance(value, (dict, list)):
                found.extend(named_inner_hits(value, name))
        return found

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
        mapped_article_date = next(
            (block.get("article_date_iso") for block in blocks if block.get("article_date_iso")),
            None,
        )
        article_date_iso = (
            mapped_article_date
            or parse_article_date_iso(raw_content)
            or (tl_dates[0] if tl_dates else None)
        )
        
        # citations: inner_hits 優先
        citations: List[Citation] = []
        ih_hits = named_inner_hits(h, "evi")
        if ih_hits:
            for eh in ih_hits[:config.inner_hit_topk]:
                esrc = (eh.get("_source") or {})
                txt = esrc.get("text")
                sid = esrc.get("source_id")
                pid = esrc.get("paragraph_id")
                event_ids = esrc.get("event_ids") or []

                if not txt:
                    nested = {}
                    for block in as_blocks(esrc.get("multidim_event_json")):
                        snippets = json_load_maybe(block.get("evidence_snippets") or [])
                        if isinstance(snippets, dict):
                            snippets = [snippets]
                        if not isinstance(snippets, list):
                            snippets = []
                        nested = next((item for item in snippets if isinstance(item, dict)), {})
                        if nested:
                            break
                    txt = nested.get("text")
                    sid = nested.get("source_id")
                    pid = nested.get("paragraph_id")
                    event_ids = nested.get("event_ids") or []

                if txt:
                    if isinstance(event_ids, str):
                        event_ids = [event_ids]
                    citations.append(Citation(
                        text=txt,
                        source_id=sid,
                        paragraph_id=pid,
                        event_ids=[str(item) for item in event_ids if item],
                    ))

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
