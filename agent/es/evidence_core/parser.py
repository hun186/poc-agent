#agent/es/evidence_core/parser.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import EvidenceBuildConfig, HitDoc, Citation
from .json_utils import as_blocks, json_load_maybe
from .date_utils import (
    parse_article_date_iso,
    collect_timeline_dates,
    collect_event_time_records,
    normalize_iso_date,
    infer_date_for_snippet,
    is_valid_year,
)
from .snippet import make_fallback_snippet
from ..reference_text import get_reference_text


def parse_es_hits(
    es_hits: List[Dict[str, Any]],
    *,
    query_for_snippet: str,
    config: EvidenceBuildConfig,
) -> Tuple[List[HitDoc], Dict[str, int]]:
    stats = {
        "n_es_hits": len(es_hits or []),
        "n_inner_used": 0,
        "n_source_evidence_used": 0,
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

    def normalized_text(value: Any) -> str:
        """Normalize scalar/one-element-array ES source values without raising."""
        value = json_load_maybe(value)
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            for item in value:
                text = normalized_text(item)
                if text:
                    return text
        return ""

    def normalized_ids(value: Any) -> List[str]:
        value = json_load_maybe(value)
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]

    def citation_from_source(item: Any) -> Citation | None:
        if not isinstance(item, dict):
            return None
        text = normalized_text(item.get("text"))
        if not text:
            return None
        return Citation(
            text=text,
            source_id=normalized_text(item.get("source_id")) or None,
            paragraph_id=normalized_text(item.get("paragraph_id")) or None,
            event_ids=normalized_ids(item.get("event_ids")),
        )

    for h in es_hits or []:
        src = h.get("_source", {}) or {}
        # `raw_content` is retained as an internal compatibility name. Its value
        # is the configured context-rich agent reference text, which may be raw
        # source material or a refined, coherent document.
        raw_content = get_reference_text(src)

        subject = (src.get("communication", {}) or {}).get("subject")

        # article_title：從 multidim_event_json blocks 擷取（避免 str/dict/list 不一致）
        article_title = None
        blocks = as_blocks(src.get("multidim_event_json"))
        if blocks:
            article_title = blocks[0].get("article_title")

        # timeline / article date
        tl_dates = collect_timeline_dates(src, topk=config.timeline_dates_topk)
        time_records = collect_event_time_records(src)
        all_dates = list(dict.fromkeys(
            tl_dates + [record.interval.iso for record in time_records]
        ))[:config.timeline_dates_topk]
        mapped_article_date = next(
            (normalize_iso_date(block.get("article_date_iso"))
             for block in blocks if normalize_iso_date(block.get("article_date_iso"))),
            None,
        )
        # An Event timestamp is NOT an article publication date.
        article_date_iso = mapped_article_date or parse_article_date_iso(raw_content)
        
        # citations: inner_hits 優先
        citations: List[Citation] = []
        ih_hits = named_inner_hits(h, "evi")
        if ih_hits:
            for eh in ih_hits[:config.inner_hit_topk]:
                esrc = (eh.get("_source") or {})
                txt = normalized_text(esrc.get("text"))
                sid = esrc.get("source_id")
                pid = esrc.get("paragraph_id")
                event_ids = normalized_ids(esrc.get("event_ids"))

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
                    txt = normalized_text(nested.get("text"))
                    sid = nested.get("source_id")
                    pid = nested.get("paragraph_id")
                    event_ids = normalized_ids(nested.get("event_ids"))

                if txt:
                    citations.append(Citation(
                        text=txt,
                        source_id=normalized_text(sid) or None,
                        paragraph_id=normalized_text(pid) or None,
                        event_ids=event_ids,
                    ))

            if citations:
                stats["n_inner_used"] += 1

        # A document can match another nested clause and therefore have no `evi`
        # inner hit. Its selected _source still contains authoritative structured
        # evidence, so use that before considering legacy raw content.
        if not citations:
            for block_index, block in enumerate(blocks):
                snippets = json_load_maybe(block.get("evidence_snippets"))
                if isinstance(snippets, dict):
                    snippets = [snippets]
                if not isinstance(snippets, list):
                    continue
                for item in snippets:
                    citation = citation_from_source(item)
                    if citation is not None:
                        citation.block_index = block_index
                        citations.append(citation)
                    if len(citations) >= config.citations_per_doc:
                        break
                if len(citations) >= config.citations_per_doc:
                    break
            if citations:
                stats["n_source_evidence_used"] += 1

        # Legacy fallback, only when neither inner hits nor structured source won.
        if not citations:
            snippet = make_fallback_snippet(raw_content, query_for_snippet or "", width=config.fallback_width)
            if snippet:
                stats["n_fallback_used"] += 1
                citations.append(Citation(text=snippet))

        stats["n_total_citations"] += len(citations)

        # per-citation date inference + attach uuid/subject
        uuid = src.get("uuid")
        for c in citations:
            matches = [
                record for record in time_records
                if c.event_ids and set(c.event_ids).intersection(record.event_ids)
                and (c.block_index is None or record.block_index == c.block_index)
            ]
            # Inner-hit evidence may not expose its outer block offset. Reused
            # IDs in different blocks are ambiguous: do not cross-link them.
            if c.block_index is None and len({r.block_index for r in matches}) > 1:
                matches = []
            c.linked_dates = matches
            # Only the citation's own linked temporal rows can help infer year,
            # never an unrelated timeline elsewhere in the same article.
            linked_days = [r.interval.iso for r in matches]
            day_precision_dates = [r.interval.iso for r in matches if r.interval.precision == "day"]
            di = infer_date_for_snippet(
                c.text or "", None if matches else article_date_iso, linked_days,
                day_precision_dates=day_precision_dates,
            )
            if di and is_valid_year(di):
                c.date_iso = di
            c.uuid = uuid
            c.subject = subject

        out_hits.append(HitDoc(
            uuid=uuid,
            subject=subject,
            article_title=article_title,
            score=h.get("_score"),
            raw_content=raw_content,
            citations=citations[:config.citations_per_doc],
            article_date_iso=article_date_iso,
            event_dates=all_dates,
            event_time_records=time_records,
            selectedMessage=src.get("selectedMessage"),
            highValue=(((src.get("ai") or {}).get("classLabels") or {}).get("highValue")),
        ))

    return out_hits, stats
