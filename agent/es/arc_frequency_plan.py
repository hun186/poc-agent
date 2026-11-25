"""ARC A3b offline Elasticsearch root-document frequency plan.

This module has no transport or index resolution. Future execution must bind
the exact authorized index and scope, enforce shared request budgets, and
verify the live mapping/analyzer before running. Counts describe ES matches,
not date-validated Evidence or semantic relevance.
"""
from __future__ import annotations

from datetime import date

from .query_body import _in_multidim_child, _structured_date_filter

MAX_GROUPS = 8
MAX_TERMS = 32
MAX_TERM_CHARS = 160
MAX_DATE_SPAN_DAYS = 3660
FIELD = "multidim_event_json.evidence_snippets.text"
SCOPE = "es_root_documents_with_candidate_date_filter"


def _valid_dates(first: str, last: str) -> bool:
    if type(first) is not str or type(last) is not str:
        return False
    if len(first) != 10 or len(last) != 10:
        return False
    try:
        start, end = date.fromisoformat(first), date.fromisoformat(last)
    except ValueError:
        return False
    return (
        start.isoformat() == first and end.isoformat() == last
        and 1900 <= start.year <= end.year <= 2100
        and 0 <= (end - start).days <= MAX_DATE_SPAN_DAYS
    )


def build_frequency_plan(
    groups: list[set[str]], *, date_from: str, date_to: str,
    must_high_value: bool = False, must_selected: bool = False,
) -> dict | None:
    """Build one count-only request for an explicit bounded date window.

    Root filters preserve the caller's high-value/selected restrictions.
    Nested phrase alternatives are OR within a group. Each filter bucket
    counts matching root documents once even for multiple matching snippets.
    The date predicate and phrase predicate may match different events;
    do not claim per-event or Python postfilter parity.
    """
    if not _valid_dates(date_from, date_to):
        return None
    if type(must_high_value) is not bool or type(must_selected) is not bool:
        return None
    if type(groups) is not list or not 1 <= len(groups) <= MAX_GROUPS:
        return None
    if any(type(group) is not set or not group for group in groups):
        return None
    if sum(map(len, groups)) > MAX_TERMS:
        return None
    buckets = {}
    for ordinal, group in enumerate(groups, 1):
        if any(type(term) is not str or not 0 < len(term) <= MAX_TERM_CHARS
               or term != term.strip() for term in group):
            return None
        buckets[str(ordinal)] = _in_multidim_child(
            "evidence_snippets",
            {"bool": {"should": [{"match_phrase": {FIELD: term}}
                                 for term in sorted(group)],
                      "minimum_should_match": 1}},
            outer_options={"score_mode": "none"}, score_mode="none",
        )
    filters = [_structured_date_filter(date_from, date_to)]
    if must_high_value:
        filters.append({"term": {"ai.classLabels.highValue": True}})
    if must_selected:
        filters.append({"term": {"selectedMessage": True}})
    return {
        "size": 0, "_source": False, "track_total_hits": True,
        "timeout": "2s",
        "query": {"bool": {"filter": filters}},
        "aggs": {"group_frequency": {"filters": {"filters": buckets}}},
    }


def parse_frequency_response(response: dict, *, group_count: int) -> dict:
    """Fail closed on missing, partial, approximate or inconsistent counts.

    Only count values and group ordinals are returned. A timeout, failed
    shard, lower-bound total or malformed result is not a measured zero.
    """
    result = {"scope": SCOPE, "status": "incomplete",
              "eligible_documents": None, "groups": []}
    if type(group_count) is not int or not 1 <= group_count <= MAX_GROUPS:
        return result
    if type(response) is not dict or response.get("timed_out") is not False:
        return result
    if response.get("terminated_early", False) is not False:
        return result
    shards = response.get("_shards")
    if type(shards) is not dict:
        return result
    total_shards, successful, failed = (
        shards.get(k) for k in ("total", "successful", "failed")
    )
    if (any(type(v) is not int for v in (total_shards, successful, failed))
            or total_shards <= 0 or successful != total_shards or failed != 0):
        return result
    try:
        total = response["hits"]["total"]
        if type(total) is not dict or total.get("relation") != "eq":
            return result
        count = total.get("value")
        buckets = response["aggregations"]["group_frequency"]["buckets"]
        if type(count) is not int or count < 0 or type(buckets) is not dict:
            return result
        if set(buckets) != {str(i) for i in range(1, group_count + 1)}:
            return result
        rows = []
        for ordinal in range(1, group_count + 1):
            value = buckets[str(ordinal)]["doc_count"]
            if type(value) is not int or not 0 <= value <= count:
                return result
            rows.append({"group_ordinal": ordinal, "document_frequency": value})
    except (KeyError, TypeError):
        return result
    return {"scope": SCOPE, "status": "exact_es_query_counts",
            "eligible_documents": count, "groups": rows}
