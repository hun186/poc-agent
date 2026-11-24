"""Single explicit non-production entrypoint joining N-round Job safety gates.

This is NOT installed into the production ReportJobWorker, API, Scheduler,
OpenWebUI or Word/export routing. The future trusted Worker MUST call
ReportJobStore.claim_next() itself and explicitly register the corresponding
NroundCheckpointStore sidecar row before invoking this entrypoint.

This helper binds:
  - same-file real SQLite ReportJob and N-round checkpoint;
  - current claimed Job owner/status/original question revalidation;
  - per-owner index/whole-question single-query authorization;
  - atomic sidecar lease issuance and lease-scoped monotonic progress;
  - bounded ES PIT -> canonical Evidence -> semantic witness -> N-round Planner;
  - lease-scoped failure cleanup, never global interrupt.

The optional internal publication path produces a real owner-bound Job DOCX;
it is not wired to production dispatch and cannot infer actual policy authority
from caller-provided callbacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from pathlib import Path
from typing import Any, Callable

from api.services.report_job_store import ReportJob, ReportJobStore
from api.services.sraf_nround_claimed_job_scope import (
    PersistedClaimedNroundJobScope,
)
from agent.adaptive_retrieval.contracts import QueryConstraints
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.coverage_evaluator import (
    CoverageTarget, RequestWideCoverageEvaluator,
)
from agent.adaptive_retrieval.evidence_ledger import PrivateCanonicalEvidence
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from agent.adaptive_retrieval.trusted_execution_loop import (
    TrustedNroundExecutionResult, run_trusted_nround,
)


class ClaimedNroundJobExecutionError(ValueError):
    """Sanitized error; never expose Job, ES, LLM or SQLite details."""


@dataclass(frozen=True)
class ClaimedNroundRetrieval:
    """Private retrieved results; no external report/Word permission."""

    _private_result: TrustedNroundExecutionResult = field(repr=False)
    _checkpoint_revision: int = field(repr=False)
    _generate: Callable[[], dict[str, Any]] | None = field(default=None, repr=False)
    _publish: Callable[[Path], None] | None = field(default=None, repr=False)

    def generate_and_publish_word(self, reports_root: Path) -> None:
        """Trusted Worker-only, one-shot synthesis and canonical Job publication."""
        if self._publish is None:
            raise ClaimedNroundJobExecutionError("nround_word_not_admitted")
        self._publish(reports_root)

    def generate_report(self) -> dict[str, Any]:
        """Internal bound synthesis; no API/Worker switch or artifact grant."""
        if self._generate is None:
            raise ClaimedNroundJobExecutionError("nround_report_not_admitted")
        return self._generate()

    @property
    def private_result(self) -> TrustedNroundExecutionResult:
        """Accessible only inside the future trusted reporting Worker."""
        return self._private_result

    def safe_audit(self) -> dict[str, int | str | bool]:
        """Retrieval-handoff snapshot only, never current persisted Job status."""
        audit = self._private_result.safe_audit()
        return {
            "schema": "sraf_nround_claimed_job_runner_v1",
            "rounds_completed": int(audit["rounds_completed"]),
            "pages_completed": int(audit["pages_completed"]),
            "terminal_reason": str(audit["terminal_reason"]),
            "checkpoint_revision": self._checkpoint_revision,
            "report_job": "NOT_FINALIZED",
            "word_generated": False,
            "word_download_authorized": False,
            "live_acceptance": "NOT_TESTED",
        }


def execute_claimed_nround_job(
    *,
    report_store: ReportJobStore,
    checkpoint_store: NroundCheckpointStore,
    claimed_job: ReportJob,
    coordinator: AdaptiveRequestCoordinator,
    constraints: QueryConstraints,
    evaluator: RequestWideCoverageEvaluator,
    authorized_indexes: tuple[str, ...],
    es_client: Any,
    semantic_assessor: Callable[[CoverageTarget, PrivateCanonicalEvidence], bool],
    check_owner_index: Callable[[ReportJob, str], bool],
    check_question_branches: Callable[
        [ReportJob, QueryConstraints, tuple[str, ...]], bool
    ],
    query_for_snippet: str,
    max_rounds: int = 8,
    page_size: int = 50,
    max_pages: int = 20,
    request_timeout_seconds: int = 20,
    max_semantic_checks_per_round: int = 512,
) -> ClaimedNroundRetrieval:
    """Run an explicitly claimed and pre-registered N-round sidecar job.

    Callers are responsible for REAL principal/index RBAC, authorized
    original QueryConstraints, multi-branch coverage and semantic verifier.
    Never pass a model-supplied ReportJob or dummy always-True policies to
    a production Worker. No live activation is performed by this function.
    """
    lease: str | None = None
    try:
        if (type(report_store) is not ReportJobStore
                or type(checkpoint_store) is not NroundCheckpointStore
                or type(claimed_job) is not ReportJob
                or type(coordinator) is not AdaptiveRequestCoordinator
                or type(constraints) is not QueryConstraints
                or type(evaluator) is not RequestWideCoverageEvaluator
                or not callable(semantic_assessor)
                or not callable(check_owner_index)
                or not callable(check_question_branches)
                or checkpoint_store.db_path.resolve() !=
                   report_store.db_path.resolve()):
            raise ClaimedNroundJobExecutionError("invalid_claimed_job_context")

        scope = PersistedClaimedNroundJobScope(
            store=report_store,
            claimed_job=claimed_job,
            constraints=constraints,
            coordinator=coordinator,
            authorized_indexes=authorized_indexes,
            check_owner_index=check_owner_index,
            check_question_branches=check_question_branches,
        )
        binding = scope.make_binding()
        # Do NOT auto-register a sidecar: a future trusted scheduler must
        # pre-register N-round intent explicitly. No legacy/unbound claim.
        lease = checkpoint_store.claim_for_running_report_job(
            report_store, claimed_job,
        )
        if lease is None:
            raise ClaimedNroundJobExecutionError("nround_job_lease_not_admitted")

        def persist(progress: dict[str, object]) -> bool:
            assert lease is not None
            return checkpoint_store.record_progress_for_running_report_job(
                report_store, claimed_job, lease, progress,
            )

        result = run_trusted_nround(
            coordinator=coordinator,
            constraints=constraints,
            evaluator=evaluator,
            authorized_indexes=authorized_indexes,
            es_client=es_client,
            semantic_assessor=semantic_assessor,
            attest_whole_query_scope=None,
            query_for_snippet=query_for_snippet,
            job_scope_binding=binding,
            max_rounds=max_rounds,
            page_size=page_size,
            max_pages=max_pages,
            request_timeout_seconds=request_timeout_seconds,
            max_semantic_checks_per_round=max_semantic_checks_per_round,
            checkpoint_sink=persist,
        )
        # The receipt is ONLY evidence of isolated retrieval completion,
        # not permission to write a Word, to complete the source ReportJob,
        # or to expose a download route. Recheck the same persisted Job
        # before returning even this private result.
        scope._assert_live()
        public = checkpoint_store.get_public(claimed_job.job_id)
        if (type(public) is not dict
                or public.get("schema") != "sraf_nround_durable_fence_v1"
                or public.get("state") != "RETRIEVAL_STOPPED"
                or public.get("phase") != "TERMINAL"
                or public.get("round_number") !=
                   result.progress["round"]
                or public.get("completed_rounds") != len(result.rounds)
                or public.get("termination") !=
                   result.progress["termination"]
                or public.get("report_generation_authorized") is not False
                or public.get("checkpoint_resume_supported") is not False
                or type(public.get("revision")) is not int):
            raise ClaimedNroundJobExecutionError("unverified_nround_checkpoint")
        # Codex P2: successful PIT authorization is not a lifetime grant.
        # A policy can be revoked while the final semantic provider is busy.
        # Recheck both current owner/index and complete-question branch scope
        # at the actual private Evidence handoff boundary, after the terminal
        # SQLite read and before returning *any* private retrieval result.
        binding._check_live_policy()
        scope._assert_live()
        # The two separate observations above cannot establish a same-DB
        # point-in-time Job + terminal sidecar claim. For a SUFFICIENT result
        # also require the merged #471 atomic, exact-revision handoff fence.
        # This is a read-only retrieval receipt, NOT DOCX permission. Other
        # terminal reasons remain explicitly incomplete/non-Word receipts;
        # an independent policy must decide how to report partial Evidence.
        if result.progress["termination"] == "SUFFICIENT":
            if not checkpoint_store.verify_terminal_for_running_report_job(
                report_store, claimed_job,
                expected_revision=public["revision"],
                completed_rounds=len(result.rounds),
            ):
                raise ClaimedNroundJobExecutionError(
                    "unverified_atomic_nround_terminal")
        revision = public["revision"]
        completed_rounds = len(result.rounds)

        def verify_generation() -> None:
            if (result.progress["termination"] != "SUFFICIENT"
                    or result.progress["ready_for_external_report_generation"] is not True
                    or coordinator.safe_progress() != result.progress):
                raise ClaimedNroundJobExecutionError("nround_report_not_admitted")
            binding._check_live_policy()
            scope._assert_live()
            if not checkpoint_store.verify_terminal_for_running_report_job(
                report_store, claimed_job, expected_revision=revision,
                completed_rounds=completed_rounds,
            ):
                raise ClaimedNroundJobExecutionError("nround_report_not_admitted")

        def generate() -> dict[str, Any]:
            # This closure belongs to the original claimed Job, policy,
            # coordinator and exact terminal revision, never HTTP input.
            from agent import report_agent
            try:
                verify_generation()
                sources: dict[str, str] = {}
                snippets = []
                for row in result._report_rows:
                    if (not row.doc_id or not row.passage.text.strip()
                            or (row.doc_id in sources
                                and sources[row.doc_id] != row.pair[1])):
                        raise ClaimedNroundJobExecutionError("nround_report_source_unverified")
                    sources[row.doc_id] = row.pair[1]
                    snippets.append(row.report_snippet())
                if not snippets:
                    raise ClaimedNroundJobExecutionError("nround_report_no_evidence")

                def guarded_report_call(prompt: str, **kwargs) -> str:
                    if (type(prompt) is not str or len(prompt) > 200_000
                            or kwargs.get("stage") != "report"):
                        raise ClaimedNroundJobExecutionError("nround_report_input_limit")
                    verify_generation()
                    remaining = coordinator._budget.claim_report_generation(completed_rounds)
                    if remaining < 1:
                        raise ClaimedNroundJobExecutionError("nround_report_budget_denied")
                    kwargs["timeout"] = min(float(kwargs["timeout"]), remaining)
                    if kwargs["timeout"] <= 0:
                        raise ClaimedNroundJobExecutionError("nround_report_budget_denied")
                    answer = report_agent.call_llm(prompt, **kwargs)
                    verify_generation()
                    if (coordinator._budget.snapshot().remaining_seconds < 1
                            or type(answer) is not str or not answer.strip()):
                        raise ClaimedNroundJobExecutionError("nround_report_result_unverified")
                    return answer

                output = report_agent._generate_report_from_payload(
                    {"question": constraints.question, "question_raw": constraints.question,
                     "time_range": {"date_from": constraints.event_date.start,
                                    "date_to": constraints.event_date.end},
                     "evidence_snippets": snippets},
                    constraints.question, constraints.question, {}, perf_counter(),
                    nround_progress=result.progress, report_call=guarded_report_call,
                )
                verify_generation()
                if (not output.get("citations")
                        or not output.get("evidence_usage", {}).get("llm_input")):
                    raise ClaimedNroundJobExecutionError("nround_report_no_evidence")
                return output
            except Exception:
                raise ClaimedNroundJobExecutionError("nround_report_generation_failed") from None

        def publish(reports_root: Path) -> None:
            # Never accept externally supplied report text, bytes or Job ID.
            # The real synthesis closure consumes the same one-shot budget.
            from api.services.export_word_service import ExportWordService
            admitted = False
            try:
                if not isinstance(reports_root, Path) or not reports_root.is_dir():
                    raise ClaimedNroundJobExecutionError("nround_word_root_unverified")
                output = generate()
                verify_generation()
                admitted = checkpoint_store.begin_docx_export_for_terminal_job(
                    report_store, claimed_job, expected_revision=revision,
                    completed_rounds=completed_rounds,
                )
                if not admitted:
                    raise ClaimedNroundJobExecutionError("nround_word_not_admitted")
                scope.recheck_export_policy()
                content, _ = ExportWordService().build_docx_bytes(output, filename=claimed_job.filename)
                scope.recheck_export_policy()
                if (coordinator._budget.snapshot().remaining_seconds < 1
                        or coordinator.safe_progress() != result.progress):
                    raise ClaimedNroundJobExecutionError("nround_word_budget_denied")
                if not checkpoint_store.commit_docx_for_terminal_job(
                    report_store, claimed_job, expected_revision=revision,
                    completed_rounds=completed_rounds,
                    reports_root=reports_root, content=content,
                    recheck_policy=scope.recheck_export_policy,
                    deadline_valid=lambda: (
                        coordinator._budget.snapshot().remaining_seconds >= 1
                        and coordinator.safe_progress() == result.progress
                    ),
                ):
                    raise ClaimedNroundJobExecutionError("nround_word_commit_denied")
            except Exception:
                if admitted:
                    try:
                        checkpoint_store.fail_docx_export_for_terminal_job(
                            report_store, claimed_job, expected_revision=revision,
                            completed_rounds=completed_rounds,
                        )
                    except Exception:
                        pass  # never fail an unrelated or completed Job
                raise ClaimedNroundJobExecutionError("nround_word_publication_failed") from None

        return ClaimedNroundRetrieval(
            _private_result=result,
            _checkpoint_revision=revision,
            _generate=generate if result.progress["termination"] == "SUFFICIENT" else None,
            _publish=publish if result.progress["termination"] == "SUFFICIENT" else None,
        )
    except Exception:
        # Target ONLY this worker's active lease. Do not use global
        # interrupt_running(), which would break unrelated report jobs.
        if lease is not None:
            try:
                checkpoint_store.fail_owned_lease(claimed_job.job_id, lease)
            except Exception:
                pass  # both failure paths are already fail-closed
        if type(coordinator) is AdaptiveRequestCoordinator:
            coordinator.revoke_unpersisted_report_readiness()
        raise ClaimedNroundJobExecutionError(
            "claimed_nround_job_execution_failed") from None
