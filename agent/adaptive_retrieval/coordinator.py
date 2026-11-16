"""Request-local, NON-PRODUCTION adaptive retrieval coordinator.

A state machine that composes the existing RequestAdmissionBudget, canonical
Evidence ledger and atomic next-round planner gate. It performs NO ES, network,
LLM provider, SQL, Report Job or DOCX IO. Only its caller may run ES using
an independently authorized adapter and return all intended results.

This module does NOT attest ES pages, query DSL, identity, RBAC, completeness,
semantic coverage, cancellation of in-flight calls or persistence. No API or
ReportJobWorker imports this coordinator. Its audit exposes counts only.
"""
from __future__ import annotations

from threading import Lock
from typing import Any

from .contracts import QueryConstraints, RoundEvidenceSummary, _bounded_text
from .evidence_ledger import (
    MAX_ROUNDS, RequestWideEvidenceLedger, observe_canonical_round,
)
from .next_round_gate import NextRoundAdmission, propose_budgeted_next_round
from .planner import AdaptiveRetrievalPlanner
from .request_budget import RequestAdmissionBudget


_PHASES = frozenset((
    "CREATED", "SEARCHING", "ASSESSING", "ASSESSED", "PLANNING", "TERMINAL",
))
_TERMINATIONS = frozenset((
    "NONE", "SUFFICIENT", "CANCELLED", "ROUND_BUDGET_EXHAUSTED",
    "RESOURCE_BUDGET_EXHAUSTED", "SAME_PLAN_SEARCH_INCOMPLETE",
    "REQUEST_LEVEL_ASSESSMENT_REQUIRED", "EVIDENCE_VALIDATION_FAILED",
    "PLANNER_FAILED_CLOSED", "DIMINISHING_RETURNS", "NO_EXPECTED_GAIN",
    "USER_KEYWORDS_LOCKED", "NO_NEW_QUERY_PLAN", "DATE_PARSE_SUSPECTED",
    "INVALID_CONTEXT", "INCONSISTENT_ROUND_HISTORY", "PLANNER_STOPPED",
    "UNTRUSTED_NEXT_ROUND_SCOPE", "LATE_BUDGET_EXHAUSTED",
    "STALE_ROUND_HISTORY", "NO_NEW_STRATEGY",
))
_RECOVERABLE_REPORT_STOPS = frozenset((
    "SUFFICIENT", "ROUND_BUDGET_EXHAUSTED", "RESOURCE_BUDGET_EXHAUSTED",
    "DIMINISHING_RETURNS", "NO_EXPECTED_GAIN", "NO_NEW_QUERY_PLAN",
    "USER_KEYWORDS_LOCKED",
))


class AdaptiveRequestCoordinator:
    """One request's trusted, bounded *accounting* and planning state machine.

    The adapter must explicitly reserve a slot before each ES request, then
    independently enforce scope, original dates, index/RBAC, timeouts and PIT
    consistency. Merely reserving a slot is NOT authorization to run ES.
    """

    def __init__(
        self, *,
        constraints: QueryConstraints,
        term_groups: tuple[tuple[str, ...], ...],
        effective_terms: tuple[str, ...],
        budget: RequestAdmissionBudget,
        planner: AdaptiveRetrievalPlanner,
    ) -> None:
        if (type(constraints) is not QueryConstraints
                or type(budget) is not RequestAdmissionBudget
                or type(planner) is not AdaptiveRetrievalPlanner
                or type(term_groups) is not tuple
                or not 1 <= len(term_groups) <= 32
                or type(effective_terms) is not tuple
                or len(effective_terms) > 64):
            raise ValueError("invalid_adaptive_coordinator_config")
        groups: list[set[str]] = []
        for group in term_groups:
            if type(group) is not tuple or not 1 <= len(group) <= 32:
                raise ValueError("invalid_adaptive_topic_contract")
            checked = {_bounded_text(v, limit=100) for v in group}
            if len(checked) != len(group):
                raise ValueError("duplicate_adaptive_topic_terms")
            groups.append(checked)
        for term in effective_terms:
            _bounded_text(term, limit=100)
        self._constraints = constraints
        self._groups = groups
        self._effective = list(effective_terms)
        self._budget = budget
        self._planner = planner
        self._ledger = RequestWideEvidenceLedger()
        self._lock = Lock()
        self._phase = "CREATED"
        self._terminal_reason = "NONE"
        self._round = 0
        self._es_slots_this_round = 0
        self._search_terms = constraints.original_core_terms

    def _terminate_locked(self, reason: str) -> None:
        self._phase = "TERMINAL"
        self._terminal_reason = (
            reason if reason in _TERMINATIONS else "PLANNER_STOPPED"
        )

    def start(self) -> bool:
        """Admit round one. Does not run the first ES query."""
        with self._lock:
            if self._phase != "CREATED":
                return False
            if not self._budget.admit("round"):
                self._terminate_locked("RESOURCE_BUDGET_EXHAUSTED")
                return False
            self._round = 1
            self._es_slots_this_round = 0
            self._phase = "SEARCHING"
            return True

    def admit_es_call(self) -> bool:
        """Nonrefundable slot for one *future* adapter ES call, no IO here."""
        with self._lock:
            if (self._phase != "SEARCHING"
                    or self._budget.rounds_started != self._round):
                return False
            if not self._budget.admit("es"):
                self._terminate_locked("RESOURCE_BUDGET_EXHAUSTED")
                return False
            self._es_slots_this_round += 1
            return True

    def complete_round(
        self, es_hits: list[dict[str, Any]], *,
        query_for_snippet: str, complete: bool,
        request_wide_attested: bool,
        missing_aspects: tuple[str, ...],
        coverage_sufficient: bool,
    ) -> RoundEvidenceSummary:
        """Consume external ES results with canonical date/topic checks.

        Only the *trusted caller* can attest all intended ES pages/queries
        were fetched and coverage assessed. If input is invalid, transition
        terminal fail-closed; no model call and no automatic retry.
        """
        with self._lock:
            if (self._phase != "SEARCHING" or
                    self._es_slots_this_round == 0 or
                    self._budget.rounds_started != self._round):
                raise ValueError("round_not_ready_for_assessment")
            self._phase = "ASSESSING"
            round_terms = self._search_terms
        try:
            if (type(es_hits) is not list
                    or any(type(hit) is not dict or
                           hit.get("_index") not in self._constraints.allowed_indexes
                           for hit in es_hits)):
                raise ValueError("untrusted_es_index")
            event_window = self._constraints.event_date
            observation = observe_canonical_round(
                es_hits,
                date_from=event_window.start,
                date_to=event_window.end,
                term_groups=[set(group) for group in self._groups],
                effective_terms=list(self._effective),
                query_for_snippet=query_for_snippet,
                original_question=self._constraints.question,
                complete=complete,
            )
            with self._lock:
                if self._phase != "ASSESSING":
                    raise ValueError("round_was_cancelled")
                record = self._ledger.append(
                    observation, search_terms=round_terms,
                    missing_aspects=missing_aspects,
                    coverage_sufficient=coverage_sufficient,
                    request_wide_attested=request_wide_attested,
                )
                if record.result_incomplete:
                    self._terminate_locked("SAME_PLAN_SEARCH_INCOMPLETE")
                elif not record.request_wide:
                    self._terminate_locked("REQUEST_LEVEL_ASSESSMENT_REQUIRED")
                elif record.coverage_sufficient:
                    self._terminate_locked("SUFFICIENT")
                else:
                    self._phase = "ASSESSED"
                return record
        except Exception:
            with self._lock:
                if self._phase == "ASSESSING":
                    self._terminate_locked("EVIDENCE_VALIDATION_FAILED")
            raise ValueError("round_assessment_failed") from None

    def plan_next_round(self) -> NextRoundAdmission:
        """Return a guarded strategy, not an ES query or executable job."""
        with self._lock:
            if self._phase != "ASSESSED":
                raise ValueError("round_not_assessed")
            if len(self._ledger.history) >= MAX_ROUNDS:
                self._terminate_locked("ROUND_BUDGET_EXHAUSTED")
                return NextRoundAdmission(
                    approved=False, reason="ROUND_BUDGET_EXHAUSTED",
                    round_number=self._round,
                )
            history = self._ledger.history
            self._phase = "PLANNING"
        try:
            admission = propose_budgeted_next_round(
                constraints=self._constraints, history=history,
                budget=self._budget, planner=self._planner,
            )
        except Exception:
            admission = NextRoundAdmission(
                approved=False, reason="PLANNER_FAILED_CLOSED",
                round_number=min(32, len(history) + 1),
            )
        with self._lock:
            if self._phase != "PLANNING":
                # A cancellation during an injected, slow planner callback
                # cannot be reversed and may have spent a nonrefundable slot.
                return NextRoundAdmission(
                    approved=False, reason="PLANNER_STOPPED",
                    round_number=min(32, len(history) + 1),
                )
            if not admission.approved:
                self._terminate_locked(admission.reason)
            elif (admission.plan is None
                  or admission.plan.constraints is not self._constraints
                  or admission.round_number != self._round + 1
                  or self._budget.rounds_started != self._round + 1):
                self._terminate_locked("UNTRUSTED_NEXT_ROUND_SCOPE")
                return NextRoundAdmission(
                    approved=False, reason="UNTRUSTED_NEXT_ROUND_SCOPE",
                    round_number=min(32, self._round + 1),
                )
            else:
                self._round = admission.round_number
                self._es_slots_this_round = 0
                self._search_terms = admission.plan.optional_terms
                self._phase = "SEARCHING"
            return admission

    def cancel(self) -> bool:
        """Stop future admissions; does NOT cancel in-flight model or ES IO."""
        with self._lock:
            if self._phase == "TERMINAL":
                return False
            self._terminate_locked("CANCELLED")
            return True

    @property
    def history(self) -> tuple[RoundEvidenceSummary, ...]:
        """Private server-side per-round history; NOT a client/audit payload."""
        with self._lock:
            return self._ledger.history

    def safe_progress(self) -> dict[str, object]:
        """Count-only snapshot; no source hashes, terms, question or dates."""
        with self._lock:
            if self._phase not in _PHASES:
                raise ValueError("unknown_adaptive_phase")
            return {
                "schema": "sraf_nround_coordinator_progress_v1",
                "phase": self._phase,
                "round": self._round,
                "es_calls_admitted_this_round": self._es_slots_this_round,
                "completed_rounds": len(self._ledger.history),
                "termination": self._terminal_reason,
                "ready_for_external_report_generation": (
                    self._phase == "TERMINAL"
                    and self._terminal_reason in _RECOVERABLE_REPORT_STOPS
                    and bool(self._ledger.history)
                    and all(
                        r.request_wide and not r.result_incomplete
                        for r in self._ledger.history
                    )
                ),
                "canonical_evidence_history": self._ledger.safe_audit(),
                "live_es": "NOT_EXECUTED_BY_COORDINATOR",
                "report_job": "NOT_INTEGRATED",
                "checkpoint_resume": "NOT_IMPLEMENTED",
            }
