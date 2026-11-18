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
