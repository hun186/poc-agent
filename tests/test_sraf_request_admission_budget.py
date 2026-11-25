"""No ES, LLM, HTTP, credentials or active production Job required."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget


def make_budget(now, **kwargs):
    return RequestAdmissionBudget(clock=lambda: now[0], **kwargs)


def test_first_round_and_all_calls_share_one_retrieval_deadline():
    now = [100.0]
    budget = make_budget(now, max_rounds=2, max_es_calls=3, max_planner_calls=1)
    assert not budget.admit("es")  # Every call needs a prior admitted round.
    assert budget.admit("round")
    assert budget.admit("es")
    assert budget.admit("planner")
    assert not budget.admit("planner")
    assert budget.admit("round")
    assert not budget.admit("round")
    now[0] += 1799
    assert budget.admit("es")
    now[0] += 1  # 30-minute retrieval cutoff, 10-minute generation reserve.
    assert not budget.admit("es")
    assert not budget.admit("round")
    hint = budget.snapshot()
    assert hint.remaining_seconds == 600
    assert hint.generation_reserve_seconds == 600
    assert hint.remaining_es_calls == 0
    assert hint.remaining_planner_calls == 0
    assert budget.rounds_started == 2


def test_atomic_slots_not_oversubscribed_under_concurrency():
    now = [50.0]
    budget = make_budget(now, max_es_calls=7)
    assert budget.admit("round")
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(lambda _: budget.admit("es"), range(160)))
    assert sum(results) == 7
    assert budget.snapshot().remaining_es_calls == 0


def test_clock_failure_or_backward_jump_denies_without_spending():
    now = [100.0]
    budget = make_budget(now, max_es_calls=1)
    assert budget.admit("round")
    now[0] = float("nan")
    assert not budget.admit("es")
    assert budget.snapshot().remaining_es_calls == 0
    now[0] = 99.0
    assert not budget.admit("es")
    now[0] = 100.0
    assert budget.admit("es")
    assert not budget.admit("es")


@pytest.mark.parametrize("kwargs", [
    {"total_seconds": True}, {"total_seconds": 86401},
    {"generation_reserve_seconds": 2400}, {"generation_reserve_seconds": -1},
    {"max_es_calls": 0}, {"max_rounds": 0}, {"max_planner_calls": -1},
    {"clock": lambda: float("inf")}, {"clock": lambda: True},
])
def test_bad_budget_fails_closed(kwargs):
    with pytest.raises(ValueError):
        RequestAdmissionBudget(**kwargs)


def test_planner_hint_never_claims_to_be_usable_without_round_admission():
    now = [0.0]
    budget = make_budget(now, max_es_calls=2, max_planner_calls=2)
    assert budget.snapshot().remaining_es_calls == 0
    assert budget.admit("round")
    assert budget.snapshot().remaining_es_calls == 2
    now[0] = 2401.0
    assert budget.snapshot().remaining_es_calls == 0
    assert not budget.admit("planner")


def test_invalid_kind_rejected():
    budget = make_budget([0.0])
    with pytest.raises(ValueError, match="invalid_request_admission_kind"):
        budget.admit("report")


def test_report_slot_uses_generation_reserve_once_and_does_not_refund():
    now = [100.0]
    budget = make_budget(now, max_rounds=2)
    assert budget.claim_report_generation(1) == 0
    assert budget.admit("round")
    assert budget.claim_report_generation(2) == 0
    now[0] += 1800
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: budget.claim_report_generation(1), range(16)))
    assert results.count(600) == 1 and results.count(0) == 15
    assert budget.claim_report_generation(1) == 0


def test_report_slot_denies_after_deadline_or_failed_clock():
    now = [100.0]
    budget = make_budget(now)
    assert budget.admit("round")
    now[0] = float("nan")
    assert budget.claim_report_generation(1) == 0
    now[0] = 2500.0
    assert budget.claim_report_generation(1) == 0


def test_optional_es_admission_keeps_mandatory_slots_and_deadline():
    now = [0.0]
    budget = make_budget(now, max_es_calls=5)
    assert not budget.admit_optional_es(1)
    assert budget.admit("round")
    assert budget.admit("es") and budget.admit("es")
    assert budget.admit_optional_es(1)
    assert budget.snapshot().remaining_es_calls == 2
    assert not budget.admit_optional_es(1)
    assert budget.admit("round")
    assert not budget.admit_optional_es(2)
    assert budget.admit("es") and budget.admit("es")
    assert budget.snapshot().remaining_es_calls == 0


def test_optional_es_atomic_per_round_and_request_cap():
    budget = make_budget([0.0], max_es_calls=20)
    for ordinal in (1, 2):
        assert budget.admit("round")
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: budget.admit_optional_es(ordinal), range(40)))
        assert sum(results) == 1
    assert budget.admit("round")
    assert not budget.admit_optional_es(3)
    assert budget.snapshot().remaining_es_calls == 18


def test_optional_es_denies_invalid_round_late_clock_and_after_planning():
    now = [100.0]
    budget = make_budget(now)
    assert budget.admit("round")
    for invalid in (True, 0, -1, 2, "1"):
        assert not budget.admit_optional_es(invalid)
    for clock in (float("nan"), 99.0, 1891.0, 1900.0):
        now[0] = clock
        assert not budget.admit_optional_es(1)
    now[0] = 1890.0
    assert budget.claim_next_strategy(1)
    assert not budget.admit_optional_es(1)
    assert budget.snapshot().remaining_es_calls == 24


def test_optional_es_denies_after_report_generation_claim():
    budget = make_budget([0.0])
    assert budget.admit("round")
    assert budget.claim_report_generation(1) > 0
    assert not budget.admit_optional_es(1)
    assert budget.snapshot().remaining_es_calls == 24
