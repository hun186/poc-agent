"""A5 bounded overload diagnosis and tightening counterfactual.

No ES or LLM requests, no actual selection, no modification of Evidence.
Candidate document counts and strict passage counts describe different scopes.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging

from ..arc_request_budget import ArcUnits, current_arc_budget
from .cross_language_alias import alias_matches
from .models import EvidenceSnippet
from .question_anchor import derive_explicit_question_anchor

_LOG = logging.getLogger("sraf.arc.tighten_shadow")
MIN_CANDIDATE_TOTAL = 256
MIN_STRICT = 40
MAX_ROWS = 128
MAX_CHARS = 131072
MAX_ROW_CHARS = 4096
MIN_RETAINED = 20
MIN_SOURCES = 8


@dataclass(frozen=True)
class CandidatePressure:
    relation: str = "unknown"
    total: int | None = None
    returned: int = 0

    @classmethod
    def from_primary(cls, response):
        if type(response) is not dict:
            return cls()
        hits = response.get("hits")
        if type(hits) is not dict or type(hits.get("hits")) is not list:
            return cls()
        returned = len(hits["hits"])
        shards = response.get("_shards")
        if (response.get("timed_out") is not False
                or response.get("terminated_early", False) is not False
                or "_clusters" in response or type(shards) is not dict):
            return cls(returned=returned)
        t, s, f = (shards.get(k) for k in ("total", "successful", "failed"))
        if (any(type(x) is not int for x in (t, s, f))
                or t <= 0 or s != t or f != 0):
            return cls(returned=returned)
        total = hits.get("total")
        if type(total) is not dict or total.get("relation") not in ("eq", "gte"):
            return cls(returned=returned)
        value = total.get("value")
        if type(value) is not int or not returned <= value <= 2**63 - 1:
            return cls(returned=returned)
        return cls(total["relation"], value, returned)


def _rare_axis(observation, group_count, anchor_index, *, native=False):
    if type(observation) is not dict:
        return None
    if native:
        from ..arc_frequency_plan import SCOPE
        if (observation.get("schema") != "sraf_arc_native_rank_frequency_v1"
                or observation.get("scope") != SCOPE
                or observation.get("status") != "exact_es_query_counts"):
            return None
        n, key = observation.get("eligible_documents"), "document_frequency"
    else:
        if (observation.get("schema") != "sraf_arc_group_frequency_v1"
                or observation.get("scope") != "ordered_parser_slice_date_valid_sample_text_only"
                or observation.get("status") != "observed_sample"):
            return None
        n, key = observation.get("eligible_hits"), "sample_hit_frequency"
    if type(n) is not int or not 16 <= n <= (2**63 - 1 if native else 128):
        return None
    rows = observation.get("groups")
    if type(rows) is not list or len(rows) != group_count:
        return None
    eligible = []
    for i, row in enumerate(rows):
        if (type(row) is not dict or type(row.get("group_ordinal")) is not int
                or row["group_ordinal"] != i + 1):
            return None
        df = row.get(key)
        if type(df) is not int or not 0 <= df <= n:
            return None
        # Unseen is unknown for matching parity; ubiquitous is not selective.
        if i != anchor_index and 0 < df < n:
            eligible.append((df, i))
    return min(eligible)[1] if eligible else None


def observe_tightening(evidence, groups, *, original_question, pressure=None,
                       local_frequency=None, native_frequency=None):
    return _compare_tightening(evidence, groups, original_question=original_question,
                               pressure=pressure, local_frequency=local_frequency,
                               native_frequency=native_frequency)


def _compare_tightening(evidence, groups, *, original_question, pressure=None,
                        local_frequency=None, native_frequency=None,
                        _offline_selections=None):
    pressure = pressure if type(pressure) is CandidatePressure else CandidatePressure()
    total = pressure.total
    if type(total) is int and total >= MIN_CANDIDATE_TOTAL:
        candidate_status = "high_exact" if pressure.relation == "eq" else "high_lower_bound"
    elif pressure.relation == "eq":
        candidate_status = "below_threshold_exact"
    else:
        candidate_status = "unknown_or_lower_bound_below_threshold"
    result = {"schema": "sraf_arc_tighten_shadow_v1",
              "scope": "strict_parser_prefix_only",
              "candidate_status": candidate_status,
              "candidate_total_relation": pressure.relation,
              "candidate_total": total, "primary_returned": pressure.returned,
              "strict_count": len(evidence), "status": "strict_not_high"}
    # High ES count alone must not trigger tightening when strict Evidence is scarce.
    if len(evidence) < MIN_STRICT:
        return result
    if (type(groups) is not list or not 4 <= len(groups) <= 16
            or any(type(g) is not set or not g for g in groups)
            or sum(map(len, groups)) > 64
            or any(type(t) is not str or not 0 < len(t) <= 160 for g in groups for t in g)):
        result["status"] = "unsupported_groups"
        return result
    anchor = derive_explicit_question_anchor(original_question, groups)
    if anchor is None:
        result["status"] = "no_trusted_anchor"
        return result
    prefix = evidence[:MAX_ROWS]
    result["prefix_count"] = len(prefix)
    result["prefix_limited"] = len(prefix) < len(evidence)
    scope = current_arc_budget()
    if scope is None:
        result["status"] = "missing_shared_budget"
        return result
    budget, ordinal = scope
    if not budget.reserve(ordinal, ArcUnits(slices=1, rows=MAX_ROWS, chars=MAX_CHARS)):
        result["status"] = "shared_budget_exhausted"
        return result
    if (any(type(e) is not EvidenceSnippet or e.match_policy != "strict"
            or type(e.text) is not str or not 0 < len(e.text) <= MAX_ROW_CHARS
            or type(e.source_hit_ordinal) is not int or e.source_hit_ordinal < 0
            for e in prefix) or sum(len(e.text) for e in prefix) > MAX_CHARS):
        result["status"] = "unsupported_prefix"
        return result
    local_axis = _rare_axis(local_frequency, len(groups), anchor.axis_index)
    native_axis = _rare_axis(native_frequency, len(groups), anchor.axis_index, native=True)
    selections = {"all_text_axes": []}
    if local_axis is not None:
        selections["anchor_plus_local_discriminative_axis"] = []
    if native_axis is not None:
        selections["anchor_plus_native_discriminative_axis"] = []
    positions = {name: [] for name in selections} if type(_offline_selections) is dict and not _offline_selections else None
    for i, e in enumerate(prefix):
        if e.weak_evidence or not alias_matches(anchor.literal, e.text):
            continue
        matched = {i for i, g in enumerate(groups)
                   if any(alias_matches(t, e.text) for t in g)}
        # Explicit literal and original group must both match; a rarity
        # candidate never lowers the original strict 3-axis text threshold.
        if anchor.axis_index not in matched or len(matched) < 3:
            continue
        if len(matched) == len(groups):
            selections["all_text_axes"].append(e.source_hit_ordinal)
            if positions is not None:
                positions["all_text_axes"].append(i)
        if local_axis is not None and local_axis in matched:
            selections["anchor_plus_local_discriminative_axis"].append(e.source_hit_ordinal)
            if positions is not None:
                positions["anchor_plus_local_discriminative_axis"].append(i)
        if native_axis is not None and native_axis in matched:
            selections["anchor_plus_native_discriminative_axis"].append(e.source_hit_ordinal)
            if positions is not None:
                positions["anchor_plus_native_discriminative_axis"].append(i)
    result["status"] = "observed_tightening"
    result["strategies"] = [
        {"strategy": name, "retained_prefix_rows": len(ids),
         "retained_source_hits": len(set(ids)),
         "sample_floor_met": len(ids) >= MIN_RETAINED and len(set(ids)) >= MIN_SOURCES}
        for name, ids in selections.items()
    ]
    if positions is not None:
        _offline_selections.update(positions)
    # These are count-only counterfactuals, never execution recommendations.
    return result


def log_tightening(result):
    _LOG.warning("SRAF_ARC_TIGHTEN_SHADOW=%s",
                 json.dumps(result, sort_keys=True, separators=(",", ":")))
