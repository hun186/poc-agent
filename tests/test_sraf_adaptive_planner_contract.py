"""Offline contract tests for an independent (not yet dispatched) N-round planner."""
import json
from dataclasses import FrozenInstanceError

import pytest

from agent.adaptive_retrieval import (
    AdaptiveRetrievalPlanner, BudgetSnapshot, DateWindow,
    QueryConstraints, RoundEvidenceSummary, bind_next_round_plan, PlannerDecision,
)


def make_scope(*, locked=False):
    return QueryConstraints(
        question="請分析 2023 年 8 月 24 日古特雷斯在金磚峰會的發言與外交意義",
        event_date=DateWindow(
            "2023-08-24", "2023-08-24", "day", "explicit_user",
            "2023 年 8 月 24 日",
        ),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
        fixed_fields=(("category", "policy"),),
        required_entities=("古特雷斯", "金磚峰會"),
        original_core_terms=("古特雷斯", "金磚峰會"),
        keyword_policy="user_locked" if locked else "flexible",
    )


def round1(*, wide=True, sufficient=False, incomplete=False, new=2):
    return RoundEvidenceSummary(
        number=1, search_terms=("古特雷斯", "金磚峰會"),
        verified_evidence=2, newly_verified_evidence=new,
        known_sources=1, missing_aspects=("各國外交回應",),
        coverage_sufficient=sufficient, result_incomplete=incomplete,
        request_wide=wide,
    )


def budget(*, es=3, planner=2, remaining=1800, reserve=600):
    return BudgetSnapshot(es, planner, remaining, reserve)


def response(action="search", code="COVERAGE_GAP", terms=None, aspects=None, **extras):
    return json.dumps({
        "action": action, "reason_code": code,
        "optional_terms": terms if terms is not None else ["聯合國聲明", "外交回應"],
        "target_aspects": aspects if aspects is not None else ["各國回應"],
        **extras,
    }, ensure_ascii=False)


def test_llm_has_separate_strategy_prompt_and_only_bounded_round_feedback():
    calls = []

    def llm(prompt, *, system_prompt):
        calls.append((prompt, system_prompt))
        return response()

    planner = AdaptiveRetrievalPlanner(llm, max_rounds=6)
    result = planner.propose_next(
        constraints=make_scope(), history=(round1(),), budget=budget(),
    )
    assert result.should_search
    assert result.action == "search"
    assert result.optional_terms == ("聯合國聲明", "外交回應")
    assert result.target_aspects == ("各國回應",)
    assert len(calls) == 1
    prompt, system = calls[0]
    assert "第 2～N 輪" in system
    assert '"start":"2023-08-24"' in prompt
    assert '"precision":"day"' in prompt
    assert "各國外交回應" in prompt
    assert "news_test" not in prompt  # index remains server-owned
    assert "category" not in prompt   # field filters remain server-owned
    assert "source_id" not in prompt
    assert "event_ids" not in prompt
    assert "2023 年 8 月 24 日" in prompt


@pytest.mark.parametrize("mutated", [
    {"date_from": "2023-08-01"},
    {"date_to": "2023-08-30"},
    {"index_hint": "other_index"},
    {"es_query": {"match_all": {}}},
    {"required_entities": []},
    {"permissions": "all"},
])
def test_model_cannot_sneak_new_authority_or_date_fields(mutated):
    planner = AdaptiveRetrievalPlanner(
        lambda *_args, **_kwargs: response(**mutated)
    )
    decision = planner.propose_next(
        constraints=make_scope(), history=(round1(),), budget=budget(),
    )
    assert decision.action == "stop"
    assert decision.reason_code == "PLANNER_FAILED_CLOSED"


@pytest.mark.parametrize("terms", [
    ["2023-08-25"], ["2024年峰會"], [], ["金磚峰會", "古特雷斯"],
])
def test_rejects_date_like_noop_and_empty_new_plan(terms):
    decision = AdaptiveRetrievalPlanner(
        lambda *_args, **_kwargs: response(terms=terms),
    ).propose_next(constraints=make_scope(), history=(round1(),), budget=budget())
    assert not decision.should_search
    assert decision.reason_code in {"PLANNER_FAILED_CLOSED", "NO_NEW_QUERY_PLAN"}


def test_date_suspicion_is_a_review_request_not_a_modified_search():
    proposal = response(
        action="date_review", code="DATE_PARSE_SUSPECTED",
        terms=[], aspects=[],
    )
    result = AdaptiveRetrievalPlanner(
        lambda *_args, **_kwargs: proposal
    ).propose_next(constraints=make_scope(), history=(round1(),), budget=budget())
    assert result.action == "date_review"
    assert not result.should_search
    assert result.optional_terms == ()
    scope = make_scope()
    with pytest.raises(FrozenInstanceError):
        scope.event_date.start = "2023-08-01"
    with pytest.raises(FrozenInstanceError):
        scope.allowed_indexes = ("other_index",)


def test_locked_explicit_keyword_policy_prevents_replanning_without_llm():
    def forbidden(*args, **kwargs):
        raise AssertionError("LLM should not be called")

    result = AdaptiveRetrievalPlanner(forbidden).propose_next(
        constraints=make_scope(locked=True), history=(round1(),), budget=budget(),
    )
    assert result.reason_code == "USER_KEYWORDS_LOCKED"


@pytest.mark.parametrize("h,b,expected", [
    ((round1(wide=False),), budget(), "REQUEST_LEVEL_ASSESSMENT_REQUIRED"),
    ((round1(sufficient=True),), budget(), "SUFFICIENT"),
    ((round1(incomplete=True),), budget(), "SAME_PLAN_SEARCH_INCOMPLETE"),
    ((round1(),), budget(es=0), "RESOURCE_BUDGET_EXHAUSTED"),
    ((round1(),), budget(planner=0), "RESOURCE_BUDGET_EXHAUSTED"),
    ((round1(),), budget(remaining=600, reserve=600), "RESOURCE_BUDGET_EXHAUSTED"),
])
def test_guard_prevents_unnecessary_llm_and_es_cost(h, b, expected):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No call allowed")
    decision = AdaptiveRetrievalPlanner(forbidden).propose_next(
        constraints=make_scope(), history=h, budget=b,
    )
    assert decision.reason_code == expected
    assert not decision.should_search


def test_round_three_and_four_replanning_uses_history_not_initial_extractor():
    seen = []
    def llm(prompt, *, system_prompt):
        seen.append(json.loads(prompt.split("\n", 1)[1]))
        return response(terms=["第三國外交立場"], aspects=["新外交影響"])
    rounds = (
        round1(),
        RoundEvidenceSummary(
            number=2, search_terms=("聯合國聲明", "外交回應"),
            verified_evidence=4, newly_verified_evidence=2,
            known_sources=3, missing_aspects=("第三國立場",),
            coverage_sufficient=False, result_incomplete=False,
            request_wide=True,
        ),
        RoundEvidenceSummary(
            number=3, search_terms=("聯合國", "各國外交回應"),
            verified_evidence=6, newly_verified_evidence=2,
            known_sources=4, missing_aspects=("特定國家回應",),
            coverage_sufficient=False, result_incomplete=False,
            request_wide=True,
        ),
    )
    proposal = AdaptiveRetrievalPlanner(llm, max_rounds=8).propose_next(
        constraints=make_scope(), history=rounds, budget=budget(),
    )
    assert proposal.should_search
    assert len(seen[0]["prior_rounds"]) == 3
    assert seen[0]["prior_rounds"][-1]["round"] == 3
    # LLM cannot override the frozen original question or date.
    assert seen[0]["hard_constraints_read_only"]["event_date"]["start"] == "2023-08-24"


def test_stagnation_or_maximum_round_count_stops_before_llm():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No call allowed")
    rounds = (
        round1(),
        RoundEvidenceSummary(2, ("聯合國",), 2, 0, 1, ("回應",), False, False, True),
        RoundEvidenceSummary(3, ("各國聲明",), 2, 0, 1, ("回應",), False, False, True),
    )
    result = AdaptiveRetrievalPlanner(forbidden).propose_next(
        constraints=make_scope(), history=rounds, budget=budget(),
    )
    assert result.reason_code == "DIMINISHING_RETURNS"
    result = AdaptiveRetrievalPlanner(forbidden, max_rounds=3).propose_next(
        constraints=make_scope(), history=rounds, budget=budget(),
    )
    assert result.reason_code == "ROUND_BUDGET_EXHAUSTED"


def test_invalid_history_fails_closed_without_retry_or_logging():
    history = (
        round1(),
        RoundEvidenceSummary(3, ("外交",), 2, 1, 1, (), False, False, True),
    )
    plan = AdaptiveRetrievalPlanner(lambda *_args, **_kwargs: "{}")
    assert plan.propose_next(
        constraints=make_scope(), history=history, budget=budget(),
    ).reason_code == "INCONSISTENT_ROUND_HISTORY"
    assert plan.propose_next(
        constraints=make_scope(), history=(), budget=budget(),
    ).reason_code == "REQUEST_LEVEL_ASSESSMENT_REQUIRED"


@pytest.mark.parametrize("raw", ["not json", "{}", "[]", "null", "x" * 4100])
def test_malformed_model_result_safe_stop(raw):
    result = AdaptiveRetrievalPlanner(lambda *_a, **_k: raw).propose_next(
        constraints=make_scope(), history=(round1(),), budget=budget(),
    )
    assert result.reason_code == "PLANNER_FAILED_CLOSED"


def test_model_and_input_failures_cannot_trigger_search_or_change_scope():
    scope = make_scope()
    before = scope

    def llm(*_args, **_kwargs):
        raise RuntimeError("PRIVATE API KEY and Evidence text")

    result = AdaptiveRetrievalPlanner(llm).propose_next(
        constraints=scope, history=(round1(),), budget=budget(),
    )
    assert result.action == "stop"
    assert result.reason_code == "PLANNER_FAILED_CLOSED"
    assert scope == before


@pytest.mark.parametrize("kwargs", [
    {"start": "2023-08-25", "end": "2023-08-24", "precision": "day", "source": "explicit_user", "source_text": "日期"},
    {"start": "2023-02-29", "end": "2023-02-29", "precision": "day", "source": "explicit_user", "source_text": "日期"},
    {"start": "2023-08-24", "end": "2023-08-24", "precision": "day", "source": "none"},
    {"start": "2023-08-24", "end": "2023-08-24", "precision": "none", "source": "explicit_user", "source_text": "日期"},
])
def test_invalid_date_contract_rejected(kwargs):
    with pytest.raises(ValueError):
        DateWindow(**kwargs)


def test_event_and_analysis_time_remain_distinct_facets():
    scope = QueryConstraints(
        question="分析 2023-08-24 峰會後三個月的外交影響",
        event_date=DateWindow("2023-08-24", "2023-08-24", "day", "explicit_user", "2023-08-24"),
        analysis_date=DateWindow("2023-08-25", "2023-11-24", "day", "trusted_context", "峰會後三個月"),
        allowed_indexes=("news_test",), required_entities=("峰會",),
    )
    prompts = []
    def llm(prompt, *, system_prompt):
        prompts.append(prompt)
        return response()
    decision = AdaptiveRetrievalPlanner(llm).propose_next(
        constraints=scope, history=(round1(),), budget=budget(),
    )
    assert decision.should_search
    assert '"start":"2023-08-25"' in prompts[0]
    assert '"end":"2023-11-24"' in prompts[0]


def test_bound_search_plan_reuses_frozen_dates_fields_indexes_and_entities():
    scope = make_scope()
    decision = AdaptiveRetrievalPlanner(
        lambda *_args, **_kwargs: response(),
    ).propose_next(constraints=scope, history=(round1(),), budget=budget())
    plan = bind_next_round_plan(
        constraints=scope, history=(round1(),), decision=decision,
    )
    assert plan.round_number == 2
    assert plan.constraints is scope
    assert plan.constraints.event_date.start == "2023-08-24"
    assert plan.constraints.allowed_indexes == ("news_test",)
    assert plan.constraints.fixed_fields == (("category", "policy"),)
    assert plan.constraints.required_entities == ("古特雷斯", "金磚峰會")
    assert plan.optional_terms == ("聯合國聲明", "外交回應")


def test_binding_rejects_manually_crafted_date_or_unsafe_plan():
    scope = make_scope()
    for crafted in (
        PlannerDecision("search", "COVERAGE_GAP", ("2024年",), ("外交",)),
        PlannerDecision("search", "COVERAGE_GAP", ("古特雷斯",), ("外交",)),
        PlannerDecision("search", "COVERAGE_GAP", (), ("外交",)),
        PlannerDecision("date_review", "DATE_PARSE_SUSPECTED"),
    ):
        with pytest.raises(ValueError):
            bind_next_round_plan(
                constraints=scope, history=(round1(),), decision=crafted,
            )
    with pytest.raises(ValueError):
        bind_next_round_plan(
            constraints=make_scope(locked=True), history=(round1(),),
            decision=PlannerDecision("search", "COVERAGE_GAP", ("聯合國",), ("外交",)),
        )
    with pytest.raises(ValueError):
        bind_next_round_plan(
            constraints=scope, history=(round1(incomplete=True),),
            decision=PlannerDecision("search", "COVERAGE_GAP", ("聯合國",), ("外交",)),
        )


def test_multiline_user_question_is_preserved_without_accepting_control_bytes():
    original = "請分析 2023 年 8 月 24 日古特雷斯的發言。\\n並補充外交背景。"
    scope = QueryConstraints(
        question=original, event_date=DateWindow(),
        analysis_date=DateWindow(), allowed_indexes=("news_test",),
    )
    assert scope.question == original
    with pytest.raises(ValueError, match="invalid_adaptive_question"):
        QueryConstraints(
            question="unsafe\\x00question", event_date=DateWindow(),
            analysis_date=DateWindow(), allowed_indexes=("news_test",),
        )
