"""Synthetic executable N-round loop, no real ES provider or Report Job."""
from __future__ import annotations

import json

import pytest

from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.coverage_evaluator import RequestWideCoverageEvaluator
from agent.adaptive_retrieval.planner import AdaptiveRetrievalPlanner
from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget
from agent.adaptive_retrieval.trusted_execution_loop import (
    TrustedNroundExecutionError, run_trusted_nround,
)
from test_sraf_nround_es_pit_adapter import FakeES, _page
from test_sraf_shared_evidence_budget import _hit as canonical_hit, D0


def _setup(*, max_es_calls=24):
    clock = [0.0]
    constraints = QueryConstraints(
        question="PRIVATE_請分析2023年甲軸乙軸丙軸與外交影響",
        event_date=DateWindow(D0, D0, "day", "explicit_user", D0),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
        required_entities=("甲軸",),
        original_core_terms=("甲軸", "乙軸", "丙軸"),
    )
    planner_calls = []
    def fake_planner(prompt, *, system_prompt):
        planner_calls.append(1)
        return json.dumps({
            "action": "search", "reason_code": "COVERAGE_GAP",
            "optional_terms": ["聯合國聲明"],
            "target_aspects": ["外交回應"],
        }, ensure_ascii=False)
    budget = RequestAdmissionBudget(
        clock=lambda: clock[0], max_es_calls=max_es_calls)
    coordinator = AdaptiveRequestCoordinator(
        constraints=constraints,
        term_groups=(("甲軸",), ("乙軸",), ("丙軸",)),
        effective_terms=("甲軸", "乙軸", "丙軸"),
        budget=budget, planner=AdaptiveRetrievalPlanner(fake_planner),
    )
    evaluator = RequestWideCoverageEvaluator(
        constraints=constraints, target_aspects=("外交回應",),
        min_evidence_per_target=2, min_sources_per_target=2,
    )
    return coordinator, constraints, evaluator, budget, planner_calls, clock


def _verified_page(name, *, count=2):
    doc = canonical_hit(count, "PRIVATE_DOC_" + name, inner=False)
    doc["sort"] = [5.0, 100, name]
    return _page([doc])


def _run(c, scope, ev, es, *, assessor=None, attestor=None, **kwargs):
    return run_trusted_nround(
        coordinator=c,
        constraints=scope, evaluator=ev,
        authorized_indexes=("news_test",), es_client=es,
        semantic_assessor=(
            (lambda target, evidence: True) if assessor is None else assessor),
        attest_whole_query_scope=(
            (lambda plan, result: True) if attestor is None else attestor),
        query_for_snippet="甲軸乙軸丙軸",
        **kwargs,
    )


def test_full_two_round_synthetic_loop_uses_real_pit_bridge_and_semantic_coverage():
    c, scope, evaluator, budget, planner_calls, clock = _setup()
    es = FakeES(_verified_page("A"), _verified_page("B"))
    inspected = []
    def assess(target, private):
        inspected.append((target.kind, private.text, private.date_iso))
        return True
    attest_calls = []
    def attest(plan, result):
        attest_calls.append((
            plan.round_number, result.query_plan_complete,
            result.request_wide_attested))
        return True
    result = _run(c, scope, evaluator, es, assessor=assess, attestor=attest)
    assert len(result.rounds) == 2
    assert [r.round_number for r in result.rounds] == [1, 2]
    assert planner_calls == [1]
    assert attest_calls == [(1, True, False), (2, True, False)]
    assert len(inspected) == 8  # 2 passages x 2 facets x 2 rounds
    assert all(when == D0 for _, _, when in inspected)
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert c.safe_progress()["completed_rounds"] == 2
    assert c.history[0].coverage_sufficient is False
    assert c.history[1].coverage_sufficient is True
    assert c.history[1].known_sources == 2
    assert c.history[1].newly_verified_evidence == 2
    assert len(es.searches) == 2
    assert [kind for kind, _ in es.calls] == [
        "open", "search", "close", "open", "search", "close"]
    assert budget.snapshot().remaining_es_calls == 20  # two PIT opens + two pages
    safe = json.dumps(result.safe_audit(), ensure_ascii=False)
    assert result.safe_audit()["report_job"] == "NOT_INTEGRATED"
    assert result.safe_audit()["word_generated"] is False
    for secret in ("PRIVATE_DOC", "news_test", "甲軸", D0):
        assert secret not in safe
    assert "PRIVATE_DOC" not in repr(result)


def test_external_request_wide_scope_proof_required_even_with_complete_pit():
    c, scope, ev, _, calls, _ = _setup()
    es = FakeES(_verified_page("A"))
    semantics = []
    with pytest.raises(TrustedNroundExecutionError, match="trusted_nround_execution_failed"):
        _run(c, scope, ev, es, assessor=lambda *a: semantics.append(1) or True,
             attestor=lambda *_: False)
    assert semantics == []
    assert len(es.searches) == 1
    assert c.history == ()
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    assert calls == []


def test_caller_attestor_non_boolean_cannot_pretend_to_be_true():
    c, scope, ev, _, calls, _ = _setup()
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, FakeES(_verified_page("A")),
             attestor=lambda *_: "true")
    assert c.history == ()
    assert calls == []


def test_semantic_verifier_failure_never_commits_coverage_or_plans_more_rounds():
    c, scope, ev, _, calls, _ = _setup()
    def invalid_semantics(*_):
        raise RuntimeError("PRIVATE_LLM_RESPONSE_URL")
    with pytest.raises(TrustedNroundExecutionError) as err:
        _run(c, scope, ev, FakeES(_verified_page("A")),
             assessor=invalid_semantics)
    assert "PRIVATE_" not in str(err.value)
    assert c.history == ()
    assert calls == []
    assert c.safe_progress()["termination"] == "CANCELLED"


def test_missing_semantic_assessor_rejected_before_first_es_io():
    c, scope, ev, _, calls, _ = _setup()
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError, match="invalid_trusted_nround_context"):
        run_trusted_nround(
            coordinator=c, constraints=scope,
            evaluator=ev, authorized_indexes=("news_test",),
            es_client=es, semantic_assessor=None,
            attest_whole_query_scope=lambda *_: True,
            query_for_snippet="甲軸乙軸丙軸",
        )
    assert es.calls == []
    assert c.safe_progress()["phase"] == "CREATED"


def test_failed_pit_or_partial_shards_cannot_return_partial_rounds():
    c, scope, ev, _, calls, _ = _setup()
    es = FakeES(_page([canonical_hit(1, "PRIVATE")], successful=1))
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es)
    assert c.history == ()
    assert calls == []
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_operator_cap_does_not_publish_incomplete_multi_round_result():
    c, scope, ev, budget, calls, _ = _setup()
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, max_rounds=1)
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    assert c.safe_progress()["completed_rounds"] == 1
    assert calls == []  # no unexecutable next strategy was purchased
    assert budget.rounds_started == 1


@pytest.mark.parametrize("cutoff_at", ["after_scope", "after_semantic"])
def test_expired_retrieval_budget_after_callbacks_fails_closed(cutoff_at):
    c, scope, ev, _, calls, clock = _setup()
    es = FakeES(_verified_page("A"))
    def attest(*_):
        if cutoff_at == "after_scope":
            clock[0] = 1900.0
        return True
    semantic_calls = []
    def assessor(*_):
        semantic_calls.append(1)
        if cutoff_at == "after_semantic":
            clock[0] = 1900.0
        return True
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, attestor=attest, assessor=assessor)
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert c.safe_progress()["completed_rounds"] == 0
    assert calls == []
    assert len(semantic_calls) == (0 if cutoff_at == "after_scope" else 1)


def test_cancel_during_semantic_callback_is_not_reversed():
    c, scope, ev, _, calls, clock = _setup()
    es = FakeES(_verified_page("A"))
    semantic_calls = []
    def cancel(*_):
        semantic_calls.append(1)
        c.cancel()
        return True
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, assessor=cancel)
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert c.history == ()
    assert calls == []
    assert semantic_calls == [1]


def test_arc_shadow_budget_is_shared_between_deep_rounds_and_sealed(monkeypatch, caplog):
    from agent.adaptive_retrieval import trusted_execution_loop as loop
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, current_arc_budget
    # A one-round-sized request budget deliberately exhausts before round 2.
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    created = []
    c, scope, evaluator, budget, planner_calls, _ = _setup()

    def factory(*, model_window_guard):
        assert model_window_guard == budget.optional_model_window_open
        child = ArcRequestBudget(
            request_limit=ArcUnits(slices=2, hits=256, rows=512, chars=262144),
            round_limit=ArcUnits(slices=2, hits=256, rows=512, chars=262144),
            model_window_guard=model_window_guard,
        )
        created.append(child)
        return child

    monkeypatch.setattr(loop, "ArcRequestBudget", factory)
    es = FakeES(_verified_page("A"), _verified_page("B"))
    result = _run(c, scope, evaluator, es)
    assert len(result.rounds) == 2
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert len(es.searches) == 2 and planner_calls == [1]
    assert budget.snapshot().remaining_es_calls == 20
    prefix = "SRAF_ARC_GROUP_FREQUENCY="
    rows = [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(rows) == 4
    assert all(r["status"] == "observed_sample" for r in rows[:2])
    assert all(r["status"] == "shared_budget_exhausted" for r in rows[2:])
    assert len(created) == 1
    owned = created[0]
    total, rounds = owned.snapshot()
    assert total == ArcUnits(slices=2, hits=256, rows=512, chars=262144)
    assert set(rounds) == {1}
    assert current_arc_budget() is None
    assert not owned.reserve(2, ArcUnits(slices=1))


def test_arc_deep_scope_restored_and_sealed_on_failed_attestation(monkeypatch):
    from agent.adaptive_retrieval import trusted_execution_loop as loop
    from agent.es.arc_request_budget import (
        ArcRequestBudget, ArcUnits, bind_arc_budget, current_arc_budget,
    )
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    parent = ArcRequestBudget()
    created = []
    c, scope, ev, budget, _, _ = _setup()

    def factory(*, model_window_guard):
        assert model_window_guard == budget.optional_model_window_open
        child = ArcRequestBudget(model_window_guard=model_window_guard)
        created.append(child)
        return child

    monkeypatch.setattr(loop, "ArcRequestBudget", factory)
    with bind_arc_budget((parent, 3)):
        with pytest.raises(TrustedNroundExecutionError):
            _run(c, scope, ev, FakeES(_verified_page("A")), attestor=lambda *_: False)
        assert current_arc_budget() == (parent, 3)
    assert parent.snapshot()[0] == ArcUnits()
    assert len(created) == 1
    owned = created[0]
    assert owned.snapshot()[0] == ArcUnits()
    assert not owned.reserve(1, ArcUnits(slices=1))
    assert current_arc_budget() is None


def test_arc_deep_time_fence_uses_parent_clock_and_shared_round_slots(monkeypatch):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits
    _, _, _, parent, _, clock = _setup()
    arc = ArcRequestBudget(model_window_guard=parent.optional_model_window_open)
    assert not arc.reserve(1, ArcUnits(llm_calls=1))
    assert parent.admit("round")
    clock[0] = 1775
    assert arc.reserve(1, ArcUnits(llm_calls=1))
    assert not arc.reserve(1, ArcUnits(llm_calls=1))
    assert parent.admit("round")
    clock[0] = 1775.01
    assert not arc.reserve(2, ArcUnits(llm_calls=1))
    assert arc.model_window_open(admission=False)
    clock[0] = 1800
    assert not arc.model_window_open(admission=False)
    assert arc.snapshot()[0] == ArcUnits(llm_calls=1)
    assert arc.reserve(2, ArcUnits(slices=1))
    arc.seal()
    assert not arc.model_window_open(admission=False)


@pytest.mark.parametrize("bad", [False, None, "true", 1])
def test_arc_parent_time_fence_requires_literal_true(bad):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits
    arc = ArcRequestBudget(model_window_guard=lambda **kw: bad)
    assert not arc.reserve(1, ArcUnits(llm_calls=1))
    assert arc.reserve(1, ArcUnits(slices=1))


def test_arc_parent_time_fence_clock_failure_and_generation_claim():
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits
    _, _, _, parent, _, clock = _setup()
    arc = ArcRequestBudget(model_window_guard=parent.optional_model_window_open)
    assert parent.admit("round")
    for value in (-1, float("nan"), float("inf"), None):
        clock[0] = value
        assert not arc.reserve(1, ArcUnits(llm_calls=1))
    clock[0] = 100
    assert parent.claim_report_generation(1) > 0
    assert not arc.reserve(1, ArcUnits(llm_calls=1))


def _callback_resource_records(caplog):
    return [json.loads(row.getMessage().split("SRAF_ARC_DEEP_CALLBACK_RESOURCE=", 1)[1])
            for row in caplog.records
            if row.getMessage().startswith("SRAF_ARC_DEEP_CALLBACK_RESOURCE=")]


@pytest.mark.parametrize("mode", ["shadow", "off"])
def test_arc_deep_callback_resource_counts_actual_planner_and_semantic_boundaries(monkeypatch, caplog, mode):
    from agent.adaptive_retrieval.arc_deep_resource_metrics import _SCOPE
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_RESOURCE_METRICS", mode)
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "off")
    monkeypatch.setenv("SRAF_ARC_REVIEW_DEEP", "off")
    c, scope, ev, _, planner_calls, _ = _setup()
    planner_lengths, semantic_lengths = [], []
    original = c._planner.llm_call
    def planner(prompt, *, system_prompt):
        result = original(prompt, system_prompt=system_prompt)
        planner_lengths.append((len(prompt) + len(system_prompt), len(result)))
        return result
    c._planner.llm_call = planner

    def assessor(target, evidence):
        semantic_lengths.append(len(target.label) + len(evidence.text))
        return True

    result = _run(c, scope, ev, FakeES(_verified_page("A"), _verified_page("B")),
                  assessor=assessor)
    assert result.progress["termination"] == "SUFFICIENT"
    assert planner_calls == [1] and len(semantic_lengths) == 8
    rows = _callback_resource_records(caplog)
    if mode == "off":
        assert rows == []
    else:
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "completed"
        assert row["provider_llm_calls"] is row["prompt_tokens"] is row["completion_tokens"] is None
        p, s = row["callbacks"]["planner"], row["callbacks"]["semantic_witness"]
        assert (p["attempted"], p["returned"], p["raised"]) == (1, 1, 0)
        assert (p["input_chars"], p["output_chars"]) == planner_lengths[0]
        assert (s["attempted"], s["returned"], s["raised"]) == (8, 8, 0)
        assert s["input_chars"] == sum(semantic_lengths) and s["output_chars"] == 0
        assert p["elapsed_ms"] >= 0 and s["elapsed_ms"] >= 0
        assert "PRIVATE" not in json.dumps(row) and "甲軸" not in json.dumps(row, ensure_ascii=False)
    assert _SCOPE.get() is None


@pytest.mark.parametrize("problem", ["semantic_error", "planner_error", "invalid_planner_return"])
def test_arc_deep_callback_resource_distinguishes_returns_from_raised(monkeypatch, caplog, problem):
    from agent.adaptive_retrieval.arc_deep_resource_metrics import _SCOPE
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_RESOURCE_METRICS", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "off")
    monkeypatch.setenv("SRAF_ARC_REVIEW_DEEP", "off")
    c, scope, ev, _, _, _ = _setup()
    def planner(*a, **k):
        if problem == "planner_error":
            raise RuntimeError("PRIVATE_PLANNER")
        return "PRIVATE_INVALID_JSON"
    c._planner.llm_call = planner
    def assessor(*args):
        if problem == "semantic_error":
            raise RuntimeError("PRIVATE_WITNESS")
        return True
    if problem == "semantic_error":
        with pytest.raises(TrustedNroundExecutionError):
            _run(c, scope, ev, FakeES(_verified_page("A")), assessor=assessor)
    else:
        result = _run(c, scope, ev, FakeES(_verified_page("A")), assessor=assessor)
        assert result.progress["termination"] == "PLANNER_FAILED_CLOSED"
    row, = _callback_resource_records(caplog)
    assert row["status"] == "failed"
    p, s = row["callbacks"]["planner"], row["callbacks"]["semantic_witness"]
    if problem == "semantic_error":
        assert (s["attempted"], s["returned"], s["raised"]) == (1, 0, 1)
        assert p["attempted"] == 0
    else:
        assert (s["attempted"], s["returned"], s["raised"]) == (4, 4, 0)
        assert p["attempted"] == 1
        assert p["raised"] == int(problem == "planner_error")
        assert p["returned"] == int(problem == "invalid_planner_return")
    assert "PRIVATE" not in json.dumps(row)
    assert _SCOPE.get() is None


@pytest.mark.parametrize("case", ["default", "flag_off", "pilot", "revoked", "nonempty"])
def test_arc_deep_a2_candidate_expansion_requires_empty_attested_round(monkeypatch, case):
    from agent.adaptive_retrieval.es_pit_adapter import _query
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "off" if case == "flag_off" else "shadow")
    for flag in ("DEEP_FREQUENCY", "REVIEW_DEEP"):
        monkeypatch.setenv("SRAF_ARC_" + flag, "off")
    c, scope, ev, budget, _, _ = _setup()
    prompts, semantic = [], []
    term = "United Nations statement"
    def planner(prompt, *, system_prompt):
        prompts.append(json.loads(prompt.split("\n", 1)[1]))
        if case == "revoked":
            monkeypatch.setenv("SRAF_ARC_BILINGUAL", "off")
        return json.dumps({"action": "search", "reason_code": "COVERAGE_GAP",
                           "optional_terms": [term], "target_aspects": ["外交回應"]})
    c._planner = AdaptiveRetrievalPlanner(planner, _arc_deep_hint_enabled=True,
        _arc_deep_candidate_expansion_enabled=case != "default")
    first = _verified_page("C") if case == "nonempty" else _page([])
    a, b = _verified_page("A"), _verified_page("B")
    second = _page(a["hits"]["hits"] + b["hits"]["hits"])
    es = FakeES(first, second)
    def assessor(*args):
        semantic.append(1)
        return True
    result = _run(c, scope, ev, es, assessor=assessor)
    assert result.progress["termination"] == "SUFFICIENT"
    assert len(prompts) == 1 and len(es.searches) == 2
    assert len(semantic) == (12 if case == "nonempty" else 8)
    advisory = prompts[0]["arc_advisory_read_only"]
    assert ("candidate_expansion_guidance" in advisory) == (case in ("pilot", "revoked"))
    assert [kind for kind, _ in es.calls] == ["open", "search", "close"] * 2
    assert budget.snapshot().remaining_es_calls == 20
    first_body, second_body = (call["body"] for call in es.searches)
    base = _query(scope, optional_terms=(term,), page_size=50)
    actual = second_body["query"]["function_score"]["query"]["bool"]
    baseline = base["query"]["function_score"]["query"]["bool"]
    assert actual["filter"] == baseline["filter"] == first_body["query"]["function_score"]["query"]["bool"]["filter"]
    assert actual["minimum_should_match"] == baseline["minimum_should_match"]
    if case == "pilot":
        # Only the existing synonym OR candidate clause differs.
        from agent.es.reference_text import get_reference_text_field
        expected = {"match": {get_reference_text_field(): {"query": term, "operator": "or"}}}
        changed = [i for i, (left, right) in enumerate(zip(actual["should"], baseline["should"]))
                   if left != right]
        assert len(actual["should"]) == len(baseline["should"]) and len(changed) == 1
        i = changed[0]
        assert actual["should"][i]["bool"]["should"] == baseline["should"][i]["bool"]["should"] + [expected]
    else:
        assert actual == baseline
    assert "candidate_expansion_guidance" not in json.dumps(result.safe_audit())
