"""Isolated trusted N-round execution loop: real ES transport + callback contracts.

This is a synchronous worker-only execution helper, NOT yet wired into the
production ReportJobWorker, API, OpenWebUI, or Word generation. It executes
the strictly frozen one-branch PIT plan from round_query_execution (PR #460),
then binds only canonical source/date/topic-verified Evidence to a separately
injected trusted semantic assessor (PR #461) and passes the witness grants to
the request-wide coverage-aware coordinator (#457/#458).

The caller MUST supply real authorization and a trustworthy full-query-scope
attestor before a round can be classified as complete. A bogus callback can
still lie: this module cannot certify tenant RBAC, missing intended branches,
true semantic grounding, model quality, or report readiness by itself.
No production switch is provided.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import QueryConstraints
from .coordinator import AdaptiveRequestCoordinator
from .coverage_evaluator import CoverageTarget, RequestWideCoverageEvaluator
from .evidence_ledger import PrivateCanonicalEvidence
from .planner import BoundNextRoundPlan
from .private_semantic_binding import prepare_private_semantic_grant
from .round_query_execution import (
    CompletedSingleQueryRound, FrozenSingleQueryPlan,
    execute_single_frozen_query,
)


class TrustedNroundExecutionError(ValueError):
    """Only fixed error codes, never private ES/LLM/citation text."""


@dataclass(frozen=True)
class TrustedNroundExecutionResult:
    """Private rounds are retained for a FUTURE separately approved report."""

    rounds: tuple[CompletedSingleQueryRound, ...] = field(repr=False)
    progress: dict[str, object] = field(repr=False)

    def safe_audit(self) -> dict[str, object]:
        return {
            "schema": "sraf_nround_trusted_execution_v1",
            "rounds_completed": len(self.rounds),
            "terminal_reason": self.progress.get("termination", "UNKNOWN"),
            "es_calls_admitted_this_round": self.progress.get(
                "es_calls_admitted_this_round", 0),
            "pages_completed": sum(item.pages_completed for item in self.rounds),
            "technical_round_chains_complete": all(
                item.query_plan_complete for item in self.rounds),
            "report_job": "NOT_INTEGRATED",
            "word_generated": False,
            "live_acceptance": "NOT_TESTED",
        }


def run_trusted_nround(
    *,
    coordinator: AdaptiveRequestCoordinator,
    constraints: QueryConstraints,
    evaluator: RequestWideCoverageEvaluator,
    authorized_indexes: tuple[str, ...],
    es_client: Any,
    semantic_assessor: Callable[[CoverageTarget, PrivateCanonicalEvidence], bool],
    attest_whole_query_scope: Callable[
        [FrozenSingleQueryPlan, CompletedSingleQueryRound], bool,
    ],
    query_for_snippet: str,
    max_rounds: int = 8,
    page_size: int = 50,
    max_pages: int = 20,
    request_timeout_seconds: int = 20,
    max_semantic_checks_per_round: int = 512,
) -> TrustedNroundExecutionResult:
    """Execute bounded real client calls but NEVER claim independent RBAC.

    An outer trusted Worker must first bind tenant authorization, permitted
    indexes, immutable date constraints and *all* intended ES query branches.
    This first phase supports only one canonical branch per round. The
    attestor must reject a question requiring other branches, and must
    independently verify the actual submitted plan against that requirement.
    Its True is a caller's assertion, not cryptographic proof.
    """
    if (type(coordinator) is not AdaptiveRequestCoordinator
            or type(constraints) is not QueryConstraints
            or type(evaluator) is not RequestWideCoverageEvaluator
            or coordinator._constraints is not constraints
            or evaluator._constraints is not constraints
            or not callable(semantic_assessor)
            or not callable(attest_whole_query_scope)
            or type(query_for_snippet) is not str
            or not 0 < len(query_for_snippet) <= 2048
            or type(max_rounds) is not int
            or not 1 <= max_rounds <= 8
            or coordinator.safe_progress()["phase"] != "CREATED"):
        raise TrustedNroundExecutionError("invalid_trusted_nround_context")

    completed: list[CompletedSingleQueryRound] = []
    next_plan: BoundNextRoundPlan | None = None
    try:
        if not coordinator.start():
            raise TrustedNroundExecutionError("first_round_not_admitted")
        for _ in range(max_rounds):
            progress = coordinator.safe_progress()
            if progress["phase"] != "SEARCHING":
                raise TrustedNroundExecutionError("unexpected_round_phase")
            frozen = FrozenSingleQueryPlan(
                coordinator=coordinator,
                constraints=constraints,
                authorized_indexes=authorized_indexes,
                round_number=progress["round"],
                next_round_plan=next_plan,
            )
            fetched = execute_single_frozen_query(
                plan=frozen, client=es_client, page_size=page_size,
                max_pages=max_pages,
                request_timeout_seconds=request_timeout_seconds,
            )
            if (fetched.request_wide_attested is not False
                    or fetched.query_plan_complete is not True):
                raise TrustedNroundExecutionError("untrusted_query_receipt")
            # This is intentionally an EXTERNAL proof requirement. No
            # source-candidate count or PIT-page success alone can assert
            # whole-question scope completeness. Strictly boolean True.
            if attest_whole_query_scope(frozen, fetched) is not True:
                raise TrustedNroundExecutionError("query_scope_not_attested")
            if (coordinator.safe_progress()["phase"] != "SEARCHING"
                    or coordinator.safe_progress()["round"] != frozen.round_number):
                raise TrustedNroundExecutionError("query_scope_changed")
            remaining = coordinator._budget.snapshot()
            if remaining.remaining_seconds <= remaining.generation_reserve_seconds:
                raise TrustedNroundExecutionError("retrieval_deadline_expired")

            # Same original immutable scope and canonical Event/Timeline date
            # validity. The grant cannot invent passage/source pairs; it only
            # accepts a separate trusted semantic assessor's boolean verdict.
            grant = prepare_private_semantic_grant(
                constraints=constraints,
                evaluator=evaluator,
                es_hits=list(fetched.hits),
                term_groups=[set(x) for x in coordinator._groups],
                effective_terms=list(coordinator._effective),
                query_for_snippet=query_for_snippet,
                complete=True,
                assessor=semantic_assessor,
                max_semantic_checks=max_semantic_checks_per_round,
            )
            remaining = coordinator._budget.snapshot()
            if remaining.remaining_seconds <= remaining.generation_reserve_seconds:
                raise TrustedNroundExecutionError("semantic_assessment_over_deadline")
            coordinator.complete_round(
                list(fetched.hits),
                query_for_snippet=query_for_snippet,
                complete=True,
                # The trusted attestor explicitly approved this exact
                # active frozen query after full PIT page-chain completion.
                request_wide_attested=True,
                coverage_evaluator=evaluator,
                coverage_witnesses=grant.witnesses,
                semantic_verifier=grant.semantic_verifier,
            )
            completed.append(fetched)
            progress = coordinator.safe_progress()
            if progress["phase"] == "TERMINAL":
                break
            if progress["phase"] != "ASSESSED":
                raise TrustedNroundExecutionError("unexpected_assessment_phase")
            admission = coordinator.plan_next_round()
            if not admission.approved:
                break
            if (admission.plan is None
                    or admission.plan is not coordinator._approved_plan):
                raise TrustedNroundExecutionError("untrusted_planner_admission")
            next_plan = admission.plan
        else:
            # The caller's own cap must not turn a still-pending next round
            # into a successful partial multi-round result.
            if coordinator.safe_progress()["phase"] != "TERMINAL":
                raise TrustedNroundExecutionError("operator_round_cap_reached")

        progress = coordinator.safe_progress()
        if (progress["phase"] != "TERMINAL"
                or progress["completed_rounds"] != len(completed)
                or any(not r.query_plan_complete for r in completed)):
            raise TrustedNroundExecutionError("round_execution_unverified")
        return TrustedNroundExecutionResult(
            rounds=tuple(completed), progress=progress)
    except Exception:
        coordinator.cancel()
        raise TrustedNroundExecutionError("trusted_nround_execution_failed") from None
