"""Compatibility entrypoint for live date refill with optional local review."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple
from agent.es.arc_review_scope import FinalReviewInput, observe_final_review_scope
from agent.es.date_refill import (
    MAX_DATE_CANDIDATES, MIN_DATE_CANDIDATES, DATE_SCAN_MULTIPLIER, MAX_PAGE_SIZE,
    _hits, _total, _dedupe_key, refill_date_filtered_evidence as _refill,
)


def refill_date_filtered_evidence(
    *,
    body: Dict[str, Any],
    first_response: Dict[str, Any],
    requested_size: int,
    search_next: Callable[[Dict[str, Any]], Dict[str, Any]],
    build_evidence: Callable[[List[dict]], Tuple[List[dict], List[dict], int]],
    max_candidates: int = MAX_DATE_CANDIDATES,
    admit_next_page: Callable[[], bool] | None = None,
    arc_review_scope: FinalReviewInput | None = None,
) -> Tuple[List[dict], List[dict], int, Dict[str, Any]]:
    observer = None
    if type(arc_review_scope) is FinalReviewInput:
        def observer(**kwargs):
            observe_final_review_scope(arc_review_scope, **kwargs)
    return _refill(
        body=body, first_response=first_response, requested_size=requested_size,
        search_next=search_next, build_evidence=build_evidence,
        max_candidates=max_candidates, admit_next_page=admit_next_page,
        observe_final=observer,
    )
