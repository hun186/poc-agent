"""Bounded refill after structured Evidence date filtering.

ES date constraints on legacy untyped time_iso must be candidate-wide.
This module refills filtered results without changing the query/scoring contract,
while making incomplete candidate scans visible instead of claiming no matches.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple


MAX_DATE_CANDIDATES = 10_000  # ES default max_result_window; never cross it with from + size
MIN_DATE_CANDIDATES = 256
DATE_SCAN_MULTIPLIER = 32
MAX_PAGE_SIZE = 1_000


def _hits(result: Any) -> List[dict]:
    if not isinstance(result, dict):
        return []
    rows = ((result.get("hits") or {}).get("hits") or [])
    return rows if isinstance(rows, list) else []


def _total(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None
    total = ((result.get("hits") or {}).get("total"))
    if isinstance(total, int):
        return total
    if isinstance(total, dict) and total.get("relation") == "eq":
        value = total.get("value")
        return value if isinstance(value, int) else None
    return None


def _dedupe_key(hit: dict) -> tuple | None:
    # Only the ES pair (_index, _id) establishes document identity.
    # Application UUID may recur across indices; do not deduplicate it.
    doc_id = hit.get("_id")
    if doc_id is not None:
        return (hit.get("_index"), str(doc_id))
    return None


def refill_date_filtered_evidence(
    *,
    body: Dict[str, Any],
    first_response: Dict[str, Any],
    requested_size: int,
    search_next: Callable[[Dict[str, Any]], Dict[str, Any]],
    build_evidence: Callable[[List[dict]], Tuple[List[dict], List[dict], int]],
    max_candidates: int = MAX_DATE_CANDIDATES,
) -> Tuple[List[dict], List[dict], int, Dict[str, Any]]:
    """Refill eligible documents, preserving original ES score order.

    Uses bounded ES `from` pages (up to the default 10k result window).
    Re-evaluating the accumulated source hits preserves the existing global
    strict/relaxed Evidence matching contract across page boundaries.

    It is *not* a full-index scan: return a precise incomplete flag if the
    cap is hit before enough date-valid documents are found.
    """
    if requested_size < 1:
        raise ValueError("requested_size must be positive")
    if not (1 <= max_candidates <= MAX_DATE_CANDIDATES):
        raise ValueError("max_candidates must be in 1..10000")

    budget = min(max_candidates, max(MIN_DATE_CANDIDATES, requested_size * DATE_SCAN_MULTIPLIER))
    page_size = min(MAX_PAGE_SIZE, max(32, requested_size))
    raw: List[dict] = []
    seen: set[tuple] = set()
    scanned = 0
    pages = 0
    response = first_response
    expected_page_size = min(int(body.get("size") or requested_size), budget)
    eligible_hits: List[dict] = []
    eligible_evidence: List[dict] = []
    matched_synonyms = 0
    exhausted = False

    while True:
        batch = _hits(response)
        pages += 1
        scanned += len(batch)
        for hit in batch:
            if not isinstance(hit, dict):
                continue
            key = _dedupe_key(hit)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            raw.append(hit)

        if raw:
            eligible_hits, eligible_evidence, matched_synonyms = build_evidence(raw)
        if len(eligible_hits) >= requested_size:
            break

        count = _total(response)
        exhausted = (
            len(batch) < expected_page_size or
            (count is not None and scanned >= count) or
            not batch
        )
        if exhausted or scanned >= budget:
            break

        next_size = min(page_size, budget - scanned)
        if next_size <= 0:
            break
        next_body = dict(body)
        next_body["size"] = next_size
        next_body["from"] = scanned
        response = search_next(next_body)
        expected_page_size = next_size

    # The builder returns a private ordinal scoped to the accumulated ES hit
    # array. Unlike source.uuid this preserves index/id identity, and no
    # evidence can be silently attributed to another same-UUID document.
    origin = "__sraf_source_hit_ordinal"
    if any(type(row.get(origin)) is not int for row in eligible_hits + eligible_evidence):
        raise ValueError("date-qualified Evidence origin missing from builder")
    selected = eligible_hits[:requested_size]
    retained_ordinals = {row[origin] for row in selected}
    selected_evidence = [
        row for row in eligible_evidence if row[origin] in retained_ordinals
    ]
    # Internal provenance is used only for filtering and never exposed as a
    # new public result field to report/LLM consumers.
    result_hits = [{k: v for k, v in row.items() if k != origin} for row in selected]
    result_evidence = [
        {k: v for k, v in row.items() if k != origin}
        for row in selected_evidence
    ]
    result_synonyms = sum(1 for row in result_evidence if row.get("synonym_hits"))
    limit_reached = (
        len(result_hits) < requested_size and not exhausted and scanned >= budget
    )
    return result_hits, result_evidence, result_synonyms, {
        "enabled": True,
        "requested_size": requested_size,
        "candidate_scan_limit": budget,
        "candidates_scanned": scanned,
        "candidates_unique": len(raw),
        "pages_fetched": pages,
        "result_count": len(result_hits),
        "result_limit_satisfied": len(result_hits) >= requested_size,
        "search_exhausted": exhausted,
        "incomplete_due_to_scan_limit": limit_reached,
        "note": "candidate_scan_limit_reached" if limit_reached else (
            "requested_size_satisfied" if len(result_hits) >= requested_size
            else "es_candidates_exhausted"
        ),
    }
