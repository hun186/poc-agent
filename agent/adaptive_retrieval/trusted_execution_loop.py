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

import os
from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Callable

from .contracts import QueryConstraints
from .coordinator import AdaptiveRequestCoordinator
from .coverage_evaluator import CoverageTarget, RequestWideCoverageEvaluator
from .evidence_ledger import CanonicalReportEvidence, PrivateCanonicalEvidence
from .planner import BoundNextRoundPlan
from .private_semantic_binding import prepare_private_semantic_grant
from .worker_scope_binding import WorkerScopeBinding
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
    _report_rows: tuple[CanonicalReportEvidence, ...] = field(default=(), repr=False)

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
    ] | None,
    query_for_snippet: str,
    job_scope_binding: WorkerScopeBinding | None = None,
    max_rounds: int = 8,
    page_size: int = 50,
    max_pages: int = 20,
    request_timeout_seconds: int = 20,
    max_semantic_checks_per_round: int = 512,
    checkpoint_sink: Callable[[dict[str, object]], bool] | None = None,
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
            or (job_scope_binding is None and
                not callable(attest_whole_query_scope))
            or (job_scope_binding is not None and (
                type(job_scope_binding) is not WorkerScopeBinding
                or attest_whole_query_scope is not None
                or job_scope_binding._constraints is not constraints
                or job_scope_binding._coordinator is not coordinator
                or job_scope_binding._authorized_indexes != authorized_indexes))
            or type(query_for_snippet) is not str
            or not 0 < len(query_for_snippet) <= 2048
            or (checkpoint_sink is not None and
                not callable(checkpoint_sink))
            or type(max_rounds) is not int
            or not 1 <= max_rounds <= 8
            or coordinator.safe_progress()["phase"] != "CREATED"):
        raise TrustedNroundExecutionError("invalid_trusted_nround_context")

    completed: list[CompletedSingleQueryRound] = []
    report_rows: dict[tuple[str, str], CanonicalReportEvidence] = {}
    report_chars = 0
    next_plan: BoundNextRoundPlan | None = None
    frozen = None
    # Separate optional shadow accounting; original ES/planner admission,
    # authorization, and generation-reserved deadline remain authoritative.
    from .arc_deep_frequency_transport import deep_frequency_enabled
    from .arc_deep_rank_receipt import DeepRoundRankReceipt
    from .arc_deep_review import deep_review_enabled, observe_deep_review

    review_binding = (job_scope_binding if deep_review_enabled()
                      and job_scope_binding is not None
                      and job_scope_binding._check_review_egress is not None else None)

    frequency_binding = (job_scope_binding if deep_frequency_enabled()
                         and job_scope_binding is not None
                         and job_scope_binding._check_frequency_scope is not None else None)
    arc_budget = ArcRequestBudget() if (
        os.getenv("SRAF_ARC_GROUP_FREQUENCY") == "shadow" or frequency_binding is not None
        or review_binding is not None
    ) else None

    def _persist_checkpoint() -> None:
        # This only emits coordinator-created, count-only safe progress;
        # callback MUST atomically fence it against the actual persisted
        # Report Job and N-round lease, and MUST return literal True.
        if checkpoint_sink is None:
            return
        try:
            snapshot = deepcopy(coordinator.safe_progress())
            if (type(snapshot) is not dict
                    or snapshot.get("schema") !=
                       "sraf_nround_coordinator_progress_v1"
                    or checkpoint_sink(snapshot) is not True):
                raise TrustedNroundExecutionError("nround_checkpoint_write_denied")
        except Exception:
            # A completed round may have reached TERMINAL/SUFFICIENT before
            # the durable sink failed. Ordinary cancel() is a no-op once
            # terminal, so explicitly revoke that stale report readiness.
            coordinator.revoke_unpersisted_report_readiness()
            raise TrustedNroundExecutionError("nround_checkpoint_write_denied") from None

    try:
        if not coordinator.start():
            raise TrustedNroundExecutionError("first_round_not_admitted")
        _persist_checkpoint()
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
                _owner_binding_token=(
                    job_scope_binding._binding_token
                    if job_scope_binding is not None else None
                ),
            )
            # The scoped path verifies the actual claimed job's owner and
            # allowed-index policy BEFORE opening a PIT. Legacy callback
            # mode exists only for isolated compatibility tests.
            if job_scope_binding is not None:
                job_scope_binding.preflight(frozen)
            rank_receipts = []
            with bind_arc_budget((arc_budget, frozen.round_number) if arc_budget is not None else None):
                fetched = execute_single_frozen_query(
                    plan=frozen, client=es_client, page_size=page_size,
                    max_pages=max_pages,
                    request_timeout_seconds=request_timeout_seconds,
                    **({"frequency_binding": frequency_binding,
                        "frequency_receipts": rank_receipts} if frequency_binding is not None else {}),
                )
            if (fetched.request_wide_attested is not False
                    or fetched.query_plan_complete is not True):
                raise TrustedNroundExecutionError("untrusted_query_receipt")
            # Record charged ES operations before the more expensive
            # private semantic/LLM work; no raw hits enter the sink.
            _persist_checkpoint()
            # This is intentionally an EXTERNAL proof requirement. No
            # source-candidate count or PIT-page success alone can assert
            # whole-question scope completeness. Strictly boolean True.
            if job_scope_binding is not None:
                attested = job_scope_binding.attest(frozen, fetched)
            else:
                attested = attest_whole_query_scope(frozen, fetched)
            if attested is not True:
                raise TrustedNroundExecutionError("query_scope_not_attested")
            if (coordinator.safe_progress()["phase"] != "SEARCHING"
                    or coordinator.safe_progress()["round"] != frozen.round_number):
                raise TrustedNroundExecutionError("query_scope_changed")
            remaining = coordinator._budget.snapshot()
            if remaining.remaining_seconds <= remaining.generation_reserve_seconds:
                raise TrustedNroundExecutionError("retrieval_deadline_expired")

            deep_rank_frequency = None
            if len(rank_receipts) == 1 and type(rank_receipts[0]) is DeepRoundRankReceipt:
                deep_rank_frequency = rank_receipts[0].consume(
                    plan=frozen, binding=frequency_binding, fetched=fetched)
            rank_receipts.clear()
            # Same original immutable scope and canonical Event/Timeline date
            # validity. The grant cannot invent passage/source pairs; it only
            # accepts a separate trusted semantic assessor's boolean verdict.
            def guarded_semantic_assessor(
                target: CoverageTarget, evidence: PrivateCanonicalEvidence,
            ) -> bool:
                # Check BEFORE EVERY provider callback, not merely after
                # all witnesses: a cancelled/expired request must never
                # initiate more paid LLM calls for remaining passages.
                status = coordinator.safe_progress()
                budget = coordinator._budget.snapshot()
                if (status["phase"] != "SEARCHING"
                        or status["round"] != frozen.round_number
                        or budget.remaining_seconds <=
                           budget.generation_reserve_seconds):
                    raise TrustedNroundExecutionError(
                        "semantic_callback_not_admissible")
                if job_scope_binding is not None:
                    # The PIT attestation is not a lifetime owner/RBAC grant:
                    # revalidate actual persisted Job and policies immediately
                    # before each potentially paid semantic/LLM witness.
                    job_scope_binding.recheck_semantic_authorization(frozen)
                    # Policies may block (e.g. SQLite/central RBAC) while
                    # the request is cancelled or retrieval reserve expires.
                    # Never purchase the provider call on a stale pre-policy
                    # phase/deadline snapshot; this second preflight is vital.
                    status = coordinator.safe_progress()
                    budget = coordinator._budget.snapshot()
                    if (status["phase"] != "SEARCHING"
                            or status["round"] != frozen.round_number
                            or budget.remaining_seconds <=
                               budget.generation_reserve_seconds):
                        raise TrustedNroundExecutionError(
                            "semantic_authorization_expired")
                verdict = semantic_assessor(target, evidence)
                if job_scope_binding is not None:
                    # Revocation during a provider call cannot undo that IO,
                    # but must prevent the remaining witnesses and handoff.
                    job_scope_binding.recheck_semantic_authorization(frozen)
                # An in-flight provider call cannot be forcibly cancelled
                # here, but another call must not start after it expires
                # or the coordinator is cancelled.
                status = coordinator.safe_progress()
                budget = coordinator._budget.snapshot()
                if (status["phase"] != "SEARCHING"
                        or status["round"] != frozen.round_number
                        or budget.remaining_seconds <=
                           budget.generation_reserve_seconds):
                    raise TrustedNroundExecutionError(
                        "semantic_callback_expired")
                return verdict

            with bind_arc_budget((arc_budget, frozen.round_number) if arc_budget is not None else None):
                grant = prepare_private_semantic_grant(
                    constraints=constraints,
                    evaluator=evaluator,
                    es_hits=list(fetched.hits),
                    term_groups=[set(x) for x in coordinator._groups],
                    effective_terms=list(coordinator._effective),
                    query_for_snippet=query_for_snippet,
                    complete=True,
                    assessor=guarded_semantic_assessor,
                    max_semantic_checks=max_semantic_checks_per_round,
                    **({"deep_rank_frequency": deep_rank_frequency} if deep_rank_frequency is not None else {}),
                )
            try:
                if review_binding is not None:
                    with bind_arc_budget((arc_budget, frozen.round_number)):
                        observe_deep_review(plan=frozen, binding=review_binding,
                                            fetched=fetched, grant=grant)
            finally:
                if job_scope_binding is not None:
                    job_scope_binding.clear_optional_review_sources(frozen)
            if review_binding is not None:
                # Independent review-egress denial alone is optional, but
                # revocation of the underlying owner/index/branch policy
                # during the extra callback must still block main coverage.
                review_binding.recheck_semantic_authorization(frozen)
            remaining = coordinator._budget.snapshot()
            if remaining.remaining_seconds <= remaining.generation_reserve_seconds:
                raise TrustedNroundExecutionError("semantic_assessment_over_deadline")
            with bind_arc_budget((arc_budget, frozen.round_number) if arc_budget is not None else None):
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
            for row in grant._report_rows:
                previous = report_rows.get(row.pair)
                if previous is not None:
                    if previous.doc_id != row.doc_id:
                        raise TrustedNroundExecutionError("ambiguous_report_source")
                    continue
                report_chars += len(row.passage.text) + len(row.title) + len(row.subject)
                if len(report_rows) >= 4096 or report_chars > 2_000_000:
                    raise TrustedNroundExecutionError("report_evidence_capacity_exceeded")
                report_rows[row.pair] = row
            completed.append(fetched)
            _persist_checkpoint()
            progress = coordinator.safe_progress()
            if progress["phase"] == "TERMINAL":
                break
            if progress["phase"] != "ASSESSED":
                raise TrustedNroundExecutionError("unexpected_assessment_phase")
            # Don't purchase a planner slot or admit an unexecutable next
            # round once the narrower operator-level cap is reached.
            if len(completed) >= max_rounds:
                raise TrustedNroundExecutionError("operator_round_cap_reached")
            admission = coordinator.plan_next_round()
            # Persist either the new SEARCHING round or terminal planner
            # stop before starting any further PIT request.
            _persist_checkpoint()
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
            rounds=tuple(completed), progress=progress,
            _report_rows=tuple(report_rows.values()) if progress["termination"] == "SUFFICIENT" else ())
    except Exception:
        coordinator.revoke_unpersisted_report_readiness()
        coordinator.cancel()
        raise TrustedNroundExecutionError("trusted_nround_execution_failed") from None
    finally:
        if job_scope_binding is not None and frozen is not None:
            job_scope_binding.clear_optional_review_sources(frozen)
        if arc_budget is not None:
            arc_budget.seal()
