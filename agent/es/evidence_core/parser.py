#agent/es/evidence_core/parser.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .models import EvidenceBuildConfig, HitDoc, Citation
from .trace import EvidenceTrace
from .json_utils import as_blocks, json_load_maybe
from .date_utils import (
    parse_article_date_iso,
    collect_timeline_dates,
    infer_date_for_snippet,
    is_valid_year,
    explicit_full_date_in_text,
)
from .snippet import make_fallback_snippet
from ..reference_text import get_reference_text
from ..event_time import collect_linked_times, linked_dates_for_ids, event_ids_in_block


def parse_es_hits(
    es_hits: List[Dict[str, Any]],
    *,
    query_for_snippet: str,
    config: EvidenceBuildConfig,
    trace: EvidenceTrace | None = None,
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

    def citation_from_source(item: Any, block_index: int) -> Citation | None:
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
            block_index=block_index,
        )

    for source_hit_ordinal, h in enumerate(es_hits or []):
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

        # Structured Event/Timeline correlation takes priority over text heuristics.
        time_lookup, has_structured_events = collect_linked_times(blocks)
        # Keep local block scope; IDs in separate multidim objects can repeat.
        local_time_lookups = [collect_linked_times([block])[0] for block in blocks]
        block_declared_ids = [event_ids_in_block(block) for block in blocks]
        # timeline / article date
        tl_dates = collect_timeline_dates(src, topk=config.timeline_dates_topk)
        mapped_article_date = next(
            (block.get("article_date_iso") for block in blocks if block.get("article_date_iso")),
            None,
        )
        article_date_iso = (
            mapped_article_date
            if mapped_article_date else (
                None if has_structured_events else parse_article_date_iso(raw_content)
            )
        )  # Do not infer publication from event dates in structured content.
        
        # citations: inner_hits 優先
        citations: List[Citation] = []
        chosen_mode = "none"
        source_items_examined = 0
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

                # ES nested inner_hits identify the enclosing multidim block
                # through their _nested chain. Absent offset is only safe to
                # infer if there is precisely one block in the parent source.
                block_index = 0 if len(blocks) == 1 else None
                nested_location = eh.get("_nested")
                while isinstance(nested_location, dict):
                    if str(nested_location.get("field", "")).split(".")[-1] == "multidim_event_json":
                        candidate = nested_location.get("offset")
                        block_index = candidate if type(candidate) is int and 0 <= candidate < len(blocks) else None
                        break
                    nested_location = nested_location.get("_nested")

                if txt:
                    citations.append(Citation(
                        text=txt,
                        source_id=normalized_text(sid) or None,
                        paragraph_id=normalized_text(pid) or None,
                        event_ids=event_ids,
                        block_index=block_index,
                    ))

            if citations:
                chosen_mode = "inner"
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
                    if trace is not None:
                        source_items_examined += 1
                    citation = citation_from_source(item, block_index)
                    if citation is not None:
                        citations.append(citation)
                    if len(citations) >= config.citations_per_doc:
                        break
                if len(citations) >= config.citations_per_doc:
                    break
            if citations:
                chosen_mode = "source"
                stats["n_source_evidence_used"] += 1

        # Legacy fallback, only when neither inner hits nor structured source won.
        if not citations:
            snippet = make_fallback_snippet(raw_content, query_for_snippet or "", width=config.fallback_width)
            if snippet:
                chosen_mode = "fallback"
                stats["n_fallback_used"] += 1
                citations.append(Citation(text=snippet))

        stats["n_total_citations"] += len(citations)
        if trace is not None:
            raw_source_count = 0
            for block in blocks:
                raw_items = json_load_maybe(block.get("evidence_snippets"))
                if isinstance(raw_items, list):
                    raw_source_count += len(raw_items)
                elif isinstance(raw_items, dict):
                    raw_source_count += 1
            trace.parsed_hit(
                ordinal=source_hit_ordinal,
                source_count=raw_source_count,
                inner_count=len(ih_hits),
                parsed_count=len(citations),
                selected_count=min(len(citations), config.citations_per_doc),
                mode=chosen_mode,
                # If source parsing hit its cap, remaining source items were
                # NOT examined. Their date/topic/validity is still unknown.
                source_uninspected_after_cap=(
                    max(0, raw_source_count - source_items_examined)
                    if chosen_mode == "source" else 0
                ),
            )

        # Link evidence by event_ids; never assign unrelated article dates to
        # a structured Event. Legacy documents without Event/Timeline preserve
        # their historical publication-date fallback in snippet.py.
        uuid = src.get("uuid")
        for c in citations:
            if c.block_index is not None:
                scoped_lookup = local_time_lookups[c.block_index]
            elif len(blocks) > 1:
                # A missing inner-hit parent offset is safe only when ALL
                # referenced IDs are declared in exactly one SAME block.
                # Count undated/invalid IDs too: otherwise an undated E1 in
                # block 0 could borrow block 1's valid E1 event time.
                owners = set()
                for eid in c.event_ids:
                    occurrences = [
                        i for i, declared in enumerate(block_declared_ids)
                        if eid in declared
                    ]
                    if len(occurrences) != 1:
                        owners.clear()
                        break
                    owners.add(occurrences[0])
                scoped_lookup = (
                    local_time_lookups[next(iter(owners))]
                    if c.event_ids and len(owners) == 1 else {}
                )
            else:
                scoped_lookup = time_lookup
            c.linked_times, c.linked_complete = linked_dates_for_ids(c.event_ids, scoped_lookup)
            if c.linked_times:
                if c.linked_complete and len(c.linked_times) == 1:
                    point = c.linked_times[0]
                    if point.precision in ("day", "hour", "minute", "second"):
                        c.date_iso = point.start
            elif has_structured_events:
                # If the link is dangling, only trust an explicit full date in
                # evidence text. Do NOT borrow article year for an ambiguous MD.
                c.date_iso = explicit_full_date_in_text(c.text)
            else:
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
            has_structured_events=has_structured_events,
            source_hit_ordinal=source_hit_ordinal,
            selectedMessage=src.get("selectedMessage"),
            highValue=(((src.get("ai") or {}).get("classLabels") or {}).get("highValue")),
        ))

    return out_hits, stats
