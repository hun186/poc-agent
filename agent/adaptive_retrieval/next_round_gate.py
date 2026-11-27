"""Safe, *non-executing* admission gate for a future SRAF N-round Report Job.

All LLM/ES operations are still external. This bridge authorizes at most one
new NEXT-ROUND STRATEGY per completed request-wide Evidence history and
consumes the existing request-local admission budget before the planner LLM.
It does not execute ES, construct DSL, allocate tokens, cancel in-flight SDK
requests, persist a Report Job, or change the production single-round path.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import QueryConstraints, RoundEvidenceSummary
from .planner import (
    AdaptiveRetrievalPlanner, BoundNextRoundPlan,
    bind_next_round_plan,
)
from .request_budget import RequestAdmissionBudget


_REASONS = frozenset((
    "ADMITTED", "INVALID_CONTEXT", "REQUEST_LEVEL_ASSESSMENT_REQUIRED",
    "INCONSISTENT_ROUND_HISTORY", "SAME_PLAN_SEARCH_INCOMPLETE",
    "SUFFICIENT", "USER_KEYWORDS_LOCKED", "ROUND_BUDGET_EXHAUSTED",
    "RESOURCE_BUDGET_EXHAUSTED", "DIMINISHING_RETURNS",
    "NO_NEW_QUERY_PLAN", "DATE_PARSE_SUSPECTED",
    "NO_EXPECTED_GAIN", "COVERAGE_GAP", "PLANNER_FAILED_CLOSED",
    "UNTRUSTED_NEXT_ROUND_SCOPE", "SUFFICIENT", "NO_NEW_STRATEGY",
    "STALE_ROUND_HISTORY", "PLANNER_STOPPED", "LATE_BUDGET_EXHAUSTED",
))
_ALLOWED_REASON = {reason for reason in _REASONS}


@dataclass(frozen=True)
class NextRoundAdmission:
    """Plan is server-only. Never serialize private terms to an audit stream."""
    approved: bool
    reason: str
    round_number: int
    plan: BoundNextRoundPlan | None = None

    def __post_init__(self) -> None:
        if (type(self.approved) is not bool
                or self.reason not in _ALLOWED_REASON
                or type(self.round_number) is not int
                or not 0 <= self.round_number <= 32
                or (self.approved != (self.plan is not None))):
            raise ValueError("invalid_next_round_admission")

    def safe_audit(self) -> dict[str, str | int | bool]:
        """No original question, search term, index, date or source identity."""
        return {
            "schema": "sraf_nround_plan_admission_v1",
            "approved": self.approved,
            "reason": self.reason,
            "round": self.round_number,
            "scope": "strategy_only_no_es_execution_authorized",
        }


def propose_budgeted_next_round(
    *, constraints: QueryConstraints,
    history: tuple[RoundEvidenceSummary, ...],
    budget: RequestAdmissionBudget,
    planner: AdaptiveRetrievalPlanner,
    _arc_hint=None,
) -> NextRoundAdmission:
    """Charge planner admission BEFORE its callable; never submit ES here.

    For a true N-round job, the trusted coordinator must call
    budget.admit("round") before round 1, budget.admit("es") before EVERY ES
    request, append canonical request-wide evidence after all pages complete,
    and pass the resulting ledger history to this function. This gate
    reserves a new round only AFTER the planner produces a valid bound plan.

    A snapshot is taken before spending the planner slot: the existing
    planner's own guard expects a positive remaining_planner_calls hint.
    The actual planner call is protected by the nonrefundable, atomic
    claim_next_strategy(completed_rounds) immediately before use. A new round is re-admitted after the call, so an
    expired clock cannot authorize subsequent ES work.
    """
    def stop(reason: str) -> NextRoundAdmission:
        if reason not in _ALLOWED_REASON:
            reason = "PLANNER_STOPPED"
        return NextRoundAdmission(
            approved=False, reason=reason,
            round_number=(min(32, len(history) + 1)
                          if type(history) is tuple else 0),
        )

    if (type(constraints) is not QueryConstraints
            or type(budget) is not RequestAdmissionBudget
            or type(planner) is not AdaptiveRetrievalPlanner
            or type(history) is not tuple or not history
            or any(type(row) is not RoundEvidenceSummary or
                   row.number != i + 1 for i, row in enumerate(history))):
        return stop("INVALID_CONTEXT")
    if (any(not row.request_wide for row in history)):
        return stop("REQUEST_LEVEL_ASSESSMENT_REQUIRED")
    if history[-1].result_incomplete:
        return stop("SAME_PLAN_SEARCH_INCOMPLETE")
    if history[-1].coverage_sufficient:
        return stop("SUFFICIENT")
    if constraints.keyword_policy == "user_locked":
        return stop("USER_KEYWORDS_LOCKED")
    if len(history) >= planner.max_rounds:
        return stop("ROUND_BUDGET_EXHAUSTED")
    if len(history) >= 3 and all(
        row.newly_verified_evidence == 0 for row in history[-2:]
    ):
        return stop("DIMINISHING_RETURNS")
    # Each request-local budget round must correspond to a completed
    # request-wide ledger round. Repeated calls on stale history must never
    # buy new planner/ES calls or bypass a pending Evidence assessment.
    if budget.rounds_started != len(history):
        return stop("STALE_ROUND_HISTORY")
    snapshot = budget.snapshot()
    if (snapshot.remaining_es_calls < 1 or
            snapshot.remaining_planner_calls < 1 or
            snapshot.remaining_seconds <= snapshot.generation_reserve_seconds):
        return stop("RESOURCE_BUDGET_EXHAUSTED")
    # One lock-protected, nonrefundable claim; rejects both concurrent
    # attempts on the SAME history and an exhausted next-round quota before
    # any Planner LLM call. Generic admit("planner") alone cannot do this.
    if not budget.claim_next_strategy(len(history)):
        return stop("RESOURCE_BUDGET_EXHAUSTED")
    decision = planner.propose_next(
        constraints=constraints, history=history, budget=snapshot,
        **({"_arc_hint": _arc_hint} if _arc_hint is not None else {}),
    )
    if not decision.should_search:
        return stop(decision.reason_code)
    try:
        bound = bind_next_round_plan(
            constraints=constraints, history=history, decision=decision,
        )
    except Exception:
        return stop("UNTRUSTED_NEXT_ROUND_SCOPE")
    if not budget.admit("round"):
        return stop("LATE_BUDGET_EXHAUSTED")
    return NextRoundAdmission(
        approved=True, reason="ADMITTED",
        round_number=bound.round_number, plan=bound,
    )
