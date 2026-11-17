"""Real temporary SQLite ReportJobStore + fake ES N-round owner revalidation."""
from __future__ import annotations

from dataclasses import replace
import json
import sqlite3

import pytest

from api.services.report_job_store import ReportJobStore
from api.services.sraf_nround_claimed_job_scope import (
    PersistedClaimedNroundJobScope, PersistedNroundJobScopeError,
)
from agent.adaptive_retrieval.trusted_execution_loop import (
    TrustedNroundExecutionError, run_trusted_nround,
)
from test_sraf_nround_es_pit_adapter import FakeES
from test_sraf_nround_trusted_execution_loop import _setup, _verified_page


J = "rpt_" + "e" * 32


def claimed_job(tmp_path, scope):
    st = ReportJobStore(tmp_path / "private.sqlite")
    st.initialize()
    row, created = st.create(
        job_id=J, prompt=scope.question, filename="PRIVATE_FILENAME.docx",
        session_id="PRIVATE_SESSION", model="SRA-Structured Retrieval Agent",
        options={}, metadata={"private": "PRIVATE_META"},
        idempotency_key="PRIVATE_KEY", request_hash="b" * 64,
        owner_kind="api_key", owner_id="PRIVATE_OWNER",
    )
    assert created and row.status == "queued"
    claimed = st.claim_next()
    assert claimed is not None and claimed.job_id == J
    assert claimed.status == "running"
    assert claimed.phase == "agent_execution"
    return st, claimed


def scoped(st, job, c, scope, *, access=None, coverage=None):
    owner_calls, branch_calls = [], []

    def index_policy(current, index):
        owner_calls.append((current.owner_id, current.status, current.phase, index))
        return (access(current, index) if access is not None
                else current.owner_id == "PRIVATE_OWNER" and index == "news_test")

    def branch_policy(current, original, branches):
        branch_calls.append((current.owner_id, original is scope, branches))
        return (coverage(current, original, branches) if coverage is not None
                else branches == ("CANONICAL_MAIN",) and original is scope)

    adapter = PersistedClaimedNroundJobScope(
        store=st, claimed_job=job, constraints=scope,
        coordinator=c, authorized_indexes=("news_test",),
        check_owner_index=index_policy,
        check_question_branches=branch_policy,
    )
    return adapter, owner_calls, branch_calls


def execute(c, scope, ev, scope_adapter, es, *, prebuilt_binding=None):
    # Test preflight after the claimed binding was created, not merely
    # constructor validation before the worker has begun.
    binding = (scope_adapter.make_binding() if prebuilt_binding is None
               else prebuilt_binding)
    return run_trusted_nround(
        coordinator=c, constraints=scope, evaluator=ev,
        authorized_indexes=("news_test",),
        es_client=es,
        semantic_assessor=lambda *_: True,
        attest_whole_query_scope=None,
        job_scope_binding=binding,
        query_for_snippet="甲軸乙軸丙軸",
    )


def test_two_round_complete_loop_rechecks_actual_sqlite_job_each_pit(tmp_path):
    c, scope, ev, _, planned, _ = _setup()
    st, job = claimed_job(tmp_path, scope)
    adapter, index_calls, branch_calls = scoped(st, job, c, scope)
    result = execute(
        c, scope, ev, adapter,
        FakeES(_verified_page("A"), _verified_page("B")),
    )
    assert len(result.rounds) == 2
    assert planned == [1]
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert index_calls == [("PRIVATE_OWNER", "running", "agent_execution", "news_test")] * 4
    assert branch_calls == [("PRIVATE_OWNER", True, ("CANONICAL_MAIN",))] * 4
    audit = json.dumps(adapter.safe_audit(), ensure_ascii=False)
    for value in ("PRIVATE_", "news_test", "api_key", "甲軸", J):
        assert value not in audit
    assert adapter.safe_audit()["report_worker"] == "NOT_INTEGRATED"
    assert st.get(J).status == "running"  # isolated runner does not finalize ReportJob


def test_queued_job_cannot_masquerade_as_claimed(tmp_path):
    c, scope, ev, *_ = _setup()
    st, claimed = claimed_job(tmp_path, scope)
    queued = replace(claimed, status="queued", started_at=None)
    with pytest.raises(PersistedNroundJobScopeError, match="claimed_job_not_current"):
        scoped(st, queued, c, scope)
    assert c.safe_progress()["phase"] == "CREATED"


@pytest.mark.parametrize("field,value", [
    ("owner_id", "PRIVATE_WRONG_OWNER"),
    ("owner_kind", "other"),
    ("session_id", "PRIVATE_OTHER_SESSION"),
    ("prompt", "PRIVATE_REPLACED_PROMPT"),
    ("request_hash", "0" * 64),
    ("started_at", "2020-01-01T00:00:00+00:00"),
])
def test_forged_claimed_job_identity_refused_against_store(tmp_path, field, value):
    c, scope, ev, *_ = _setup()
    st, claimed = claimed_job(tmp_path, scope)
    fake = replace(claimed, **{field: value})
    with pytest.raises(PersistedNroundJobScopeError, match="claimed_job_not_current"):
        scoped(st, fake, c, scope)


def test_db_job_becomes_terminal_before_pit_no_es_and_no_semantic(tmp_path):
    c, scope, ev, _, planners, _ = _setup()
    st, job = claimed_job(tmp_path, scope)
    adapter, _, _ = scoped(st, job, c, scope)
    binding = adapter.make_binding()
    st.fail(J, "ForcedStop", "PRIVATE_STOP_REASON")
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        execute(c, scope, ev, adapter, es, prebuilt_binding=binding)
    assert es.calls == []
    assert c.history == ()
    assert planners == []
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_job_recovered_interrupted_before_pit_denied(tmp_path):
    c, scope, ev, *_ = _setup()
    st, job = claimed_job(tmp_path, scope)
    adapter, _, _ = scoped(st, job, c, scope)
    binding = adapter.make_binding()
    assert st.recover_running() == 1
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        execute(c, scope, ev, adapter, es, prebuilt_binding=binding)
    assert es.calls == []
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_owner_or_session_changed_in_db_denied_even_while_running(tmp_path):
    for column, value in [
        ("owner_id", "PRIVATE_CHANGED"),
        ("session_id", "PRIVATE_STOLEN_SESSION"),
        ("request_hash", "f" * 64),
    ]:
        c, scope, ev, *_ = _setup()
        # Each sub-case needs a newly claimed private fixture.
        from pathlib import Path
        case = tmp_path / column
        case.mkdir()
        st, claimed = claimed_job(case, scope)
        adapter, _, _ = scoped(st, claimed, c, scope)
        binding = adapter.make_binding()
        with sqlite3.connect(st.db_path) as conn:
            conn.execute(f"UPDATE report_jobs SET {column}=? WHERE job_id=?", (value, J))
        es = FakeES(_verified_page("A"))
        with pytest.raises(TrustedNroundExecutionError):
            execute(c, scope, ev, adapter, es, prebuilt_binding=binding)
        assert es.calls == []
        assert c.safe_progress()["phase"] == "TERMINAL"


def test_store_revocation_during_es_forbids_semantic_processing(tmp_path):
    c, scope, ev, _, planners, _ = _setup()
    st, claimed = claimed_job(tmp_path, scope)
    adapter, _, _ = scoped(st, claimed, c, scope)
    class RevokingES(FakeES):
        def search(self, **kwargs):
            result = super().search(**kwargs)
            st.fail(J, "Revoked", "PRIVATE_REVOKED")
            return result
    es = RevokingES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        execute(c, scope, ev, adapter, es)
    assert len(es.searches) == 1
    assert c.history == ()
    assert planners == []


def test_policy_denial_or_exception_cannot_grant_access(tmp_path):
    for policy in [
        lambda *_: 1,
        lambda *_: (_ for _ in ()).throw(RuntimeError("PRIVATE_CREDENTIAL")),
    ]:
        c, scope, ev, *_ = _setup()
        loc = tmp_path / str(id(policy))
        loc.mkdir()
        st, claimed = claimed_job(loc, scope)
        adapter, _, _ = scoped(st, claimed, c, scope, access=policy)
        es = FakeES(_verified_page("A"))
        with pytest.raises(TrustedNroundExecutionError) as exc:
            execute(c, scope, ev, adapter, es)
        assert "PRIVATE_" not in str(exc.value)
        assert es.calls == []


def test_branch_policy_refuses_multibranch_original_request(tmp_path):
    c, scope, ev, *_ = _setup()
    st, claimed = claimed_job(tmp_path, scope)
    adapter, _, _ = scoped(
        st, claimed, c, scope, coverage=lambda *_: False)
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        execute(c, scope, ev, adapter, es)
    assert es.calls == []


def test_post_pit_policy_revocation_denies_attestation(tmp_path):
    c, scope, ev, _, _, _ = _setup()
    st, claimed = claimed_job(tmp_path, scope)
    calls = []
    def index_access(job, index):
        calls.append(1)
        return len(calls) == 1
    adapter, _, _ = scoped(st, claimed, c, scope, access=index_access)
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError):
        execute(c, scope, ev, adapter, es)
    assert len(es.searches) == 1
    assert calls == [1, 1]
    assert c.history == ()
