"""Count-only A7 observation of an already assessed deep retrieval round.

The canonical ledger and semantic coverage assessment have different meanings.
This helper never turns a candidate/row count into semantic relevance, a
date change, a relaxed filter, a new search, or a report readiness grant.
"""
from __future__ import annotations

import json
import logging

from agent.arc_mode import arc_shadow_enabled
from .contracts import RoundEvidenceSummary
from .coverage_evaluator import CoverageAssessment
from .evidence_ledger import RoundObservation

_LOG = logging.getLogger("sraf.arc.deep_strategy")


def build_deep_strategy_record(*, record, observation, assessment, keyword_policy):
    """Return only fixed keys, bounded counts and an advisory reason."""
    if (type(record) is not RoundEvidenceSummary
            or type(observation) is not RoundObservation
            or type(assessment) is not CoverageAssessment
            or keyword_policy not in ("flexible", "user_locked")
            or assessment.round_number != record.number
            or assessment.coverage_sufficient is not record.coverage_sufficient
            or assessment.request_wide_attested is not record.request_wide
            or assessment.missing_aspects != record.missing_aspects):
        return None
    if (not record.request_wide or record.result_incomplete
            or not observation.complete or assessment.result_incomplete):
        return {"schema": "sraf_arc_deep_strategy_shadow_v1",
                "round": record.number, "status": "unattested_or_incomplete",
                "advice": "none"}
    if (any(type(v) is not int or v < 0 for v in
            (assessment.verified_evidence, assessment.verified_sources,
             assessment.required_targets))
            or not len(record.missing_aspects) <= assessment.required_targets <= 8
            or assessment.verified_evidence > record.verified_evidence
            or assessment.verified_sources > record.known_sources
            or assessment.verified_sources > assessment.verified_evidence
            or len(observation.verified_evidence) > record.verified_evidence
            or record.newly_verified_evidence > len(observation.verified_evidence)):
        return None

    candidates = len(observation.candidate_sources)
    canonical = len(observation.verified_evidence)
    missing = len(record.missing_aspects)
    if record.coverage_sufficient:
        advice = "coverage_sufficient"
    elif keyword_policy == "user_locked":
        advice = "user_keywords_locked"
    elif not candidates:
        advice = "inspect_empty_candidate_scope"
    elif not canonical:
        advice = "inspect_canonical_filter_attrition"
    elif not assessment.verified_evidence:
        advice = "inspect_semantic_support_gap"
    elif not record.newly_verified_evidence:
        advice = "inspect_repeated_evidence"
    elif canonical >= 40 and missing:
        advice = "inspect_high_volume_coverage_gap"
    elif record.newly_verified_evidence < 3:
        advice = "inspect_low_incremental_gain"
    else:
        advice = "inspect_remaining_coverage_gap"

    return {
        "schema": "sraf_arc_deep_strategy_shadow_v1",
        "round": record.number, "status": "observed", "advice": advice,
        "candidate_sources": candidates,
        "canonical_evidence_this_round": canonical,
        "new_canonical_evidence": record.newly_verified_evidence,
        "cumulative_canonical_evidence": record.verified_evidence,
        "cumulative_canonical_sources": record.known_sources,
        "cumulative_semantically_supported_evidence": assessment.verified_evidence,
        "cumulative_semantically_supported_sources": assessment.verified_sources,
        "missing_targets": missing,
        "required_targets": assessment.required_targets,
    }


def observe_deep_strategy(**kwargs):
    """Optional local diagnostic; never changes the planner or its inputs."""
    if not arc_shadow_enabled("SRAF_ARC_STRATEGY"):
        return
    from agent.external_capabilities import requirement_acceptance_active

    try:
        if requirement_acceptance_active():
            return
        result = build_deep_strategy_record(**kwargs)
        if result is not None:
            _LOG.warning("SRAF_ARC_DEEP_STRATEGY=%s", json.dumps(
                result, sort_keys=True, separators=(",", ":")))
    except Exception:
        # The observation is neither an authorization nor an execution gate.
        return
