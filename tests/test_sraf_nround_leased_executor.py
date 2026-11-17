"""Offline leased execution integration: real temporary SQLite, fake ES/LLM."""
from __future__ import annotations

import json
import sqlite3

import pytest

from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from api.services.sraf_nround_leased_executor import (
    ClaimedNroundExecutorError, execute_claimed_nround,
)
from test_sraf_nround_es_pit_adapter import FakeES
from test_sraf_nround_persisted_claimed_job_scope import J, claimed_job
from test_sraf_nround_trusted_execution_loop import _setup, _verified_page


def _ready(tmp_path):
    coordinator, constraints, evaluator, _, planner_calls, _ = _setup()
    reports, job = claimed_job(tmp_path, constraints)
    sidecar = NroundCheckpointStore(reports.db_path)
    sidecar.initialize()
    assert sidecar.create(J)
    return coordinator, constraints, evaluator, reports, job, sidecar, planner_calls


def _execute(state, es, *, index_policy=None, branch_policy=None, assessor=None,
             **overrides):
    c, scope, evaluator, reports, job, checkpoint, _ = state
    args = dict(
        report_store=reports, checkpoint_store=checkpoint, claimed_job=job,
        constraints=scope, coordinator=c, evaluator=evaluator,
        authorized_indexes=("news_test",),
        check_owner_index=(
            index_policy if index_policy is not None
            else lambda row, index: row.owner_id == "PRIVATE_OWNER"
            and index == "news_test"
        ),
        check_question_branches=(
            branch_policy if branch_policy is not None
            else lambda row, original, branches:
            original is scope and branches == ("CANONICAL_MAIN",)
        ),
        es_client=es,
        semantic_assessor=assessor if assessor is not None else lambda *_: True,
        query_for_snippet="甲軸乙軸丙軸",
    )
    args.update(overrides)
    return execute_claimed_nround(**args)


def test_two_rounds_durable_owner_bound_and_no_word_authority(tmp_path):
    state = _ready(tmp_path)
    c, _, _, reports, job, checkpoint, planners = state
    es = FakeES(_verified_page("A"), _verified_page("B"))
    receipt = _execute(state, es)
    assert len(receipt.result.rounds) == 2
    assert planners == [1]
    assert len(es.searches) == 2
    status = checkpoint.get_public(J)
    assert status["state"] == "RETRIEVAL_STOPPED"
    assert status["phase"] == "TERMINAL"
    assert status["termination"] == "SUFFICIENT"
    assert status["completed_rounds"] == 2
    assert status["report_generation_authorized"] is False
    assert status["checkpoint_resume_supported"] is False
    assert reports.get(J).status == "running"  # Never complete main Job
    assert receipt.safe_audit()["report_job_completed"] is False
    assert receipt.safe_audit()["word_generated"] is False
    assert receipt.safe_audit()["report_generation_authorized"] is False
    public = json.dumps([status, receipt.safe_audit()], ensure_ascii=False)
    for secret in ("PRIVATE", "news_test", "甲軸", J, job.owner_id):
        assert secret not in public
    assert "PRIVATE" not in repr(receipt)


def test_denied_owner_policy_fails_only_this_lease_before_es(tmp_path):
    state = _ready(tmp_path)
    c, _, _, reports, job, checkpoint, _ = state
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundExecutorError,
                       match="claimed_nround_execution_denied") as exc:
        _execute(state, es, index_policy=lambda *_: 1)
    assert "PRIVATE" not in str(exc.value)
    assert es.calls == []
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    status = checkpoint.get_public(J)
    assert status["state"] == "FAILED"
    assert status["termination"] == "CANCELLED"
    assert not checkpoint.claim_for_running_report_job(reports, job)
    assert reports.get(J).status == "running"


def test_report_job_revoked_during_pit_fails_owned_sidecar_before_semantic(tmp_path):
    state = _ready(tmp_path)
    c, _, _, reports, _, checkpoint, planners = state
    seen = []

    class RevokingES(FakeES):
        def search(self, **kwargs):
            response = super().search(**kwargs)
            reports.fail(J, "PRIVATE_failure", "PRIVATE_details")
            return response

    es = RevokingES(_verified_page("A"))
    with pytest.raises(ClaimedNroundExecutorError,
                       match="claimed_nround_execution_denied"):
        _execute(state, es, assessor=lambda *_: seen.append(1) or True)
    assert len(es.searches) == 1
    assert seen == [] and planners == []
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert reports.get(J).status == "failed"
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_failing_semantic_provider_never_leaves_running_sidecar(tmp_path):
    state = _ready(tmp_path)
    c, _, _, _, _, checkpoint, _ = state
    es = FakeES(_verified_page("A"))

    def fail(*_):
        raise OSError("PRIVATE_MODEL_API_KEY_AND_PATH")

    with pytest.raises(ClaimedNroundExecutorError) as exc:
        _execute(state, es, assessor=fail)
    assert str(exc.value) == "claimed_nround_execution_denied"
    assert len(es.searches) == 1
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_replayed_or_missing_queued_sidecar_never_opens_es(tmp_path):
    state = _ready(tmp_path)
    c, _, _, _, _, checkpoint, _ = state
    assert checkpoint.cancel_queued(J)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundExecutorError):
        _execute(state, es)
    assert es.calls == []
    assert checkpoint.get_public(J)["state"] == "CANCELLED"
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_schema_drift_refuses_lease_and_leaves_queued_sidecar(tmp_path):
    state = _ready(tmp_path)
    c, _, _, reports, _, checkpoint, _ = state
    with sqlite3.connect(reports.db_path) as con:
        con.execute("PRAGMA user_version=999")
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundExecutorError):
        _execute(state, es)
    assert es.calls == []
    assert checkpoint.get_public(J)["state"] == "QUEUED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_terminal_audit_failure_does_not_expose_in_memory_report_ready(
    tmp_path, monkeypatch
):
    state = _ready(tmp_path)
    c, _, _, _, _, checkpoint, _ = state
    original_get = checkpoint.get_public

    def broken_read(job_id):
        raise OSError("PRIVATE_SQLITE_FILE")

    monkeypatch.setattr(checkpoint, "get_public", broken_read)
    es = FakeES(_verified_page("A"), _verified_page("B"))
    with pytest.raises(ClaimedNroundExecutorError) as err:
        _execute(state, es)
    assert str(err.value) == "claimed_nround_execution_denied"
    assert original_get(J)["state"] == "RETRIEVAL_STOPPED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_cross_database_lease_cannot_claim_or_es(tmp_path):
    state = _ready(tmp_path / "real")
    _, _, _, _, _, _, _ = state
    wrong = NroundCheckpointStore(tmp_path / "other" / "different.sqlite3")
    wrong.initialize()
    assert wrong.create(J)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundExecutorError):
        _execute(state, es, checkpoint_store=wrong)
    assert es.calls == []
    assert wrong.get_public(J)["state"] == "QUEUED"
