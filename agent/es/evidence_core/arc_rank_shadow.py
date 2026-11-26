"""A4 diagnostic ranking on one date/topic-validated strict Evidence prefix.

The supplied observation must be produced by the same builder invocation and
same groups. Local ordered sample frequencies are not corpus DF. This module
never returns reordered Evidence or changes admission, selection or retrieval.
"""
from __future__ import annotations

import json
import logging
import math

from ..arc_request_budget import ArcUnits, current_arc_budget
from ..arc_frequency_plan import SCOPE as NATIVE_SCOPE
from ..arc_native_rank_receipt import DEEP_SCOPE
from .models import EvidenceSnippet
from .text_norm import normalize_for_match

_LOG = logging.getLogger("sraf.arc.rank_shadow")
MIN_SAMPLE_HITS = 16
MAX_ROWS = 128
MAX_CHARS = 131072
MAX_ROW_CHARS = 4096
MAX_WEIGHT_MILLI = 2000
TOP_K = 20


def observe_rank_shadow(evidence: list[EvidenceSnippet], groups: list[set[str]],
                        frequency: dict) -> dict:
    result = {
        "schema": "sraf_arc_rank_shadow_v1",
        "scope": "same_parser_slice_ordered_sample_strict_prefix",
        "status": "insufficient_sample",
        "strict_count": len(evidence),
    }
    deep = frequency.get("schema") == "sraf_arc_deep_rank_frequency_v1"
    native = deep or frequency.get("schema") == "sraf_arc_native_rank_frequency_v1"
    if native:
        result["scope"] = ("same_round_pit_native_df_strict_first_prefix" if deep
                           else "same_search_native_df_strict_first_prefix_not_pit")
        n = frequency.get("eligible_documents")
        df_key = "document_frequency"
        scope_valid = (frequency.get("scope") == (DEEP_SCOPE if deep else NATIVE_SCOPE)
                       and frequency.get("status") == "exact_es_query_counts"
                       and type(n) is int and MIN_SAMPLE_HITS <= n <= 2**63 - 1)
    else:
        n = frequency.get("eligible_hits")
        df_key = "sample_hit_frequency"
        scope_valid = (frequency.get("schema") == "sraf_arc_group_frequency_v1"
                       and frequency.get("scope") == "ordered_parser_slice_date_valid_sample_text_only"
                       and frequency.get("status") == "observed_sample"
                       and type(n) is int and MIN_SAMPLE_HITS <= n <= 128)
    rows = frequency.get("groups")
    if (not scope_valid
            or type(rows) is not list or type(groups) is not list
            or not 1 <= len(groups) <= (8 if native else 16) or len(rows) != len(groups)
            or any(type(g) is not set or not g for g in groups)
            or sum(map(len, groups)) > (32 if native else 64)):
        return result
    weights = []
    normalized = []
    for i, (row, group) in enumerate(zip(rows, groups), 1):
        if type(row) is not dict or type(row.get("group_ordinal")) is not int or row["group_ordinal"] != i:
            return result
        df = row.get(df_key)
        if type(df) is not int or not 0 <= df <= n:
            return result
        if any(type(t) is not str or not 0 < len(t) <= 160 for t in group):
            return result
        terms = {normalize_for_match(t) for t in group} - {""}
        if not terms:
            return result
        normalized.append(terms)
        # Zero observations are unknown for this biased sample, not a rarity bonus.
        weights.append(min(MAX_WEIGHT_MILLI, round(1000 * math.log((n + 1) / (df + 1)))) if df else 0)
    if len(evidence) <= TOP_K:
        result["status"] = "no_top_k_pressure"
        return result
    prefix = evidence[:MAX_ROWS]
    result["prefix_count"] = len(prefix)
    result["prefix_limited"] = len(prefix) < len(evidence)
    if not native:
        result["frequency_sample_limited"] = frequency.get("sample_limited") is True
    else:
        result["snapshot_consistency"] = "same_round_pit" if deep else "not_pit"
    # Reserve before normalizing any text. Skip oversized prefix, never silently
    # exclude a long row from comparison and treat it as a low ranking candidate.
    scope = current_arc_budget()
    if scope is None:
        result["status"] = "missing_shared_budget"
        return result
    budget, ordinal = scope
    if not budget.reserve(ordinal, ArcUnits(slices=1, rows=MAX_ROWS, chars=MAX_CHARS)):
        result["status"] = "shared_budget_exhausted"
        return result
    if (any(type(e) is not EvidenceSnippet or e.match_policy != "strict"
            or type(e.group_hits) is not int or not 1 <= e.group_hits <= len(groups)
            or type(e.source_hit_ordinal) is not int or e.source_hit_ordinal < 0
            or type(e.weak_evidence) is not bool
            or type(e.text) is not str or not 0 < len(e.text) <= MAX_ROW_CHARS
            for e in prefix)
            or sum(len(e.text) for e in prefix) > MAX_CHARS):
        result["status"] = "unsupported_prefix"
        return result
    priorities = []
    for i, e in enumerate(prefix):
        text = normalize_for_match(e.text)
        matched = [j for j, aliases in enumerate(normalized) if any(a in text for a in aliases)]
        # Existing weak/strong, total groups and text group count always
        # outrank rarity. A group counts once, not once per alias.
        priorities.append((int(not e.weak_evidence), e.group_hits, len(matched),
                           sum(weights[j] for j in matched), -i))
    order = sorted(range(len(prefix)), key=priorities.__getitem__, reverse=True)
    coverage_only = sorted(range(len(prefix)),
                           key=lambda i: (*priorities[i][:3], -i), reverse=True)
    baseline = set(range(TOP_K))
    selected = set(order[:TOP_K])
    result.update(
        status="observed_rank",
        top_k=TOP_K,
        top_k_replaced=len(baseline - selected),
        rarity_only_top_k_replaced=len(set(coverage_only[:TOP_K]) - selected),
        original_source_hits=len({prefix[i].source_hit_ordinal for i in baseline}),
        shadow_source_hits=len({prefix[i].source_hit_ordinal for i in selected}),
        original_strong=sum(not prefix[i].weak_evidence for i in baseline),
        shadow_strong=sum(not prefix[i].weak_evidence for i in selected),
    )
    return result


def log_rank_shadow(observation: dict) -> None:
    _LOG.warning("SRAF_ARC_RANK_SHADOW=%s",
                 json.dumps(observation, sort_keys=True, separators=(",", ":")))
