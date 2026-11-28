"""Private, fixed-shape ARC advisory for an explicitly opted-in planner.

Not a query, authority, persisted receipt or coverage verdict. A hint binds
to the exact completed in-memory ledger object and original constraints;
it may be included in an already-admitted planner call, never trigger one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.arc_mode import arc_shadow_enabled
from .contracts import QueryConstraints, RoundEvidenceSummary
from .arc_deep_local_advisory import LocalGroupAdvisory, LocalPressureAdvisory

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
    missing_target_deficits: tuple[tuple[int, int], ...] = field(default=(), repr=False)
    local_advisory: LocalGroupAdvisory | None = field(default=None, repr=False)
    pressure_advisory: LocalPressureAdvisory | None = field(default=None, repr=False)

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
        deficits = self.missing_target_deficits
        if (type(deficits) is not tuple
                or (deficits and len(deficits) != len(latest.missing_aspects))
                or any(type(pair) is not tuple or len(pair) != 2
                       or type(pair[0]) is not int or type(pair[1]) is not int
                       or not 0 <= pair[0] <= 20 or not 0 <= pair[1] <= 10
                       or not (pair[0] or pair[1]) for pair in deficits)):
            return None
        result = {
            "scope": "advisory_only_no_constraint_changes",
            "round": latest.number, "advice": self.advice,
            "candidate_sources": self.candidate_sources,
            "canonical_evidence_this_round": self.canonical_evidence_this_round,
            "cumulative_semantically_supported_evidence": self.cumulative_semantically_supported_evidence,
            "cumulative_semantically_supported_sources": self.cumulative_semantically_supported_sources,
        }
        if deficits:
            # Zero-based positions in the existing latest missing_aspects
            # array, no extra labels or source identities.
            result["missing_aspect_deficits"] = [
                {"missing_aspect_position": position,
                 "additional_evidence_needed": evidence_gap,
                 "additional_distinct_sources_needed": source_gap,
                 "focus": ("independent_sources" if not evidence_gap else
                           "supporting_evidence" if not source_gap else
                           "supporting_evidence_and_independent_sources")}
                for position, (evidence_gap, source_gap) in enumerate(deficits)
            ]
        if type(self.local_advisory) is LocalGroupAdvisory:
            result.update(self.local_advisory.payload())
        if type(self.pressure_advisory) is LocalPressureAdvisory:
            result.update(self.pressure_advisory.payload(
                candidate_sources=self.candidate_sources,
                canonical_count=self.canonical_evidence_this_round))
        return result


def candidate_expansion_scope_enabled():
    """Separate private pilot still needs both existing shadow scopes."""
    return (arc_shadow_enabled("SRAF_ARC_BILINGUAL") and hint_scope_enabled())


def candidate_expansion_advised(hint, constraints, latest):
    # Empty *candidate* scope, not just rejected or semantically weak hits.
    # Counts never authorize looser canonical topic/date verification.
    if type(hint) is not DeepPlannerHint or not candidate_expansion_scope_enabled():
        return False
    payload = hint.payload_for(constraints, latest)
    return (payload is not None and payload["candidate_sources"] == 0
            and payload["advice"] == "inspect_empty_candidate_scope")


PRESSURE_QUERY_MODES = ("none", "focus", "expand")


def pressure_query_scope_enabled(mode):
    if type(mode) is not str or mode not in ("focus", "expand"):
        return False
    return (hint_scope_enabled() and arc_shadow_enabled(
        "SRAF_ARC_TIGHTEN" if mode == "focus" else "SRAF_ARC_RELAX"))


def pressure_query_mode(hint, constraints, latest):
    """Choose one bounded candidate strategy from the exact prior assessment."""
    if type(hint) is not DeepPlannerHint or not hint_scope_enabled():
        return "none"
    data = hint.payload_for(constraints, latest)
    if not data or not latest.missing_aspects:
        return "none"
    if ("local_tightening_counterfactual" in data
            and pressure_query_scope_enabled("focus")):
        return "focus"
    if ("local_relaxation_counterfactual" in data
            and pressure_query_scope_enabled("expand")):
        return "expand"
    return "none"
