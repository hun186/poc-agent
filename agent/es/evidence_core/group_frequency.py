"""ARC A3: bounded, count-only group frequency on one parser slice.

This is not an ES index/document-frequency aggregation, nor an unbiased
sample. Never change scores, selection, admission, dates or query scope.
"""
from __future__ import annotations

import json
import logging
import math

from .models import HitDoc
from .snippet import build_evidence_snippet
from .text_norm import normalize_for_match

MAX_HITS = 128
MAX_ROWS = 256
MAX_ROWS_PER_HIT = 8
MAX_CHARS = 131072
MAX_ROW_CHARS = 4096
MAX_GROUPS = 16
MAX_TERMS = 64
MAX_TERM_CHARS = 160
_LOG = logging.getLogger("sraf.arc.group_frequency")


def observe_group_frequency(
    hits: list[HitDoc], groups: list[set[str]], *,
    date_from: str | None, date_to: str | None,
    allowed_years: set[int] | None,
) -> dict:
    result = {
        "schema": "sraf_arc_group_frequency_v1",
        "scope": "ordered_parser_slice_date_valid_sample_text_only",
        "status": "unsupported_groups",
        "available_hits": len(hits), "scanned_hits": 0,
        "inspected_rows": 0, "eligible_rows": 0, "eligible_hits": 0,
        "text_chars": 0, "sample_limited": False, "groups": [],
    }
    # Bound both the matcher dimensions and raw input lengths before work.
    if not 1 <= len(groups) <= MAX_GROUPS:
        return result
    if sum(len(group) for group in groups) > MAX_TERMS:
        return result
    normalized = []
    for group in groups:
        if not group or any(type(term) is not str or not
                            0 < len(term) <= MAX_TERM_CHARS for term in group):
            return result
        terms = {normalize_for_match(term) for term in group}
        terms.discard("")
        if not terms:
            return result
        normalized.append(terms)

    counts = [0] * len(normalized)
    limited = len(hits) > MAX_HITS
    for hit in hits[:MAX_HITS]:
        if result["inspected_rows"] >= MAX_ROWS or result["text_chars"] >= MAX_CHARS:
            limited = True
            break
        result["scanned_hits"] += 1
        if len(hit.citations) > MAX_ROWS_PER_HIT:
            limited = True
        eligible = False
        matched: set[int] = set()
        for citation in hit.citations[:MAX_ROWS_PER_HIT]:
            if result["inspected_rows"] >= MAX_ROWS or result["text_chars"] >= MAX_CHARS:
                limited = True
                break
            result["inspected_rows"] += 1
            text = citation.text
            if (type(text) is not str or not 0 < len(text) <= MAX_ROW_CHARS
                    or result["text_chars"] + len(text) > MAX_CHARS):
                limited = True
                continue
            result["text_chars"] += len(text)
            ev = build_evidence_snippet(
                hit, citation, date_from=date_from, date_to=date_to,
                allowed_years=allowed_years,
            )
            if ev is None:
                continue
            body = normalize_for_match(ev.text)
            if not body:
                continue
            eligible = True
            result["eligible_rows"] += 1
            for idx, aliases in enumerate(normalized):
                if idx not in matched and any(alias in body for alias in aliases):
                    matched.add(idx)
        if eligible:
            result["eligible_hits"] += 1
            for idx in matched:
                counts[idx] += 1

    n = result["eligible_hits"]
    result.update(
        status="observed_sample" if n else "no_date_eligible_sample",
        sample_limited=limited,
        groups=[{
            "group_ordinal": idx + 1, "sample_hit_frequency": count,
            "idf_milli": round(1000 * math.log((n + 1) / (count + 1))) if n else None,
        } for idx, count in enumerate(counts)],
    )
    return result


def log_group_frequency(observation: dict) -> None:
    # Only the internal producer above calls this logger; no user/model terms,
    # document identifiers, raw text, query, date or source names in output.
    _LOG.warning("SRAF_ARC_GROUP_FREQUENCY=%s",
                 json.dumps(observation, sort_keys=True, separators=(",", ":")))
