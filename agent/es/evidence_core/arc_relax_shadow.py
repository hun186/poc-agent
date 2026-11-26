"""A6 first-primary-slice low volume diagnostics; no actual relaxation.

Counts are from the existing strict parser pass, not corpus completeness.
Counterfactuals only consider already parsed, canonically eligible passages.
No model, ES calls, source refill, or modification of Evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging

from ..arc_request_budget import ArcUnits, current_arc_budget
from .arc_tighten_shadow import CandidatePressure
from .cross_language_alias import alias_matches, _collision_key
from .question_anchor import derive_explicit_question_anchor
from .snippet import build_evidence_snippet

_LOG = logging.getLogger("sraf.arc.relax_shadow")
TARGET_STRICT = 3
MAX_ADD = 2
MAX_HITS = 128
MAX_ROWS = 128
MAX_ROWS_PER_HIT = 8
MAX_CHARS = 131072
MAX_ROW_CHARS = 4096
_DATE_REASONS = frozenset({"date_unmatched", "date_unknown", "date_before",
                           "date_after", "year_unmatched"})


@dataclass
class StrictSliceCounts:
    inspected: int = 0
    canonical_eligible: int = 0
    date_rejected: int = 0
    other_rejected: int = 0
    topic_rejected: int = 0

    def reject(self, reason):
        if reason in _DATE_REASONS:
            self.date_rejected += 1
        else:
            self.other_rejected += 1


def _identity(e):
    return (e.source_hit_ordinal, e.block_index, e.text, tuple(e.event_ids))


def observe_low_volume(hits, strict, groups, *, counts, pressure,
                       original_question, date_from, date_to, allowed_years):
    return _compare_low_volume(
        hits, strict, groups, counts=counts, pressure=pressure,
        original_question=original_question, date_from=date_from,
        date_to=date_to, allowed_years=allowed_years,
    )


def _compare_low_volume(hits, strict, groups, *, counts, pressure,
                        original_question, date_from, date_to, allowed_years,
                        _offline_candidates=None):
    # The public observer remains aggregate-only. Offline replay may collect
    # the first hypothetical cap of distinct eligible identities in scan
    # order; this is a declared counterfactual, not production selection.
    result = {
        "schema": "sraf_arc_relax_shadow_v1",
        "scope": "first_primary_strict_parser_slice",
        "status": "unavailable",
    }
    if type(counts) is not StrictSliceCounts or type(pressure) is not CandidatePressure:
        return result
    if (counts.inspected != counts.canonical_eligible + counts.date_rejected + counts.other_rejected
            or counts.canonical_eligible != len(strict) + counts.topic_rejected):
        return result
    result.update(primary_returned=pressure.returned,
                  candidate_total_relation=pressure.relation,
                  candidate_total=pressure.total,
                  parsed_citations=counts.inspected,
                  canonical_eligible=counts.canonical_eligible,
                  date_rejected=counts.date_rejected,
                  other_rejected=counts.other_rejected,
                  topic_rejected=counts.topic_rejected,
                  strict_count=len(strict))
    if len(strict) >= TARGET_STRICT:
        result["status"] = "strict_not_low"
        return result
    if pressure.returned == 0:
        result["status"] = ("primary_exact_zero" if pressure.relation == "eq"
                            and pressure.total == 0 else "primary_empty_unconfirmed")
        return result
    if not counts.inspected:
        result["status"] = "no_parsed_citations"
        return result
    if not counts.canonical_eligible:
        result["status"] = ("all_parsed_date_rejected" if counts.date_rejected == counts.inspected
                            else "no_canonical_eligible")
        return result
    if not counts.topic_rejected:
        result["status"] = "few_eligible_no_topic_rejections"
        return result
    result["status"] = "topic_rejection_observed"
    # Only the 3->2 case; never turn a two-group query into one group.
    if (type(groups) is not list or not 3 <= len(groups) <= 16
            or any(type(g) is not set or not g for g in groups)
            or sum(map(len, groups)) > 64
            or any(type(t) is not str or not 0 < len(t) <= 160 for g in groups for t in g)):
        result["status"] = "unsupported_groups"
        return result
    anchor = derive_explicit_question_anchor(original_question, groups)
    if anchor is None:
        result["status"] = "no_trusted_anchor"
        return result
    # A normalized term shared by multiple axes is not independent evidence.
    owners = {}
    for i, group in enumerate(groups):
        for t in group:
            key = _collision_key(t)
            if not key or (key in owners and owners[key] != i):
                result["status"] = "ambiguous_groups"
                return result
            owners[key] = i
    scope = current_arc_budget()
    if scope is None:
        result["status"] = "missing_shared_budget"
        return result
    budget, ordinal = scope
    if not budget.reserve(ordinal, ArcUnits(slices=1, hits=MAX_HITS, rows=MAX_ROWS, chars=MAX_CHARS)):
        result["status"] = "shared_budget_exhausted"
        return result

    inspected = chars = eligible = 0
    limited = len(hits) > MAX_HITS
    strict_ids = {_identity(e) for e in strict}
    seen = set(strict_ids)
    source_hits = set()
    proposed = 0
    for hit in hits[:MAX_HITS]:
        if inspected >= MAX_ROWS or chars >= MAX_CHARS:
            limited = True
            break
        if len(hit.citations) > MAX_ROWS_PER_HIT:
            limited = True
        for citation in hit.citations[:MAX_ROWS_PER_HIT]:
            if inspected >= MAX_ROWS or chars >= MAX_CHARS:
                limited = True
                break
            inspected += 1
            text = citation.text
            if (type(text) is not str or not 0 < len(text) <= MAX_ROW_CHARS
                    or chars + len(text) > MAX_CHARS):
                limited = True
                continue
            chars += len(text)
            if not alias_matches(anchor.literal, text):
                continue
            matched = {i for i, g in enumerate(groups) if any(alias_matches(t, text) for t in g)}
            if len(matched) != 2 or anchor.axis_index not in matched:
                continue
            e = build_evidence_snippet(hit, citation, date_from=date_from,
                                       date_to=date_to, allowed_years=allowed_years)
            if e is None:
                continue
            eligible += 1
            key = _identity(e)
            if key in seen:
                continue
            seen.add(key)
            proposed += 1
            if (type(_offline_candidates) is list
                    and len(_offline_candidates) < min(MAX_ADD, TARGET_STRICT - len(strict))):
                _offline_candidates.append(key)
            source_hits.add(e.source_hit_ordinal)
    result.update(status="observed_relaxation", inspected_rows=inspected,
                  text_chars=chars, sample_limited=limited,
                  eligible_direct_two_axis=eligible, new_candidate_rows=proposed,
                  candidate_source_hits=len(source_hits),
                  hypothetical_add_cap=min(proposed, MAX_ADD, TARGET_STRICT - len(strict)))
    return result


def log_low_volume(result):
    _LOG.warning("SRAF_ARC_RELAX_SHADOW=%s",
                 json.dumps(result, sort_keys=True, separators=(",", ":")))
