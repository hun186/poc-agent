"""Strict, explicit one-branch N-round ES query-plan execution boundary.

The existing PIT adapter attests one complete page chain; it does not know
whether the *caller* silently omitted an intended query branch. For now,
SRAF's only supported plan here is ONE frozen canonical main query for the
active round. The plan is built from the original QueryConstraints and the
exact coordinator-approved next-round strategy; there are no caller-supplied
ES DSL or variable branch lists to forget or silently skip.

No import-time IO, production API wiring, ReportJob, LLM or Word. A trusted
caller must independently authorize tenant/index and prove that this SINGLE
canonical branch represents the intended retrieval scope. This helper
proves only that the supported technical plan executed successfully:
it NEVER reports request_wide_attested or Evidence sufficiency. Future
multi-branch scopes must not be modeled as this single-branch plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import QueryConstraints
from .coordinator import AdaptiveRequestCoordinator
from .es_pit_adapter import (
    FencedESRound, LiveRoundESFailure, search_fenced_es_round,
)
from .planner import BoundNextRoundPlan


class RoundQueryPlanError(ValueError):
    """Fixed reason, without private ES, PIT, question or source text."""


@dataclass(frozen=True)
class FrozenSingleQueryPlan:
    """Private plan authority for exactly one canonical SRAF search query."""

    coordinator: AdaptiveRequestCoordinator
    constraints: QueryConstraints
    authorized_indexes: tuple[str, ...]
    round_number: int
    next_round_plan: BoundNextRoundPlan | None
    # Fixed internal branch name, NOT a user/LLM supplied branch list.
    branch_code: str = "CANONICAL_MAIN"
    # Opaque per-plan identity; never include it in progress, logs or audit.
    _execution_token: object = field(
        default_factory=object, compare=False, repr=False,
    )
    # The future Worker-bound path stamps its exact owner-scope binding
    # onto the frozen plan; the unbound isolated ES path stays None.
    _owner_binding_token: object | None = field(
        default=None, compare=False, repr=False,
    )

    def __post_init__(self) -> None:
        if (type(self.coordinator) is not AdaptiveRequestCoordinator
                or type(self.constraints) is not QueryConstraints
                or self.coordinator._constraints is not self.constraints
                or type(self.authorized_indexes) is not tuple
                or any(type(v) is not str for v in self.authorized_indexes)
                or not set(self.constraints.allowed_indexes).issubset(
                    set(self.authorized_indexes))
                or self.branch_code != "CANONICAL_MAIN"
                or type(self._execution_token) is not object
                or type(self.round_number) is not int
                or not 1 <= self.round_number <= 8):
            raise RoundQueryPlanError("untrusted_frozen_query_context")
        progress = self.coordinator.safe_progress()
        if (progress["phase"] != "SEARCHING"
                or progress["round"] != self.round_number):
            raise RoundQueryPlanError("inactive_query_round")
        if self.round_number == 1:
            if self.next_round_plan is not None:
                raise RoundQueryPlanError("unexpected_next_round_plan")
        elif (type(self.next_round_plan) is not BoundNextRoundPlan
              or self.next_round_plan is not self.coordinator._approved_plan
              or self.next_round_plan.constraints is not self.constraints
              or self.next_round_plan.round_number != self.round_number):
            raise RoundQueryPlanError("unapproved_next_round_plan")


@dataclass(frozen=True)
class CompletedSingleQueryRound:
    """Private PIT results; caller still needs canonical + semantic assessment."""

    hits: tuple[dict[str, Any], ...]
    round_number: int
    pages_completed: int
    unique_sources: int
    # Only the one explicitly supported search query was executed completely.
    query_plan_complete: bool = True
    # Execution-issued, unlogged receipt identity. The technical proof
    # may be accepted only by the SAME FrozenSingleQueryPlan and coordinator
    # that successfully claimed and executed the PIT chain.
    _execution_token: object = field(
        default_factory=object, compare=False, repr=False,
    )

    @property
    def request_wide_attested(self) -> bool:
        # Neither tenant RBAC, semantic coverage nor undocumented query
        # branches are attested by this isolated technical query receipt.
        return False

    def safe_audit(self) -> dict[str, int | str | bool]:
        return {
            "schema": "sraf_nround_single_query_plan_v1",
            "round": self.round_number,
            "expected_branches": 1,
            "completed_branches": 1,
            "pages_completed": self.pages_completed,
            "sources_accepted": self.unique_sources,
            "technical_query_plan_complete": self.query_plan_complete,
            "request_wide_attested": False,
            "semantic_coverage": "NOT_ASSESSED",
            "report_job": "NOT_INTEGRATED",
        }


def execute_single_frozen_query(
    *,
    plan: FrozenSingleQueryPlan,
    client: Any,
    page_size: int = 50,
    max_pages: int = 20,
    request_timeout_seconds: int = 20,
) -> CompletedSingleQueryRound:
    """Consume the manifest exactly once via the *real* strict ES PIT adapter.

    No partial hit list returned on error. The unchanged PIT adapter already
    guards per-IO ES budget, strict index/date scope, PIT cleanup, pagination,
    shard completeness and immutable strategy identity.
    """
    if type(plan) is not FrozenSingleQueryPlan:
        raise RoundQueryPlanError("invalid_frozen_query_plan")
    coordinator = plan.coordinator
    progress = coordinator.safe_progress()
    if (progress["phase"] != "SEARCHING"
            or progress["round"] != plan.round_number
            or coordinator._constraints is not plan.constraints
            or (plan.round_number > 1
                and coordinator._approved_plan is not plan.next_round_plan)):
        raise RoundQueryPlanError("stale_frozen_query_plan")

    if not coordinator.claim_single_query_execution(
            plan.round_number, execution_token=plan._execution_token):
        raise RoundQueryPlanError("query_plan_already_claimed_or_mixed")

    try:
        result = search_fenced_es_round(
            coordinator=coordinator,
            constraints=plan.constraints,
            authorized_indexes=plan.authorized_indexes,
            client=client,
            plan=plan.next_round_plan,
            page_size=page_size,
            max_pages=max_pages,
            request_timeout_seconds=request_timeout_seconds,
            execution_token=plan._execution_token,
        )
    except LiveRoundESFailure:
        # Never return partial evidence, nor allow an assessor to declare
        # completeness after a failed scheduled branch.
        coordinator.cancel()
        raise RoundQueryPlanError("frozen_query_execution_failed") from None
    except Exception:
        coordinator.cancel()
        raise RoundQueryPlanError("frozen_query_execution_failed") from None

    try:
        audit = result.audit
        if (type(result) is not FencedESRound
                or type(audit) is not dict
                or audit.get("schema") != "sraf_nround_es_page_fence_v1"
                or audit.get("round") != plan.round_number
                or audit.get("complete_page_chain") is not True
                or audit.get("failed") != "NONE"
                or audit.get("request_wide_attested") is not False
                or type(audit.get("pages_accepted")) is not int
                or audit["pages_accepted"] < 1
                or type(audit.get("sources_accepted")) is not int
                or audit["sources_accepted"] != len(result.hits)
                or type(result.hits) is not list
                or any(type(h) is not dict
                       or h.get("_index") not in plan.constraints.allowed_indexes
                       for h in result.hits)):
            raise ValueError("invalid_pit_receipt")
        if (coordinator.safe_progress()["phase"] != "SEARCHING"
                or coordinator.safe_progress()["round"] != plan.round_number):
            raise ValueError("round_changed_during_query")
        return CompletedSingleQueryRound(
            hits=tuple(result.hits),
            round_number=plan.round_number,
            pages_completed=audit["pages_accepted"],
            unique_sources=audit["sources_accepted"],
            _execution_token=plan._execution_token,
        )
    except Exception:
        coordinator.cancel()
        raise RoundQueryPlanError("frozen_query_receipt_unverified") from None
