"""Offline N-round request state machine: synthetic ES and fake model only."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import threading

import pytest

from agent.adaptive_retrieval import AdaptiveRetrievalPlanner
from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget
from test_sraf_adaptive_planner_contract import response
from test_sraf_shared_evidence_budget import _hit, D0


def scope(*, locked=False):
    return QueryConstraints(
        question="請分析2023年8月24日甲軸乙軸丙軸事件與政策影響",
        event_date=DateWindow(D0, D0, "day", "explicit_user", D0),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
        required_entities=("甲軸",),
        original_core_terms=("甲軸", "乙軸", "丙軸"),
        keyword_policy="user_locked" if locked else "flexible",
    )


def coordinator(*, llm=None, clock=None, locked=False, _arc_deep_hint_enabled=False, **budget_options):
    budget = RequestAdmissionBudget(
        clock=(lambda: clock[0]) if clock is not None else lambda: 0.0,
        **budget_options,
    )
    calls = []
    def fake_llm(prompt, *, system_prompt):
        calls.append("planner")
        if llm is not None:
            return llm(prompt, system_prompt=system_prompt)
        return response(terms=["不同地區回應"], aspects=["後續影響"])
    c = AdaptiveRequestCoordinator(
        constraints=scope(locked=locked),
        term_groups=(("甲軸",), ("乙軸",), ("丙軸",)),
        effective_terms=("甲軸", "乙軸", "丙軸"),
        budget=budget, planner=AdaptiveRetrievalPlanner(fake_llm,
            _arc_deep_hint_enabled=_arc_deep_hint_enabled),
    )
    return c, budget, calls


def finish(c, hits, *, complete=True, attested=True, sufficient=False):
    return c.complete_round(
        copy.deepcopy(hits), query_for_snippet="甲軸乙軸丙軸",
        complete=complete, request_wide_attested=attested,
        coverage_sufficient=sufficient, missing_aspects=("後續影響",),
    )


def test_two_rounds_are_canonical_and_report_ready_only_after_assessment():
    c, budget, calls = coordinator()
    assert c.safe_progress()["phase"] == "CREATED"
    assert not c.admit_es_call()
    assert c.start()
    assert not c.start()
    with pytest.raises(ValueError, match="round_not_ready"):
        finish(c, [_hit(2, "A", inner=False)])
    assert c.admit_es_call()
    first = finish(c, [_hit(2, "A", inner=False)])
    assert first.verified_evidence == 2
    assert first.newly_verified_evidence == 2
    assert first.known_sources == 1
    assert c.safe_progress()["phase"] == "ASSESSED"
    assert not c.admit_es_call()
    plan = c.plan_next_round()
    assert plan.approved and plan.round_number == 2
    assert plan.plan.constraints == scope()  # immutable value; coordinator checks identity
    assert plan.plan.constraints.event_date.start == D0
    assert calls == ["planner"]
    assert c.safe_progress()["round"] == 2
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    assert c.admit_es_call()
    second = finish(
        c, [_hit(2, "A", inner=False), _hit(1, "B", inner=False)],
        sufficient=True,
    )
    assert second.verified_evidence == 3
    assert second.newly_verified_evidence == 1
    assert second.known_sources == 2
    progress = c.safe_progress()
    assert progress["phase"] == "TERMINAL"
    assert progress["termination"] == "SUFFICIENT"
    assert progress["completed_rounds"] == 2
    assert progress["ready_for_external_report_generation"] is True
    assert progress["report_job"] == "NOT_INTEGRATED"
    assert progress["canonical_evidence_history"][1]["new_verified"] == 1
    assert budget.rounds_started == 2
    assert not c.admit_es_call()
    with pytest.raises(ValueError, match="round_not_assessed"):
        c.plan_next_round()


def test_missing_date_wrong_event_is_not_promoted_to_verified_evidence():
    c, _, calls = coordinator()
    assert c.start() and c.admit_es_call()
    hit = _hit(4, "A", other_date_every=2, inner=False)
    report = finish(c, [hit], sufficient=True)
    assert report.verified_evidence == 2
    assert report.newly_verified_evidence == 2
    assert report.known_sources == 1
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert calls == []


@pytest.mark.parametrize("incomplete,attested,expected", [
    (True, True, "SAME_PLAN_SEARCH_INCOMPLETE"),
    (False, False, "REQUEST_LEVEL_ASSESSMENT_REQUIRED"),
])
def test_incomplete_or_unattested_request_cannot_plan_next_round(
        incomplete, attested, expected):
    c, _, calls = coordinator()
    assert c.start() and c.admit_es_call()
    result = finish(
        c, [_hit(1, "A", inner=False)],
        complete=not incomplete, attested=attested,
    )
    assert result.verified_evidence == 1
    assert c.safe_progress()["termination"] == expected
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    with pytest.raises(ValueError, match="round_not_assessed"):
        c.plan_next_round()
    assert calls == []


def test_es_index_must_be_within_frozen_authorized_indexes():
    c, _, calls = coordinator()
    assert c.start() and c.admit_es_call()
    hit = _hit(1, "SECRET", inner=False)
    hit["_index"] = "other_production_index"
    with pytest.raises(ValueError, match="round_assessment_failed"):
        finish(c, [hit])
    progress = c.safe_progress()
    assert progress["termination"] == "EVIDENCE_VALIDATION_FAILED"
    assert progress["completed_rounds"] == 0
    assert not c.admit_es_call()
    assert calls == []
    assert "other_production_index" not in json.dumps(progress)


def test_pending_round_cannot_be_report_ready_when_es_budget_exhausts():
    clock = [0.0]
    c, _, _ = coordinator(clock=clock, max_es_calls=2, max_rounds=3)
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(1, "A", inner=False)])
    assert c.plan_next_round().approved
    # The second round was legitimately admitted while ES quota remained,
    # but the 30-minute cutoff arrives before any new ES call. A previous
    # completed round must not make this pending round report-ready.
    clock[0] = 1800.0
    assert not c.admit_es_call()
    progress = c.safe_progress()
    assert progress["termination"] == "RESOURCE_BUDGET_EXHAUSTED"
    assert progress["completed_rounds"] == 1
    assert progress["ready_for_external_report_generation"] is False


def test_30min_cutoff_and_generation_reserve_prevent_new_planning():
    clock = [0.0]
    c, _, calls = coordinator(clock=clock)
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(1, "A", inner=False)])
    clock[0] = 1800.0  # 2400 seconds total, 600 seconds reserved.
    decision = c.plan_next_round()
    assert not decision.approved
    assert decision.reason == "RESOURCE_BUDGET_EXHAUSTED"
    assert calls == []
    assert not c.admit_es_call()


def test_locked_keywords_stop_without_planner_llm():
    c, _, calls = coordinator(locked=True)
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(1, "A", inner=False)])
    decision = c.plan_next_round()
    assert not decision.approved
    assert decision.reason == "USER_KEYWORDS_LOCKED"
    assert calls == []


def test_cancel_during_planner_never_reenables_es_or_mutates_scope():
    active = [None]
    c, budget, calls = coordinator(
        llm=lambda *_args, **_kwargs: (
            active[0].cancel(),
            response(terms=["其他經濟後果"], aspects=["新影響"]),
        )[1],
    )
    active[0] = c
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(1, "A", inner=False)])
    decision = c.plan_next_round()
    assert not decision.approved
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert c.safe_progress()["termination"] == "CANCELLED"
    assert not c.admit_es_call()
    assert calls == ["planner"]
    assert c.safe_progress()["report_job"] == "NOT_INTEGRATED"
    assert budget.snapshot().remaining_planner_calls < 6


def test_cancel_during_canonical_parse_prevents_late_append(monkeypatch):
    from agent.adaptive_retrieval import coordinator as module
    c, _, calls = coordinator()
    assert c.start() and c.admit_es_call()
    original = module.observe_canonical_round
    def simulated_race(*args, **kwargs):
        assert c.cancel()
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "observe_canonical_round", simulated_race)
    with pytest.raises(ValueError, match="round_assessment_failed"):
        finish(c, [_hit(1, "A", inner=False)])
    assert c.safe_progress()["completed_rounds"] == 0
    assert c.safe_progress()["termination"] == "CANCELLED"
    assert calls == []


def test_duplicate_or_concurrent_assessment_is_rejected():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    entered, unblock = threading.Event(), threading.Event()
    from agent.adaptive_retrieval import coordinator as module
    original = module.observe_canonical_round
    def blocked(*args, **kwargs):
        entered.set()
        assert unblock.wait(timeout=3)
        return original(*args, **kwargs)
    # Monkeypatch only for this test; no background ES operations.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "observe_canonical_round", blocked)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(finish, c, [_hit(1, "A", inner=False)])
            assert entered.wait(timeout=3)
            with pytest.raises(ValueError, match="round_not_ready"):
                finish(c, [_hit(1, "B", inner=False)])
            unblock.set()
            result = pending.result(timeout=5)
    assert result.verified_evidence == 1
    assert c.safe_progress()["completed_rounds"] == 1


def test_public_progress_contains_no_source_text_date_question_or_terms():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(1, "PRIVATE-ID", inner=False)], sufficient=True)
    output = json.dumps(c.safe_progress(), ensure_ascii=False)
    for forbidden in (
        "PRIVATE-ID", "甲軸", "乙軸", "丙軸", "2023-08-24",
        "請分析", "後續影響", "金磚峰會", "E1", "news_test",
    ):
        assert forbidden not in output


def test_model_error_is_terminal_without_retries_or_es():
    c, _, calls = coordinator(
        llm=lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("PRIVATE-KEY and source text")
        ),
    )
    assert c.start() and c.admit_es_call()
    finish(c, [_hit(1, "A", inner=False)])
    admission = c.plan_next_round()
    assert not admission.approved
    assert admission.reason == "PLANNER_FAILED_CLOSED"
    assert calls == ["planner"]
    assert c.safe_progress()["termination"] == "PLANNER_FAILED_CLOSED"
    assert "PRIVATE" not in json.dumps(c.safe_progress())


def test_round_zero_or_cancelled_never_generates_fake_report_handoff():
    c, _, calls = coordinator()
    assert c.cancel()
    assert not c.start()
    assert not c.cancel()
    assert not c.admit_es_call()
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    assert calls == []


def test_zero_hit_first_round_is_a_valid_complete_assessment():
    c, _, _ = coordinator()
    assert c.start() and c.admit_es_call()
    result = finish(c, [], sufficient=False)
    assert result.verified_evidence == 0
    assert result.known_sources == 0
    assert c.safe_progress()["canonical_evidence_history"][0]["candidate_sources"] == 0
    assert c.plan_next_round().approved


def test_es_slots_are_atomic_under_concurrent_admission():
    c, budget, _ = coordinator(max_es_calls=2)
    assert c.start()
    with ThreadPoolExecutor(max_workers=8) as pool:
        successes = list(pool.map(lambda _: c.admit_es_call(), range(8)))
    assert sum(successes) == 2
    assert c.safe_progress()["termination"] == "RESOURCE_BUDGET_EXHAUSTED"
    assert budget.snapshot().remaining_es_calls == 0
