"""Read-through claimed ReportJob authorization bridge for *future* N-round Jobs.

This module does not modify existing ReportJobWorker, ReportJobStore, API,
SQLite schema, downloadable Word routes or environment variables.

A trusted worker supplies the exact ReportJob returned by claim_next() and
real owner-index / question-scope policies. Before and after every frozen PIT
query, WorkerScopeBinding calls these wrappers, which re-fetch the job from
the real ReportJobStore and verify that the original claim's immutable
identity remains in 'running'/'agent_execution'.

A store read does not itself prove that the caller legitimately claimed the
job. A production Worker must source the claim from claim_next() rather
than from external request data; policies must consult actual server-side
authz, not LLM output or arbitrary 'True' callbacks.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

from api.services.report_job_store import ReportJob, ReportJobStore
from agent.adaptive_retrieval.contracts import QueryConstraints
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.worker_scope_binding import WorkerScopeBinding


class PersistedNroundJobScopeError(ValueError):
    """Sanitized failure only, no prompt, owner, index or sqlite data."""


_IMMUTABLE_FIELDS = (
    "job_id", "owner_kind", "owner_id", "session_id", "prompt",
    "model", "request_hash", "idempotency_key", "filename", "created_at",
    "started_at", "options", "metadata",
)


def _identity(job: ReportJob) -> tuple:
    return tuple(deepcopy(getattr(job, name)) for name in _IMMUTABLE_FIELDS)


class PersistedClaimedNroundJobScope:
    """Revalidate an existing claimed job against persisted state at each gate."""

    def __init__(
        self, *,
        store: ReportJobStore,
        claimed_job: ReportJob,
        constraints: QueryConstraints,
        coordinator: AdaptiveRequestCoordinator,
        authorized_indexes: tuple[str, ...],
        check_owner_index: Callable[[ReportJob, str], bool],
        check_question_branches: Callable[
            [ReportJob, QueryConstraints, tuple[str, ...]], bool
        ],
    ) -> None:
        if (type(store) is not ReportJobStore
                or type(claimed_job) is not ReportJob
                or type(constraints) is not QueryConstraints
                or type(coordinator) is not AdaptiveRequestCoordinator
                or coordinator._constraints is not constraints
                or type(authorized_indexes) is not tuple
                or not authorized_indexes
                or len(set(authorized_indexes)) != len(authorized_indexes)
                or any(type(index) is not str or not index.strip()
                       for index in authorized_indexes)
                or not set(constraints.allowed_indexes).issubset(
                    set(authorized_indexes))
                or not callable(check_owner_index)
                or not callable(check_question_branches)):
            raise PersistedNroundJobScopeError("invalid_persisted_job_scope")
        self._store = store
        self._identity = _identity(claimed_job)
        self._job_id = claimed_job.job_id
        self._question = constraints
        self._coordinator = coordinator
        self._authorized_indexes = authorized_indexes
        self._check_owner_index = check_owner_index
        self._check_question_branches = check_question_branches
        self._assert_live()

    def _assert_live(self, *, expected_phase: str = "agent_execution") -> ReportJob:
        try:
            row = self._store.get(self._job_id)
            if (type(row) is not ReportJob
                    or row.status != "running"
                    or row.phase != expected_phase
                    or type(row.started_at) is not str
                    or not row.started_at
                    or type(row.owner_kind) is not str
                    or not row.owner_kind.strip()
                    or type(row.owner_id) is not str
                    or not row.owner_id.strip()
                    or type(row.session_id) is not str
                    or not row.session_id.strip()
                    or row.prompt != self._question.question
                    or _identity(row) != self._identity):
                raise PersistedNroundJobScopeError("claimed_job_not_current")
            return row
        except Exception:
            raise PersistedNroundJobScopeError("claimed_job_not_current") from None

    def _index_policy(self, _untrusted_snapshot: ReportJob, index: str) -> bool:
        try:
            live = self._assert_live()
            # The caller policy receives only the freshly loaded DB row,
            # never a possibly stale in-memory claim object.
            return self._check_owner_index(live, index) is True
        except Exception:
            raise PersistedNroundJobScopeError("owner_index_revalidation_failed") from None

    def _branch_policy(
        self, _untrusted_snapshot: ReportJob, constraints: QueryConstraints,
        branches: tuple[str, ...],
    ) -> bool:
        try:
            live = self._assert_live()
            if constraints is not self._question or branches != ("CANONICAL_MAIN",):
                return False
            return self._check_question_branches(live, constraints, branches) is True
        except Exception:
            raise PersistedNroundJobScopeError("question_scope_revalidation_failed") from None

    def recheck_export_policy(self) -> None:
        """Fresh original owner/index/branch policy after export admission."""
        try:
            for index in self._question.allowed_indexes:
                if self._check_owner_index(
                    self._assert_live(expected_phase="docx_export"), index,
                ) is not True:
                    raise PersistedNroundJobScopeError("export_policy_denied")
            if self._check_question_branches(
                self._assert_live(expected_phase="docx_export"),
                self._question, ("CANONICAL_MAIN",),
            ) is not True:
                raise PersistedNroundJobScopeError("export_policy_denied")
            self._assert_live(expected_phase="docx_export")
        except Exception:
            raise PersistedNroundJobScopeError("export_policy_denied") from None

    def make_binding(self) -> WorkerScopeBinding:
        """Only a scoped, non-production binding; no ES/LLM/Word calls."""
        live = self._assert_live()
        return WorkerScopeBinding(
            job=live,
            constraints=self._question,
            coordinator=self._coordinator,
            authorized_indexes=self._authorized_indexes,
            check_index_access=self._index_policy,
            check_single_branch_coverage=self._branch_policy,
        )

    def safe_audit(self) -> dict[str, str | bool]:
        return {
            "schema": "sraf_nround_persisted_claimed_job_scope_v1",
            "job_claim_recheck": "REQUIRED_BEFORE_AND_AFTER_PIT",
            "authorization_source": "INJECTED_TRUSTED_POLICIES",
            "persistent_job_store": True,
            "report_worker": "NOT_INTEGRATED",
            "nround_api": "NOT_ENABLED",
        }
