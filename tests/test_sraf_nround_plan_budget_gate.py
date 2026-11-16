"""Offline strategy admission: no ES, API, LLM provider or report side effects."""
from __future__ import annotations

import json
import pytest

from agent.adaptive_retrieval import AdaptiveRetrievalPlanner
from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget
from agent.adaptive_retrieval.next_round_gate import propose_budgeted_next_round
from test_sraf_adaptive_planner_contract import (
    make_scope, round1, response,
)
from agent.adaptive_retrieval.contracts import RoundEvidenceSummary


def _budget(now=None, **opts):
    time = [100.0] if now is None else now
    return RequestAdmissionBudget(clock=lambda: time[0], **opts), time


def _run(planner, budget, *, scope=None, history=None):
    return propose_budgeted_next_round(
        constraints=make_scope() if scope is None else scope,
        history=(round1(),) if history is None else history,
        budget=budget, planner=planner,
    )


def test_single_planner_slot_is_charged_before_model_and_bound_plan_is_safe():
    b, _ = _budget(max_rounds=2, max_es_calls=2, max_planner_calls=1)
    assert b.admit("round")
    assert b.admit("es")  # Initial ES call must be admitted separately.
    calls = []
    def llm(prompt, *, system_prompt):
        # This runs *after* the gate has spent the last planner admission.
        calls.append(b.snapshot().remaining_planner_calls)
        return response(terms=["聯合國聲明"], aspects=["外交分析"])
    gate = _run(AdaptiveRetrievalPlanner(llm), b)
    assert gate.approved and gate.reason == "ADMITTED"
    assert gate.round_number == 2
    assert gate.plan.constraints == make_scope()
    assert gate.plan.constraints.allowed_indexes == ("news_test",)
    assert gate.plan.constraints.event_date.start == "2023-08-24"
    assert gate.plan.optional_terms == ("聯合國聲明",)
    assert calls == [0]
    assert b.rounds_started == 2
    # This function does not call ES; adapter still must pay for each ES call.
    assert b.snapshot().remaining_es_calls == 1
    assert b.admit("es")
    assert not b.admit("es")
    assert gate.safe_audit() == {
        "schema": "sraf_nround_plan_admission_v1",
        "approved": True, "reason": "ADMITTED", "round": 2,
        "scope": "strategy_only_no_es_or_llm_execution_authorized",
    }
    metrics = json.dumps(gate.safe_audit())
    for secret in ("2023-08-24", "古特雷斯", "聯合國聲明", "news_test"):
        assert secret not in metrics


def test_stale_same_history_never_spends_second_planner_or_new_round():
    b, _ = _budget(max_planner_calls=3, max_rounds=4)
    assert b.admit("round")
    times = []
    plan = AdaptiveRetrievalPlanner(
        lambda *_a, **_k: (times.append("called"), response())[1],
    )
    first = _run(plan, b)
    assert first.approved
    second = _run(plan, b)
    assert not second.approved
    assert second.reason == "STALE_ROUND_HISTORY"
    assert times == ["called"]
    assert b.rounds_started == 2
    assert b.snapshot().remaining_planner_calls == 2


@pytest.mark.parametrize("history,locked,reason", [
    ((round1(wide=False),), False, "REQUEST_LEVEL_ASSESSMENT_REQUIRED"),
    ((round1(incomplete=True),), False, "SAME_PLAN_SEARCH_INCOMPLETE"),
    ((round1(sufficient=True),), False, "SUFFICIENT"),
    ((round1(),), True, "USER_KEYWORDS_LOCKED"),
])
def test_guard_refuses_noop_without_llm_or_spending_planner(
        history, locked, reason):
    b, _ = _budget()
    assert b.admit("round")
    no_llm = AdaptiveRetrievalPlanner(
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError(
            "the guard should not invoke LLM"
        )),
    )
    outcome = _run(
        no_llm, b, scope=make_scope(locked=locked), history=history,
    )
    assert not outcome.approved
    assert outcome.reason == reason
    assert b.snapshot().remaining_planner_calls == 6
    assert b.rounds_started == 1


def test_30_minute_cutoff_and_generation_reserve_stop_new_planner_calls():
    now = [0.0]
    b, _ = _budget(now)
    assert b.admit("round")
    now[0] = 1800.0  # 2400 total - 600 generation reserve
    no_llm = AdaptiveRetrievalPlanner(
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError),
    )
    gate = _run(no_llm, b)
    assert gate.reason == "RESOURCE_BUDGET_EXHAUSTED"
    assert b.snapshot().remaining_planner_calls == 0
    assert b.rounds_started == 1


def test_elapsed_during_planner_cannot_admit_new_round_or_es():
    now = [100.0]
    b, _ = _budget(now, max_rounds=4, max_es_calls=2, max_planner_calls=1)
    assert b.admit("round")
    def llm(*_a, **_k):
        now[0] = 1900.0  # At the retrieval cutoff.
        return response()
    gate = _run(AdaptiveRetrievalPlanner(llm), b)
    assert not gate.approved
    assert gate.reason == "LATE_BUDGET_EXHAUSTED"
    assert b.rounds_started == 1
    assert not b.admit("es")


def test_invalid_model_date_index_and_extras_cannot_issue_a_plan():
    b, _ = _budget(max_planner_calls=2)
    assert b.admit("round")
    bad = AdaptiveRetrievalPlanner(
        lambda *_a, **_k: response(es_query={"match_all": {}},
                                   date_to="2025-01-01"),
    )
    gate = _run(bad, b)
    assert not gate.approved
    assert gate.reason == "PLANNER_FAILED_CLOSED"
    assert b.rounds_started == 1
    assert b.snapshot().remaining_planner_calls == 1


@pytest.mark.parametrize("reply,expected", [
    (response(action="date_recheck", code="DATE_PARSE_SUSPECTED",
              terms=[], aspects=[]), "DATE_PARSE_SUSPECTED"),
    (response(action="stop", code="NO_EXPECTED_GAIN",
              terms=[], aspects=[]), "NO_EXPECTED_GAIN"),
    (response(terms=["古特雷斯", "金磚峰會"]), "NO_NEW_QUERY_PLAN"),
])
def test_no_new_search_on_stop_date_recheck_or_repeated_terms(reply, expected):
    b, _ = _budget(max_planner_calls=2)
    assert b.admit("round")
    gate = _run(AdaptiveRetrievalPlanner(lambda *_a, **_k: reply), b)
    assert not gate.approved and gate.reason == expected
    assert b.rounds_started == 1


def test_locked_keyword_policy_or_history_without_first_admission_fails():
    b, _ = _budget()
    no_llm = AdaptiveRetrievalPlanner(lambda *_a, **_k: response())
    result = _run(no_llm, b)
    assert result.reason == "STALE_ROUND_HISTORY"
    assert b.snapshot().remaining_es_calls == 0
    assert b.rounds_started == 0


def test_diminishing_returns_stops_before_model_and_reserve():
    b, _ = _budget(max_rounds=8)
    for _ in range(3):
        assert b.admit("round")
    history = (
        round1(),
        RoundEvidenceSummary(2, ("延伸1",), 2, 0, 1, ("未覆蓋",),
                             False, False, True),
        RoundEvidenceSummary(3, ("延伸2",), 2, 0, 1, ("未覆蓋",),
                             False, False, True),
    )
    gate = _run(AdaptiveRetrievalPlanner(
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError)
    ), b, history=history)
    assert gate.reason == "DIMINISHING_RETURNS"
    assert b.snapshot().remaining_planner_calls == 6


def test_concurrent_budget_gate_does_not_overspend_limited_slots():
    from concurrent.futures import ThreadPoolExecutor
    b, _ = _budget(max_rounds=3, max_planner_calls=1)
    assert b.admit("round")
    planner = AdaptiveRetrievalPlanner(lambda *_a, **_k: response())
    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(lambda _: _run(planner, b), range(10)))
    assert sum(x.approved for x in outcomes) <= 1
    assert b.rounds_started <= 2
    assert b.snapshot().remaining_planner_calls == 0
