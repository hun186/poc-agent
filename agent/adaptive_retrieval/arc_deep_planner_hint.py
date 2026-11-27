"""Private, fixed-shape ARC advisory for an explicitly opted-in planner.

Not a query, authority, persisted receipt or coverage verdict. A hint binds
to the exact completed in-memory ledger object and original constraints;
it may be included in an already-admitted planner call, never trigger one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.arc_mode import arc_shadow_enabled
from .contracts import QueryConstraints, RoundEvidenceSummary

_ADVICE = frozenset((
    "inspect_empty_candidate_scope", "inspect_canonical_filter_attrition",
    "inspect_semantic_support_gap", "inspect_repeated_evidence",
    "inspect_high_volume_coverage_gap", "inspect_low_incremental_gain",
    "inspect_remaining_coverage_gap",
))


def hint_scope_enabled():
    if not arc_shadow_enabled("SRAF_ARC_STRATEGY"):
        return False
    from agent.external_capabilities import requirement_acceptance_active
    return not requirement_acceptance_active()


@dataclass(frozen=True)
class DeepPlannerHint:
    _constraints: QueryConstraints = field(repr=False)
    _record: RoundEvidenceSummary = field(repr=False)
    advice: str
    candidate_sources: int
    canonical_evidence_this_round: int
    cumulative_semantically_supported_evidence: int
    cumulative_semantically_supported_sources: int

    def payload_for(self, constraints, latest):
        if (type(constraints) is not QueryConstraints
                or constraints is not self._constraints
                or type(latest) is not RoundEvidenceSummary
                or latest is not self._record
                or constraints.keyword_policy != "flexible"
                or not latest.request_wide or latest.result_incomplete
                or latest.coverage_sufficient
                or type(self.advice) is not str or self.advice not in _ADVICE):
            return None
        counts = (self.candidate_sources, self.canonical_evidence_this_round,
                  self.cumulative_semantically_supported_evidence,
                  self.cumulative_semantically_supported_sources)
        if any(type(n) is not int or n < 0 for n in counts):
            return None
        if (self.candidate_sources > 1000
                or not latest.newly_verified_evidence <= self.canonical_evidence_this_round <= min(4096, latest.verified_evidence)
                or self.cumulative_semantically_supported_evidence > latest.verified_evidence
                or self.cumulative_semantically_supported_sources > min(latest.known_sources, self.cumulative_semantically_supported_evidence)
                or (not self.candidate_sources and self.canonical_evidence_this_round)):
            return None
        # Recompute the fixed reason from the numeric inputs, rather than
        # trusting a free-form diagnosis or arbitrary model-generated enum.
        if not self.candidate_sources:
            expected = "inspect_empty_candidate_scope"
        elif not self.canonical_evidence_this_round:
            expected = "inspect_canonical_filter_attrition"
        elif not self.cumulative_semantically_supported_evidence:
            expected = "inspect_semantic_support_gap"
        elif not latest.newly_verified_evidence:
            expected = "inspect_repeated_evidence"
        elif self.canonical_evidence_this_round >= 40 and latest.missing_aspects:
            expected = "inspect_high_volume_coverage_gap"
        elif latest.newly_verified_evidence < 3:
            expected = "inspect_low_incremental_gain"
        else:
            expected = "inspect_remaining_coverage_gap"
        if self.advice != expected:
            return None
        return {
            "scope": "advisory_only_no_constraint_changes",
            "round": latest.number, "advice": self.advice,
            "candidate_sources": self.candidate_sources,
            "canonical_evidence_this_round": self.canonical_evidence_this_round,
            "cumulative_semantically_supported_evidence": self.cumulative_semantically_supported_evidence,
            "cumulative_semantically_supported_sources": self.cumulative_semantically_supported_sources,
        }
