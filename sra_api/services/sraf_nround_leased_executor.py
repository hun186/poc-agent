"""Isolated owner-bound N-round executor for a *previously claimed* Report Job.

This helper only binds the existing claimed job, real SQLite lease and
count-only coordinator checkpoints. It never creates/claims the main Report
Job, finalizes it, generates Word, or exposes a user API. A trusted future
Worker must provide real current owner-index and single-branch policies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from api.services.report_job_store import ReportJob, ReportJobStore
from api.services.sraf_nround_claimed_job_scope import PersistedClaimedNroundJobScope
from agent.adaptive_retrieval.contracts import QueryConstraints
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.coverage_evaluator import CoverageTarget, RequestWideCoverageEvaluator
from agent.adaptive_retrieval.evidence_ledger import PrivateCanonicalEvidence
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from agent.adaptive_retrieval.trusted_execution_loop import (
    TrustedNroundExecutionResult, run_trusted_nround,
)


class ClaimedNroundExecutorError(ValueError):
    """Fixed denial code only; never reveal job, owner, SQLite or ES details."""


@dataclass(frozen=True)
class ClaimedNroundExecution:
    """Private Evidence retained for a separately authorized future handoff."""

    result: TrustedNroundExecutionResult = field(repr=False)

    def safe_audit(self) -> dict[str, object]:
        return {
            "schema": "sraf_nround_claimed_execution_v1",
            "completed_rounds": len(self.result.rounds),
            "termination": self.result.progress["termination"],
            "report_job_claim_revalidated": True,
            "checkpoint_terminal_persisted": True,
            "report_job_completed": False,
            "word_generated": False,
            "report_generation_authorized": False,
            "live_acceptance": "NOT_TESTED",
        }


def execute_claimed_nround(
    *,
    report_store: ReportJobStore,
    checkpoint_store: NroundCheckpointStore,
    claimed_job: ReportJob,
    constraints: QueryConstraints,
    coordinator: AdaptiveRequestCoordinator,
    evaluator: RequestWideCoverageEvaluator,
    authorized_indexes: tuple[str, ...],
    check_owner_index: Callable[[ReportJob, str], bool],
    check_question_branches: Callable[
        [ReportJob, QueryConstraints, tuple[str, ...]], bool
    ],
    es_client: Any,
    semantic_assessor: Callable[[CoverageTarget, PrivateCanonicalEvidence], bool],
    query_for_snippet: str,
    max_rounds: int = 8,
    page_size: int = 50,
    max_pages: int = 20,
    request_timeout_seconds: int = 20,
    max_semantic_checks_per_round: int = 512,
) -> ClaimedNroundExecution:
    """Run a strictly isolated, lease-fenced retrieval (NOT a ReportJobWorker).

    Requires an already QUEUED NroundCheckpointStore row created by trusted
    job admission and the genuine ReportJobStore.claim_next() return value.
    Never calls sidecar.create() or unbound sidecar.claim()/record_progress().
    This module is not exposed to HTTP and does not enable N-round traffic.
    """
    lease: str | None = None
    try:
        if (type(report_store) is not ReportJobStore
                or type(checkpoint_store) is not NroundCheckpointStore
                or type(claimed_job) is not ReportJob
                or type(coordinator) is not AdaptiveRequestCoordinator
                or type(evaluator) is not RequestWideCoverageEvaluator
                or evaluator._constraints is not constraints
                or type(max_rounds) is not int or not 1 <= max_rounds <= 8
                or not callable(semantic_assessor)
                or type(query_for_snippet) is not str
                or not 0 < len(query_for_snippet) <= 2048):
            raise ClaimedNroundExecutorError("invalid_claimed_nround_context")

        scoped = PersistedClaimedNroundJobScope(
            store=report_store, claimed_job=claimed_job,
            constraints=constraints, coordinator=coordinator,
            authorized_indexes=authorized_indexes,
            check_owner_index=check_owner_index,
            check_question_branches=check_question_branches,
        )
        binding = scoped.make_binding()
        # True SQLite BEGIN IMMEDIATE CAS: main Job identity and sidecar lease
        # are checked in the SAME DB transaction, not a pair of read calls.
        lease = checkpoint_store.claim_for_running_report_job(
            report_store, claimed_job,
        )
        if lease is None:
            raise ClaimedNroundExecutorError("checkpoint_lease_not_claimed")

        def persist(snapshot: dict[str, object]) -> bool:
            return checkpoint_store.record_progress_for_running_report_job(
                report_store, claimed_job, lease, snapshot,
            ) is True

        result = run_trusted_nround(
            coordinator=coordinator, constraints=constraints,
            evaluator=evaluator, authorized_indexes=authorized_indexes,
            es_client=es_client, semantic_assessor=semantic_assessor,
            attest_whole_query_scope=None, job_scope_binding=binding,
            query_for_snippet=query_for_snippet,
            max_rounds=max_rounds, page_size=page_size, max_pages=max_pages,
            request_timeout_seconds=request_timeout_seconds,
            max_semantic_checks_per_round=max_semantic_checks_per_round,
            checkpoint_sink=persist,
        )
        public = checkpoint_store.get_public(claimed_job.job_id)
        if (type(public) is not dict
                or public.get("state") != "RETRIEVAL_STOPPED"
                or public.get("phase") != "TERMINAL"
                or public.get("termination") != result.progress["termination"]
                or public.get("completed_rounds") != len(result.rounds)
                or public.get("report_generation_authorized") is not False):
            raise ClaimedNroundExecutorError("terminal_checkpoint_unverified")
        # This is NOT an artifact or Word-generation authorization. The main
        # Job remains running; a future report/asset commit needs separate CAS.
        return ClaimedNroundExecution(result=result)
    except Exception:
        if lease is not None:
            try:
                # Only our own live lease may be failed. A terminal sidecar,
                # interruption or different Job must never be overwritten.
                checkpoint_store.fail_owned_lease(claimed_job.job_id, lease)
            except Exception:
                # No fake successful cleanup if SQLite itself is unavailable.
                # Startup interruption is a separate operator responsibility.
                pass
        if type(coordinator) is AdaptiveRequestCoordinator:
            coordinator.revoke_unpersisted_report_readiness()
        raise ClaimedNroundExecutorError("claimed_nround_execution_denied") from None
