"""Deterministic, non-actionable health of ONE Evidence parser slice (#413).

A slice is not an ES request, full result set or report. Its counters cannot
prove full recall, query intent, topic breadth, completeness or readiness to
spend another LLM/ES call. This module never receives raw content or IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RetrievalSliceHealth:
    reason: str
    parsed: int
    date_eligible: int
    strict_accepted: int
    known_uninspected: int
    known_capped: int


def _count(counters: Mapping[str, int], key: str) -> int:
    value = counters.get(key, 0)
    if type(value) is not int or value < 0 or value > 1_000_000:
        raise ValueError("invalid_retrieval_count")
    return value


def assess_retrieval_slice(
    counters: Mapping[str, int], *, strict_accepted: int,
) -> RetrievalSliceHealth:
    """Return one conservative reason, never a decision to re-query.

    "date_eligible" counts only citations that passed the canonical
    date/linkage checks *within this parser slice*: strict accepted plus
    strict topic-rejected. It is not the number of date-valid ES documents.
    Truncated/unreturned rows are unknown, not presumed relevant.
    """
    if type(strict_accepted) is not int or not 0 <= strict_accepted <= 1_000_000:
        raise ValueError("invalid_retrieval_count")
    parsed = _count(counters, "parser.citations_selected")
    accepted = _count(counters, "strict.accepted")
    if accepted != strict_accepted or strict_accepted > parsed:
        raise ValueError("inconsistent_retrieval_counts")

    date_eligible = accepted + _count(counters, "strict.topic_rejected")
    known_uninspected = _count(counters, "parser.source_uninspected_after_cap")
    known_capped = (
        _count(counters, "parser.citations_capped")
        + _count(counters, "valid_budget.not_selected")
    )
    if date_eligible > parsed:
        raise ValueError("inconsistent_retrieval_counts")

    if known_uninspected or known_capped:
        reason = "SEARCH_INCOMPLETE"
    elif parsed == 0:
        reason = "NO_PARSED_CANDIDATES"
    elif date_eligible == 0:
        reason = "NO_DATE_ELIGIBLE_CITATIONS"
    elif strict_accepted == 0:
        reason = "NO_STRICT_TOPIC_EVIDENCE"
    elif strict_accepted <= 2 and date_eligible >= 3:
        reason = "LOW_STRICT_COVERAGE"
    else:
        # A good-looking slice cannot certify that the entire original
        # question was covered, that ES returned every candidate, or that
        # enough deadline/token budget remains for an additional round.
        reason = "REQUEST_LEVEL_ASSESSMENT_REQUIRED"

    return RetrievalSliceHealth(
        reason=reason,
        parsed=parsed,
        date_eligible=date_eligible,
        strict_accepted=strict_accepted,
        known_uninspected=known_uninspected,
        known_capped=known_capped,
    )
