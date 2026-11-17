"""Optional job-owner and query-scope gate for FUTURE SRAF N-round Workers.

No production API/ReportJobWorker integration; no DB or ES access here.
The trusted Worker MUST load an actual claimed ReportJob and provide
current per-index RBAC and a policy that verifies the question legitimately
fits the ONLY supported canonical query branch. Neither callback is inferred
from the job prompt/LLM output or a complete PIT page chain.

This gate is NOT a standalone security authority: an untrustworthy caller
could construct a fake job, supply permissive policies, or use the legacy
no-binding execution helper. Production integration must restrict that
path and recheck current store owner/status before query start.
"""
from __future__ import annotations

from threading import Lock
from typing import Callable

from api.services.report_job_store import ReportJob
from .contracts import QueryConstraints
from .coordinator import AdaptiveRequestCoordinator
from .round_query_execution import FrozenSingleQueryPlan, CompletedSingleQueryRound


class WorkerScopeBindingError(ValueError):
    """Fixed reason codes; never include owner, question or document text."""


class WorkerScopeBinding:
    """Private one-job immutable query manifest + per-round policy rechecks."""

    def __init__(
        self, *,
        job: ReportJob,
        constraints: QueryConstraints,
        coordinator: AdaptiveRequestCoordinator,
        authorized_indexes: tuple[str, ...],
        check_index_access: Callable[[ReportJob, str], bool],
        check_single_branch_coverage: Callable[
            [ReportJob, QueryConstraints, tuple[str, ...]], bool
        ],
    ) -> None:
        if (type(job) is not ReportJob
                or job.status != "running"
                or type(job.owner_kind) is not str or not job.owner_kind.strip()
                or type(job.owner_id) is not str or not job.owner_id.strip()
                or type(job.job_id) is not str or not job.job_id.strip()
                or type(job.session_id) is not str or not job.session_id.strip()
                or type(constraints) is not QueryConstraints
                or job.prompt != constraints.question
                or type(coordinator) is not AdaptiveRequestCoordinator
                or coordinator._constraints is not constraints
                or type(authorized_indexes) is not tuple
                or len(set(authorized_indexes)) != len(authorized_indexes)
                or any(type(index) is not str or not index.strip()
                       for index in authorized_indexes)
                or not set(constraints.allowed_indexes).issubset(
                    set(authorized_indexes))
                or not callable(check_index_access)
                or not callable(check_single_branch_coverage)):
            raise WorkerScopeBindingError("invalid_job_scope_binding")
        self._job = job
        self._constraints = constraints
        self._coordinator = coordinator
        self._authorized_indexes = authorized_indexes
        self._check_index = check_index_access
        self._check_branches = check_single_branch_coverage
        self._lock = Lock()
        self._binding_token = object()
        self._attested_rounds: set[int] = set()
        self._preflight_plans: dict[int, FrozenSingleQueryPlan] = {}

    def _check_live_policy(self) -> None:
        try:
            if (not all(self._check_index(self._job, index) is True
                        for index in self._constraints.allowed_indexes)
                    or self._check_branches(
                        self._job, self._constraints, ("CANONICAL_MAIN",)
                    ) is not True):
                raise WorkerScopeBindingError("job_scope_not_authorized")
        except Exception:
            raise WorkerScopeBindingError("job_scope_not_authorized") from None

    def preflight(self, plan: FrozenSingleQueryPlan) -> None:
        """Must run BEFORE PIT open, and again after ES completes."""
        with self._lock:
            if (type(plan) is not FrozenSingleQueryPlan
                    or plan.constraints is not self._constraints
                    or plan.coordinator is not self._coordinator
                    or plan.authorized_indexes != self._authorized_indexes
                    or plan.branch_code != "CANONICAL_MAIN"
                    or plan._owner_binding_token is not self._binding_token
                    or plan.round_number in self._attested_rounds
                    or plan.round_number in self._preflight_plans):
                raise WorkerScopeBindingError("wrong_job_query_manifest")
            self._check_live_policy()
            # This exact plan, not merely a matching same-round plan, was
            # explicitly authorized before any ES request was issued.
            self._preflight_plans[plan.round_number] = plan

    def attest(
        self, plan: FrozenSingleQueryPlan, receipt: CompletedSingleQueryRound,
    ) -> bool:
        """Single-use technical check; caller still owns semantic accuracy."""
        with self._lock:
            if (type(plan) is not FrozenSingleQueryPlan
                    or type(receipt) is not CompletedSingleQueryRound
                    or plan.constraints is not self._constraints
                    or plan.coordinator is not self._coordinator
                    or plan.authorized_indexes != self._authorized_indexes
                    or plan.branch_code != "CANONICAL_MAIN"
                    or plan._owner_binding_token is not self._binding_token
                    or plan.round_number != receipt.round_number
                    or self._preflight_plans.get(plan.round_number) is not plan
                    or receipt._execution_token is not plan._execution_token
                    or self._coordinator._single_query_claimed_round != plan.round_number
                    or self._coordinator._single_query_claim_token is not plan._execution_token
                    or self._coordinator._es_slots_this_round < 2
                    or self._coordinator.safe_progress()["phase"] != "SEARCHING"
                    or self._coordinator.safe_progress()["round"] != plan.round_number
                    or plan.round_number in self._attested_rounds
                    or receipt.query_plan_complete is not True
                    or receipt.request_wide_attested is not False
                    or type(receipt.pages_completed) is not int
                    or receipt.pages_completed < 1
                    or type(receipt.unique_sources) is not int
                    or receipt.unique_sources != len(receipt.hits)
                    or any(
                        type(hit) is not dict
                        or hit.get("_index") not in self._constraints.allowed_indexes
                        or type(hit.get("_id")) is not str
                        or type(hit.get("_source")) is not dict
                        for hit in receipt.hits
                    )):
                raise WorkerScopeBindingError("job_query_receipt_unverified")
            self._check_live_policy()
            self._attested_rounds.add(plan.round_number)
            del self._preflight_plans[plan.round_number]
            return True

    def safe_audit(self) -> dict[str, int | str | bool]:
        with self._lock:
            return {
                "schema": "sraf_nround_worker_scope_binding_v1",
                "bound_to_running_job": True,
                "owner_index_policy": "TRUSTED_CALLBACK_REQUIRED",
                "single_branch_policy": "TRUSTED_CALLBACK_REQUIRED",
                "branches_per_round": 1,
                "rounds_attested": len(self._attested_rounds),
                "production_worker": "NOT_INTEGRATED",
            }
