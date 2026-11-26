"""Owner-bound N-round scope manifest: synthetic only; never contact real ES."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from api.services.report_job_store import ReportJob
from agent.adaptive_retrieval.trusted_execution_loop import (
    TrustedNroundExecutionError, run_trusted_nround,
)
from agent.adaptive_retrieval.worker_scope_binding import (
    WorkerScopeBinding, WorkerScopeBindingError,
)
from agent.adaptive_retrieval.round_query_execution import (
    CompletedSingleQueryRound, FrozenSingleQueryPlan,
    execute_single_frozen_query,
)
from test_sraf_nround_trusted_execution_loop import (
    _setup, _verified_page,
)
from test_sraf_nround_es_pit_adapter import FakeES


def _job(scope, **changes):
    job = ReportJob(
        job_id="rpt_PRIVATE_JOB", status="running",
        prompt=scope.question, filename="private.docx",
        session_id="PRIVATE_SESSION", model="SRA-Structured Retrieval Agent",
        options={}, metadata={}, idempotency_key=None, request_hash="a"*64,
        owner_kind="api_key", owner_id="PRIVATE_OWNER_ID",
    )
    return replace(job, **changes)


def _binding(c, scope, job=None, *, index_policy=None,
             branch_policy=None, authorized_indexes=("news_test",)):
    return WorkerScopeBinding(
        job=_job(scope) if job is None else job,
        coordinator=c,
        constraints=scope,
        authorized_indexes=authorized_indexes,
        check_index_access=(
            (lambda job, index: True) if index_policy is None else index_policy),
        check_single_branch_coverage=(
            (lambda job, scope, branch_codes:
             branch_codes == ("CANONICAL_MAIN",))
            if branch_policy is None else branch_policy),
    )


def _run(c, scope, ev, es, binding):
    return run_trusted_nround(
        coordinator=c,
        constraints=scope,
        evaluator=ev,
        authorized_indexes=("news_test",),
        es_client=es,
        semantic_assessor=lambda *_: True,
        attest_whole_query_scope=None,
        job_scope_binding=binding,
        query_for_snippet="甲軸乙軸丙軸",
    )


def test_running_report_job_owner_and_single_query_scope_are_checked_each_round():
    c, scope, ev, _, planner_calls, _ = _setup()
    index_checks, branch_checks = [], []

    def index_policy(job, index):
        index_checks.append((job.owner_kind, index))
        return job.owner_id == "PRIVATE_OWNER_ID" and index == "news_test"

    def branch_policy(job, constraints, codes):
        branch_checks.append((job.job_id, constraints is scope, codes))
        return codes == ("CANONICAL_MAIN",) and constraints is scope

    binding = _binding(
        c, scope, index_policy=index_policy, branch_policy=branch_policy)
    result = _run(
        c, scope, ev,
        FakeES(_verified_page("A"), _verified_page("B")), binding,
    )
    assert len(result.rounds) == 2
    assert planner_calls == [1]
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    # 2 rounds: 4 PIT pre/post checks + 8 semantic witnesses x 2 checks.
    assert index_checks == [("api_key", "news_test")] * (4 + 8 * 2)
    assert branch_checks == [
        ("rpt_PRIVATE_JOB", True, ("CANONICAL_MAIN",))
    ] * (4 + 8 * 2)
    audit = json.dumps(binding.safe_audit(), ensure_ascii=False)
    for value in ("PRIVATE_", "news_test", "甲軸", "rpt_PRIVATE_JOB"):
        assert value not in audit
    assert binding.safe_audit()["rounds_attested"] == 2
    assert binding.safe_audit()["production_worker"] == "NOT_INTEGRATED"


@pytest.mark.parametrize("bad", [
    {"status": "queued"},
    {"status": "completed"},
    {"owner_kind": None},
    {"owner_id": None},
    {"owner_id": ""},
    {"prompt": "PRIVATE_OTHER_QUESTION"},
    {"session_id": ""},
])
def test_bad_job_owner_status_or_original_question_refused_before_es(bad):
    c, scope, ev, *_ = _setup()
    with pytest.raises(WorkerScopeBindingError, match="invalid_job_scope_binding"):
        _binding(c, scope, job=_job(scope, **bad))
    assert c.safe_progress()["phase"] == "CREATED"


def test_wrong_index_authorization_fails_before_pit_open():
    c, scope, ev, _, planner_calls, _ = _setup()
    binding = _binding(c, scope, index_policy=lambda *_: False)
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, binding)
    assert es.calls == []
    assert c.history == ()
    assert planner_calls == []
    assert c.safe_progress()["termination"] == "CANCELLED"


def test_wrong_owner_is_rejected_by_real_policy_before_es():
    c, scope, ev, *_ = _setup()
    binding = _binding(
        c, scope,
        job=_job(scope, owner_id="PRIVATE_IMPERSONATED_OWNER"),
        index_policy=lambda job, index:
            job.owner_id == "PRIVATE_OWNER_ID",
    )
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, binding)
    assert es.calls == []


def test_question_requiring_multiple_queries_is_refused_before_es():
    c, scope, ev, *_ = _setup()
    # Model/LLM-identified policy: one canonical branch is insufficient for
    # a request requiring disjoint queries. Fail closed, do not just ignore it.
    binding = _binding(
        c, scope, branch_policy=lambda job, constraints, codes: False,
    )
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, binding)
    assert es.calls == []
    assert c.history == ()


def test_owner_permission_revoked_after_pit_before_evidence_verification():
    c, scope, ev, _, planner_calls, _ = _setup()
    calls = []

    def index_policy(job, index):
        calls.append(1)
        return len(calls) == 1

    binding = _binding(c, scope, index_policy=index_policy)
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, binding)
    assert len(es.searches) == 1
    assert calls == [1, 1]
    assert c.history == ()
    assert planner_calls == []
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_invalid_scope_binding_cannot_be_used_with_other_coordinator():
    c, scope, ev, *_ = _setup()
    binding = _binding(c, scope)
    other_c, other_scope, other_ev, *_ = _setup()
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError,
                       match="invalid_trusted_nround_context"):
        _run(other_c, other_scope, other_ev, es, binding)
    assert es.calls == []
    assert other_c.safe_progress()["phase"] == "CREATED"


def test_legacy_lambda_and_manifest_cannot_be_combined_to_bypass_scope():
    c, scope, ev, *_ = _setup()
    binding = _binding(c, scope)
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError,
                       match="invalid_trusted_nround_context"):
        run_trusted_nround(
            coordinator=c, constraints=scope, evaluator=ev,
            authorized_indexes=("news_test",), es_client=es,
            semantic_assessor=lambda *_: True,
            attest_whole_query_scope=lambda *_: True,
            job_scope_binding=binding, query_for_snippet="甲軸乙軸丙軸",
        )
    assert es.calls == []
    assert c.safe_progress()["phase"] == "CREATED"


def test_non_boolean_or_throwing_index_permission_cannot_grant_any_es():
    for checker in (lambda *_: 1,
                    lambda *_: (_ for _ in ()).throw(
                        RuntimeError("PRIVATE_SECRET_ERROR"))):
        c, scope, ev, *_ = _setup()
        binding = _binding(c, scope, index_policy=checker)
        es = FakeES(_verified_page("A"))
        with pytest.raises(TrustedNroundExecutionError) as err:
            _run(c, scope, ev, es, binding)
        assert "PRIVATE_SECRET_ERROR" not in str(err.value)
        assert es.calls == []



def _frozen_plan(c, scope, binding):
    assert c.safe_progress()["phase"] == "SEARCHING"
    return FrozenSingleQueryPlan(
        coordinator=c, constraints=scope,
        authorized_indexes=("news_test",),
        round_number=1, next_round_plan=None,
        _owner_binding_token=binding._binding_token,
    )


def test_forged_receipt_without_actual_execution_or_claim_rejected():
    c, scope, ev, *_ = _setup()
    assert c.start()
    binding = _binding(c, scope)
    plan = _frozen_plan(c, scope, binding)
    binding.preflight(plan)
    # A fabricated "complete" source list, without a PIT open or ES call,
    # cannot be used to establish job authorization or query completeness.
    fake = CompletedSingleQueryRound(
        hits=(), round_number=1, pages_completed=1, unique_sources=0,
    )
    with pytest.raises(WorkerScopeBindingError,
                       match="job_query_receipt_unverified"):
        binding.attest(plan, fake)
    assert binding.safe_audit()["rounds_attested"] == 0


def test_cross_job_owner_scope_cannot_reuse_other_jobs_plan():
    c, scope, ev, *_ = _setup()
    assert c.start()
    first = _binding(c, scope, job=_job(scope, owner_id="OWNER_FIRST"))
    second = _binding(c, scope, job=_job(scope, owner_id="OWNER_SECOND"))
    plan = _frozen_plan(c, scope, first)
    first.preflight(plan)
    with pytest.raises(WorkerScopeBindingError,
                       match="wrong_job_query_manifest"):
        second.preflight(plan)
    assert second.safe_audit()["rounds_attested"] == 0


def test_actual_executed_pit_receipt_is_single_use_for_exact_preflight_plan():
    c, scope, ev, *_ = _setup()
    assert c.start()
    binding = _binding(c, scope)
    plan = _frozen_plan(c, scope, binding)
    binding.preflight(plan)
    receipt = execute_single_frozen_query(
        plan=plan, client=FakeES(_verified_page("A")),
    )
    assert binding.attest(plan, receipt) is True
    assert binding.safe_audit()["rounds_attested"] == 1
    with pytest.raises(WorkerScopeBindingError,
                       match="job_query_receipt_unverified"):
        binding.attest(plan, receipt)
    assert binding.safe_audit()["rounds_attested"] == 1


def test_same_round_different_plan_cannot_attest_other_plans_real_receipt():
    c, scope, ev, *_ = _setup()
    assert c.start()
    binding = _binding(c, scope)
    original = _frozen_plan(c, scope, binding)
    binding.preflight(original)
    receipt = execute_single_frozen_query(
        plan=original, client=FakeES(_verified_page("A")),
    )
    replacement = _frozen_plan(c, scope, binding)
    assert replacement is not original
    assert replacement._execution_token is not original._execution_token
    with pytest.raises(WorkerScopeBindingError,
                       match="job_query_receipt_unverified"):
        binding.attest(replacement, receipt)
    assert binding.attest(original, receipt) is True


def test_unauthorized_index_in_synthetic_receipt_cannot_attest():
    c, scope, ev, *_ = _setup()
    assert c.start()
    binding = _binding(c, scope)
    plan = _frozen_plan(c, scope, binding)
    binding.preflight(plan)
    assert c.claim_single_query_execution(
        1, execution_token=plan._execution_token,
        owner_token=binding._binding_token)
    assert c.admit_es_call(execution_token=plan._execution_token)
    assert c.admit_es_call(execution_token=plan._execution_token)
    forged = CompletedSingleQueryRound(
        hits=({"_index": "UNAUTHORIZED_INDEX", "_id": "x", "_source": {}},),
        round_number=1, pages_completed=1, unique_sources=1,
        _execution_token=plan._execution_token,
    )
    with pytest.raises(WorkerScopeBindingError,
                       match="job_query_receipt_unverified"):
        binding.attest(plan, forged)
    assert binding.safe_audit()["rounds_attested"] == 0



def test_owner_bound_executor_cannot_run_es_before_preflight():
    c, scope, ev, *_ = _setup()
    assert c.start()
    binding = _binding(c, scope)
    plan = _frozen_plan(c, scope, binding)
    es = FakeES(_verified_page("A"))
    from agent.adaptive_retrieval.round_query_execution import (
        RoundQueryPlanError,
    )
    with pytest.raises(RoundQueryPlanError,
                       match="query_plan_already_claimed_or_mixed"):
        execute_single_frozen_query(plan=plan, client=es)
    assert es.calls == []  # no PIT opened before Job policy approval
    assert c.safe_progress()["phase"] == "SEARCHING"
    binding.preflight(plan)
    receipt = execute_single_frozen_query(plan=plan, client=es)
    assert binding.attest(plan, receipt) is True
    assert [kind for kind, _ in es.calls] == ["open", "search", "close"]


def test_late_preflight_after_legacy_es_execution_is_refused():
    c, scope, ev, *_ = _setup()
    assert c.start()
    from agent.adaptive_retrieval.round_query_execution import (
        FrozenSingleQueryPlan,
    )
    unbound_plan = FrozenSingleQueryPlan(
        coordinator=c, constraints=scope,
        authorized_indexes=("news_test",), round_number=1,
        next_round_plan=None,
    )
    assert execute_single_frozen_query(
        plan=unbound_plan, client=FakeES(_verified_page("A")),
    ).query_plan_complete
    binding = _binding(c, scope)
    bound_plan = _frozen_plan(c, scope, binding)
    with pytest.raises(WorkerScopeBindingError,
                       match="job_query_preflight_too_late"):
        binding.preflight(bound_plan)
    assert binding.safe_audit()["rounds_attested"] == 0


def test_direct_legacy_es_admission_after_owner_preflight_is_denied():
    c, scope, ev, *_ = _setup()
    assert c.start()
    binding = _binding(c, scope)
    plan = _frozen_plan(c, scope, binding)
    binding.preflight(plan)
    assert not c.admit_es_call()  # no token => invalid during owner preflight
    assert c.safe_progress()["termination"] == "UNTRACKED_QUERY_ADMISSION"
    es = FakeES(_verified_page("A"))
    from agent.adaptive_retrieval.round_query_execution import (
        RoundQueryPlanError,
    )
    with pytest.raises(RoundQueryPlanError):
        execute_single_frozen_query(plan=plan, client=es)
    assert es.calls == []


def test_another_owners_frozen_claim_cannot_steal_preflight():
    c, scope, ev, *_ = _setup()
    assert c.start()
    authorized = _binding(c, scope)
    another = _binding(
        c, scope, job=_job(scope, owner_id="PRIVATE_OTHER"),
    )
    plan = _frozen_plan(c, scope, authorized)
    authorized.preflight(plan)
    assert not c.claim_single_query_execution(
        round_number=1, execution_token=plan._execution_token,
        owner_token=another._binding_token)
    assert c.safe_progress()["termination"] == "UNTRACKED_QUERY_ADMISSION"


def _frequency_context(*, policy, index_policy=None):
    from agent.adaptive_retrieval.es_page_fence import RoundESPageFence
    c, scope, _, budget, _, _ = _setup()
    binding = WorkerScopeBinding(
        job=_job(scope), constraints=scope, coordinator=c,
        authorized_indexes=("news_test",),
        check_index_access=index_policy or (lambda *_: True),
        check_single_branch_coverage=lambda *_: True,
        check_frequency_scope=policy,
    )
    assert c.start()
    plan = FrozenSingleQueryPlan(c, scope, ("news_test",), 1, None,
                                 _owner_binding_token=binding._binding_token)
    binding.preflight(plan)
    assert c.claim_single_query_execution(1, execution_token=plan._execution_token,
                                          owner_token=binding._binding_token)
    assert c.admit_es_call(execution_token=plan._execution_token)
    fence = RoundESPageFence(coordinator=c, constraints=scope, round_number=1,
                             page_size=2, execution_token=plan._execution_token)
    return c, budget, binding, plan, fence


def test_arc_deep_frequency_admission_is_separate_from_required_page_slots():
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _page
    calls = []
    c, budget, binding, plan, fence = _frequency_context(
        policy=lambda job, constraints: calls.append((job, constraints)) or True)
    arc = ArcRequestBudget()
    with bind_arc_budget((arc, 1)):
        assert not binding.admit_optional_frequency(plan, fence)
        ticket = fence.begin_page()
        assert fence.submit_page(ticket, _page([]))
        assert not binding.admit_optional_frequency(plan, fence)
        assert fence.take_complete_hits() == []
        before = budget.snapshot().remaining_es_calls
        assert binding.admit_optional_frequency(plan, fence)
        assert budget.snapshot().remaining_es_calls == before - 1
        assert c._es_slots_this_round == 2
        assert not binding.admit_optional_frequency(plan, fence)
    assert calls and calls[0][1] is plan.constraints
    assert arc.snapshot()[0] == ArcUnits(es_calls=1)
    assert c.safe_progress()["phase"] == "SEARCHING"
    assert fence.safe_audit()["pages_accepted"] == 1


@pytest.mark.parametrize("case", ["missing_policy", "deny", "policy_exception",
                                  "wrong_plan", "wrong_round_budget", "no_budget",
                                  "revoked_owner", "cancel_during_policy"])
def test_arc_deep_frequency_denial_never_spends_es_or_cancels_main(case):
    from contextlib import nullcontext
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _page
    checks = []
    def index_policy(*_):
        checks.append(1)
        return case != "revoked_owner" or len(checks) == 1
    def policy(*_):
        if case == "policy_exception":
            raise RuntimeError("PRIVATE_POLICY")
        if case == "cancel_during_policy":
            c.cancel()
        return case != "deny"
    c, budget, binding, plan, fence = _frequency_context(
        policy=None if case == "missing_policy" else policy,
        index_policy=index_policy)
    assert fence.submit_page(fence.begin_page(), _page([]))
    fence.take_complete_hits()
    arc = ArcRequestBudget()
    if case == "wrong_plan":
        plan = replace(plan)
    before = budget.snapshot().remaining_es_calls
    with bind_arc_budget(None if case == "no_budget" else
                         (arc, 2 if case == "wrong_round_budget" else 1)):
        assert not binding.admit_optional_frequency(plan, fence)
    assert arc.snapshot()[0] == ArcUnits()
    if case != "cancel_during_policy":
        assert budget.snapshot().remaining_es_calls == before
        assert c.safe_progress()["phase"] == "SEARCHING"
    else:
        assert c.safe_progress()["termination"] == "CANCELLED"


def test_arc_deep_frequency_preserves_next_required_pit_open_and_page_budget():
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _page
    c, budget, binding, plan, fence = _frequency_context(policy=lambda *_: True)
    assert fence.submit_page(fence.begin_page(), _page([]))
    fence.take_complete_hits()
    while budget.snapshot().remaining_es_calls > 2:
        assert budget.admit("es")
    before = budget.snapshot().remaining_es_calls
    arc = ArcRequestBudget()
    with bind_arc_budget((arc, 1)):
        assert not binding.admit_optional_frequency(plan, fence)
    assert before == budget.snapshot().remaining_es_calls == 2
    assert arc.snapshot()[0] == ArcUnits(es_calls=1)
    assert c.safe_progress()["phase"] == "SEARCHING"


def _pit_frequency_response(**changes):
    return dict({"timed_out": False,
                 "_shards": {"total": 2, "successful": 2, "failed": 0},
                 "pit_id": "PRIVATE-PIT-FREQUENCY",
                 "hits": {"total": {"value": 100, "relation": "eq"}, "hits": []},
                 "aggregations": {"group_frequency": {"buckets": {
                     "1": {"doc_count": 50}, "2": {"doc_count": 25}, "3": {"doc_count": 1}}}}},
                **changes)


def _pit_frequency_job(policy):
    c, scope, ev, budget, _, _ = _setup()
    binding = WorkerScopeBinding(
        job=_job(scope), constraints=scope, coordinator=c,
        authorized_indexes=("news_test",),
        check_index_access=lambda *_: True,
        check_single_branch_coverage=lambda *_: True,
        check_frequency_scope=policy,
    )
    assert c.start()
    plan = _frozen_plan(c, scope, binding)
    binding.preflight(plan)
    return c, budget, binding, plan


def _pit_frequency_logs(caplog):
    return [json.loads(row.getMessage().split("SRAF_ARC_DEEP_FREQUENCY=", 1)[1])
            for row in caplog.records if row.getMessage().startswith("SRAF_ARC_DEEP_FREQUENCY=")]


def test_arc_deep_frequency_uses_latest_pit_after_main_pages(monkeypatch, caplog):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _hit, _page
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "news_test")
    c, budget, binding, plan = _pit_frequency_job(lambda *_: True)
    es = FakeES(_page([_hit(1), _hit(2)], pit_id="PRIVATE-PIT-2"),
                _page([_hit(3)], pit_id="PRIVATE-PIT-3"),
                _pit_frequency_response())
    arc = ArcRequestBudget()
    with bind_arc_budget((arc, 1)):
        fetched = execute_single_frozen_query(plan=plan, client=es, page_size=2,
                                               frequency_binding=binding)
    assert [kind for kind, _ in es.calls] == ["open", "search", "search", "search", "close"]
    assert fetched.unique_sources == 3 and fetched.pages_completed == 2
    assert fetched.request_wide_attested is False
    assert binding.attest(plan, fetched)
    body = es.searches[-1]["body"]
    assert body["pit"]["id"] == "PRIVATE-PIT-3"
    assert "search_after" not in body and "sort" not in body and "index" not in es.searches[-1]
    assert body["size"] == 0 and body["_source"] is False and body["timeout"] == "2s"
    assert body["query"]["bool"]["filter"] == es.searches[0]["body"]["query"]["function_score"]["query"]["bool"]["filter"]
    assert es.searches[-1]["allow_partial_search_results"] is False
    assert es.transport_options[-2]["request_timeout"] == 3
    assert es.transport_options[-2]["max_retries"] == 0
    assert es.calls[-1][1]["id"] == "PRIVATE-PIT-FREQUENCY"
    assert arc.snapshot()[0] == ArcUnits(es_calls=1)
    assert budget.snapshot().remaining_es_calls == 20
    assert c._es_slots_this_round == 3
    rows = _pit_frequency_logs(caplog)
    assert rows[0]["status"] == "observed_counts"
    assert rows[0]["eligible_documents"] == 100
    assert rows[0]["groups"][2] == {"group_ordinal": 3, "document_frequency": 1}
    assert "PRIVATE" not in caplog.text and "news_test" not in caplog.text
    assert "甲軸" not in caplog.text


@pytest.mark.parametrize("problem", ["partial", "lower_bound", "bad_buckets", "cluster", "revoked"])
def test_arc_deep_frequency_rejects_counts_but_closes_updated_pit(monkeypatch, caplog, problem):
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _page
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "news_test")
    checks = []
    def policy(*_):
        checks.append(1)
        return problem != "revoked" or len(checks) == 1
    c, _, binding, plan = _pit_frequency_job(policy)
    response = _pit_frequency_response()
    if problem == "partial":
        response["timed_out"] = True
    elif problem == "lower_bound":
        response["hits"]["total"]["relation"] = "gte"
    elif problem == "bad_buckets":
        response["aggregations"] = {}
    elif problem == "cluster":
        response["_clusters"] = {"total": 1}
    es = FakeES(_page([]), response)
    with bind_arc_budget((ArcRequestBudget(), 1)):
        receipt = execute_single_frozen_query(plan=plan, client=es,
                                               frequency_binding=binding)
    assert receipt.query_plan_complete and receipt.pages_completed == 1
    assert es.calls[-1][1]["id"] == "PRIVATE-PIT-FREQUENCY"
    assert len(es.searches) == 2
    logs = _pit_frequency_logs(caplog)
    assert logs[0]["status"] == ("authorization_or_deadline_changed" if problem == "revoked" else "incomplete")
    assert "eligible_documents" not in logs[0]
    assert c.safe_progress()["phase"] == "SEARCHING"


@pytest.mark.parametrize("case", ["off", "no_policy", "denied", "wrong_index", "no_budget"])
def test_arc_deep_frequency_never_calls_unapproved_statistics(monkeypatch, caplog, case):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _page
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "off" if case == "off" else "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "other" if case == "wrong_index" else "news_test")
    c, budget, binding, plan = _pit_frequency_job(None if case == "no_policy" else lambda *_: case != "denied")
    es = FakeES(_page([]))
    arc = ArcRequestBudget()
    with bind_arc_budget(None if case == "no_budget" else (arc, 1)):
        receipt = execute_single_frozen_query(plan=plan, client=es, frequency_binding=binding)
    assert receipt.query_plan_complete
    assert [kind for kind, _ in es.calls] == ["open", "search", "close"]
    assert budget.snapshot().remaining_es_calls == 22
    assert arc.snapshot()[0] == ArcUnits()
    assert c.safe_progress()["phase"] == "SEARCHING"


@pytest.mark.parametrize("case", ["transport", "malformed_pit", "close_failure"])
def test_arc_deep_frequency_cleanup_failure_never_certifies_round(monkeypatch, caplog, case):
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from agent.adaptive_retrieval.round_query_execution import RoundQueryPlanError
    from test_sraf_nround_es_pit_adapter import _page
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "news_test")
    c, _, binding, plan = _pit_frequency_job(lambda *_: True)
    class OptionalFailure(FakeES):
        def search(self, **kw):
            if case == "transport" and self.searches:
                self.calls.append(("search", kw))
                self.searches.append(kw)
                raise RuntimeError("PRIVATE_TRANSPORT")
            return super().search(**kw)
    es = OptionalFailure(_page([]), _pit_frequency_response(
        **({"pit_id": None} if case == "malformed_pit" else {})),
        closing=RuntimeError("PRIVATE_CLOSE") if case == "close_failure" else None)
    with bind_arc_budget((ArcRequestBudget(), 1)):
        if case == "transport":
            assert execute_single_frozen_query(plan=plan, client=es,
                                               frequency_binding=binding).query_plan_complete
            assert _pit_frequency_logs(caplog)[0]["status"] == "unavailable"
        else:
            with pytest.raises(RoundQueryPlanError):
                execute_single_frozen_query(plan=plan, client=es, frequency_binding=binding)
            assert c.safe_progress()["phase"] == "TERMINAL"
            assert not _pit_frequency_logs(caplog)
    assert es.calls[-1][0] == "close"
    assert es.calls[-1][1]["id"] == ("PRIVATE-PIT-FREQUENCY" if case == "close_failure" else "PRIVATE-PIT-1")
    assert "PRIVATE" not in caplog.text


def test_arc_deep_frequency_two_round_loop_uses_shared_budget_without_changing_coverage(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "news_test")
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    c, scope, ev, budget, planner_calls, _ = _setup()
    binding = WorkerScopeBinding(
        job=_job(scope), constraints=scope, coordinator=c,
        authorized_indexes=("news_test",),
        check_index_access=lambda *_: True,
        check_single_branch_coverage=lambda *_: True,
        check_frequency_scope=lambda *_: True,
    )
    es = FakeES(_verified_page("A"), _pit_frequency_response(),
                _verified_page("B"), _pit_frequency_response())
    result = _run(c, scope, ev, es, binding)
    assert len(result.rounds) == 2 and planner_calls == [1]
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert [kind for kind, _ in es.calls] == ["open", "search", "search", "close"] * 2
    assert len(_pit_frequency_logs(caplog)) == 2
    assert all(row["status"] == "observed_counts" for row in _pit_frequency_logs(caplog))
    assert budget.snapshot().remaining_es_calls <= 18
    assert all(row.pages_completed == 1 for row in result.rounds)
    assert all(row.request_wide_attested is False for row in result.rounds)
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize("case", ["ok", "unattested", "other_hits", "revoked", "off"])
def test_arc_deep_rank_receipt_one_shot_and_owner_bound(monkeypatch, case):
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from test_sraf_nround_es_pit_adapter import _page, _hit
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "news_test")
    monkeypatch.setenv("SRAF_ARC_RANK_DEEP", "off" if case == "off" else "shadow")
    checks = []
    def policy(*_):
        checks.append(1)
        return case != "revoked" or len(checks) <= 2
    c, _, binding, plan = _pit_frequency_job(policy)
    es = FakeES(_page([_hit(1)]), _pit_frequency_response())
    receipts = []
    with bind_arc_budget((ArcRequestBudget(), 1)):
        fetched = execute_single_frozen_query(plan=plan, client=es,
            frequency_binding=binding, frequency_receipts=receipts)
    if case == "off":
        assert receipts == []
        return
    assert len(receipts) == 1
    if case != "unattested":
        assert binding.attest(plan, fetched)
    receipt = receipts.pop()
    other = replace(fetched, hits=tuple(dict(h) for h in fetched.hits)) if case == "other_hits" else fetched
    frequency = receipt.consume(plan=plan, binding=binding, fetched=other)
    assert (frequency is not None) == (case == "ok")
    assert receipt.consume(plan=plan, binding=binding, fetched=fetched) is None
    assert "PRIVATE" not in repr(receipt)


def test_arc_deep_rank_used_only_in_first_canonical_build_per_round(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX", "news_test")
    monkeypatch.setenv("SRAF_ARC_RANK_DEEP", "shadow")
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    c, scope, ev, _, planner_calls, _ = _setup()
    binding = WorkerScopeBinding(
        job=_job(scope), constraints=scope, coordinator=c,
        authorized_indexes=("news_test",),
        check_index_access=lambda *_: True,
        check_single_branch_coverage=lambda *_: True,
        check_frequency_scope=lambda *_: True,
    )
    es = FakeES(_verified_page("A"), _pit_frequency_response(),
                _verified_page("B"), _pit_frequency_response())
    result = _run(c, scope, ev, es, binding)
    assert len(result.rounds) == 2 and planner_calls == [1]
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    rows = [json.loads(row.getMessage().split("SRAF_ARC_RANK_SHADOW=",1)[1])
            for row in caplog.records if row.getMessage().startswith("SRAF_ARC_RANK_SHADOW=")]
    assert len(rows) == 2
    assert all(row["scope"] == "same_round_pit_native_df_strict_first_prefix" for row in rows)
    assert all(row["status"] == "no_top_k_pressure" for row in rows)
    assert "PRIVATE" not in caplog.text


def _deep_review_page():
    from test_sraf_shared_evidence_budget import _hit as canonical_hit
    from test_sraf_nround_es_pit_adapter import _page
    docs = []
    for i in range(5):
        doc = canonical_hit(10, "PRIVATE_REVIEW_DOC_" + str(i), inner=False)
        doc["sort"] = [5.0, 100, i]
        doc["_source"]["communication"]["subject"] = "甲軸乙軸丙軸"
        doc["_source"]["multidim_event_json"][0]["evidence_snippets"][0]["text"] = "PRIVATE_WEAK_TEXT"
        docs.append(doc)
    return _page(docs)


@pytest.mark.parametrize("case", ["ok", "off", "no_policy", "deny", "revoked", "wrong_endpoint"])
def test_arc_deep_review_runs_only_with_live_source_and_endpoint_permission(monkeypatch, caplog, case):
    import json
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.evidence_core.arc_semantic_review import summarize_semantic_review
    monkeypatch.setenv("SRAF_ARC_REVIEW_DEEP", "off" if case == "off" else "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://other.invalid/api/chat" if case == "wrong_endpoint" else "https://review.invalid/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "private-model")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE", raising=False)
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_DEEP_FREQUENCY", raising=False)
    c, scope, ev, _, planner_calls, _ = _setup()
    checks, sends = [], []
    def policy(job, constraints, index, ids, endpoint, model, verify):
        assert constraints is scope
        assert index == "news_test"
        assert ids == tuple("PRIVATE_REVIEW_DOC_" + str(i) for i in range(5))
        assert model == "private-model" and verify is True
        checks.append(endpoint)
        return (case != "deny" and endpoint == "https://review.invalid/api/chat"
                and (case != "revoked" or len(checks) == 1))
    binding = WorkerScopeBinding(
        job=_job(scope), constraints=scope, coordinator=c,
        authorized_indexes=("news_test",),
        check_index_access=lambda *_: True,
        check_single_branch_coverage=lambda *_: True,
        check_review_egress=None if case == "no_policy" else policy,
    )
    def review(approved, batch):
        sends.append(approved)
        payload = json.loads(batch.payload)
        assert payload["query"] == scope.question
        assert len(payload["passages"]) == batch.count == 5
        assert all(set(p) == {"ordinal","text"} for p in payload["passages"])
        assert "PRIVATE_REVIEW_DOC_" not in batch.payload
        return summarize_semantic_review(json.dumps([
            {"ordinal":i,"verdict":"unrelated"} for i in range(1,batch.count+1)]),batch)
    monkeypatch.setattr(transport, "_request_review", review)
    result = _run(c, scope, ev, FakeES(_deep_review_page()), binding)
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert len(result.rounds) == 1 and not planner_calls
    assert len(result._report_rows) == 50
    assert len(sends) == int(case in ("ok","revoked"))
    assert len(checks) == (2 if case in ("ok","revoked") else 1 if case in ("deny","wrong_endpoint") else 0)
    assert binding._review_sources is None or case == "off"
    logs = [json.loads(row.getMessage().split("SRAF_ARC_SEMANTIC_REVIEW=",1)[1])
            for row in caplog.records if row.getMessage().startswith("SRAF_ARC_SEMANTIC_REVIEW=")]
    if case == "ok":
        assert logs[0]["status"] == "observed_verdicts"
        assert logs[0]["counts"]["unrelated"] == 5
    elif case == "revoked":
        assert logs == [{"schema":"sraf_arc_semantic_review_shadow_v1","status":"authorization_or_deadline_changed"}]
    elif case in ("deny","wrong_endpoint"):
        assert logs[0]["status"] == "source_or_endpoint_not_authorized"
    else:
        assert not logs
    assert "PRIVATE" not in caplog.text and "review.invalid" not in caplog.text


def test_arc_deep_review_below_pressure_does_not_request_provider(monkeypatch, caplog):
    from agent.es import arc_semantic_review_transport as transport
    monkeypatch.setenv("SRAF_ARC_REVIEW_DEEP","shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW","shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS","approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX","news_test")
    c, scope, ev, _, _, _ = _setup()
    binding = WorkerScopeBinding(
        job=_job(scope), constraints=scope, coordinator=c,
        authorized_indexes=("news_test",),
        check_index_access=lambda *_: True,
        check_single_branch_coverage=lambda *_: True,
        check_review_egress=lambda *_: pytest.fail("unexpected policy call"),
    )
    monkeypatch.setattr(transport,"_request_review",lambda *a: pytest.fail("unexpected model call"))
    result = _run(c,scope,ev,FakeES(_verified_page("A"),_verified_page("B")),binding)
    assert len(result.rounds) == 2
    assert caplog.text.count("below_review_pressure") == 2
    assert binding._review_sources is None
