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
        check_frequency_scope: Callable[[ReportJob, QueryConstraints], bool] | None = None,
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
                or not callable(check_single_branch_coverage)
                or (check_frequency_scope is not None and not callable(check_frequency_scope))):
            raise WorkerScopeBindingError("invalid_job_scope_binding")
        self._job = job
        self._constraints = constraints
        self._coordinator = coordinator
        self._authorized_indexes = authorized_indexes
        self._check_index = check_index_access
        self._check_branches = check_single_branch_coverage
        self._check_frequency_scope = check_frequency_scope
        self._lock = Lock()
        self._binding_token = object()
        self._attested_rounds: set[int] = set()
        self._preflight_plans: dict[int, FrozenSingleQueryPlan] = {}
        # Retain the exact attested PIT plan for each paid semantic phase.
        self._semantic_plans: dict[int, FrozenSingleQueryPlan] = {}

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
            if not self._coordinator.authorize_owner_query_preflight(
                    plan.round_number, owner_token=self._binding_token,
                    execution_token=plan._execution_token):
                raise WorkerScopeBindingError("job_query_preflight_too_late")
            # This exact plan, not merely a matching same-round plan, was
            # explicitly authorized before any ES request was issued.
            self._preflight_plans[plan.round_number] = plan

    def admit_optional_frequency(self, plan: FrozenSingleQueryPlan, fence) -> bool:
        """Authorize/charge one optional count query, not a canonical page.

        A trusted adapter must call after taking the complete same-round
        fence results, while its PIT is still open. The independent frequency
        policy must explicitly allow the broader date/entity denominator;
        a canonical query permission alone is insufficient. No IO here.
        """
        from agent.es.arc_request_budget import ArcUnits, current_arc_budget
        from .es_page_fence import RoundESPageFence

        with self._lock:
            if (self._check_frequency_scope is None
                    or type(plan) is not FrozenSingleQueryPlan
                    or type(fence) is not RoundESPageFence
                    or plan._owner_binding_token is not self._binding_token
                    or plan.constraints is not self._constraints
                    or plan.coordinator is not self._coordinator
                    or plan.authorized_indexes != self._authorized_indexes
                    or plan.branch_code != "CANONICAL_MAIN"
                    or self._preflight_plans.get(plan.round_number) is not plan
                    or plan.round_number in self._attested_rounds
                    or fence._coordinator is not self._coordinator
                    or fence._constraints is not self._constraints
                    or fence._round != plan.round_number
                    or fence._execution_token is not plan._execution_token):
                return False
            # The completed/consumed fence is immutable for this purpose:
            # read its completion state under the fence lock.
            with fence._lock:
                if (not fence._consumed or not fence._complete
                        or fence._failed is not None or fence._pending is not None):
                    return False
                pages = fence._page_count
            scope = current_arc_budget()
            if scope is None or scope[1] != plan.round_number:
                return False
            budget, ordinal = scope
            try:
                self._check_live_policy()
                if self._check_frequency_scope(self._job, self._constraints) is not True:
                    return False
            except Exception:
                return False
            # Authorization callbacks may block; coordinator rechecks active
            # round, exact owner/execution identity and time on admission.
            progress = self._coordinator.safe_progress()
            if (progress["phase"] != "SEARCHING"
                    or progress["round"] != plan.round_number):
                return False
            if not budget.reserve(ordinal, ArcUnits(es_calls=1)):
                return False
            # Conservative nonrefund: ARC slot remains charged if main budget
            # subsequently denies this optional query. Never cancel the round.
            return self._coordinator._admit_optional_frequency(
                plan.round_number, owner_token=self._binding_token,
                execution_token=plan._execution_token, completed_pages=pages,
            )

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
                    or self._coordinator._owner_preflight_round != plan.round_number
                    or self._coordinator._owner_preflight_token is not self._binding_token
                    or self._coordinator._owner_preflight_execution_token is not plan._execution_token
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
            self._semantic_plans[plan.round_number] = plan
            del self._preflight_plans[plan.round_number]
            return True

    def recheck_semantic_authorization(self, plan: FrozenSingleQueryPlan) -> None:
        """Revalidate current owner/index/branch scope around each paid witness.

        This is NOT an independent provider or RBAC implementation. It uses
        the already injected, trusted policy callbacks; the persisted-job
        bridge re-reads real SQLite on every invocation. Reject unauthenticated
        or stale plans before issuing another semantic LLM call.
        """
        with self._lock:
            if (type(plan) is not FrozenSingleQueryPlan
                    or plan._owner_binding_token is not self._binding_token
                    or plan.constraints is not self._constraints
                    or plan.coordinator is not self._coordinator
                    or self._semantic_plans.get(plan.round_number) is not plan
                    or self._coordinator.safe_progress()["phase"] != "SEARCHING"
                    or self._coordinator.safe_progress()["round"] != plan.round_number):
                raise WorkerScopeBindingError("semantic_authorization_not_current")
            self._check_live_policy()

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
