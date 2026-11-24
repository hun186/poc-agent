"""Isolated claimed ReportJob + durable N-round checkpoint + fake ES execution."""
from __future__ import annotations

import json
import sqlite3

import pytest

from api.services.report_job_store import ReportJobStore
from api.services.sraf_nround_claimed_job_runner import (
    ClaimedNroundJobExecutionError, execute_claimed_nround_job,
)
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from test_sraf_nround_trusted_execution_loop import _setup, _verified_page
from test_sraf_nround_es_pit_adapter import FakeES

J = "rpt_" + "8" * 32


def _case(tmp_path, *, sidecar_registered=True):
    c, scope, ev, budget, planners, _ = _setup()
    db = tmp_path / "PRIVATE_report_jobs.sqlite"
    store = ReportJobStore(db)
    store.initialize()
    created, ok = store.create(
        job_id=J, prompt=scope.question,
        filename="PRIVATE_SINGLE_WORD.docx", session_id="PRIVATE_SID",
        model="SRA-Structured Retrieval Agent", options={},
        metadata={"secret": "PRIVATE"} , idempotency_key="PRIVATE_IDEM",
        request_hash="d" * 64, owner_kind="api_key",
        owner_id="PRIVATE_OWNER",
    )
    assert ok and created.status == "queued"
    claimed = store.claim_next()
    assert claimed and claimed.job_id == J and claimed.status == "running"
    sidecar = NroundCheckpointStore(db)
    sidecar.initialize()
    if sidecar_registered:
        assert sidecar.create(J)
    return c, scope, ev, planners, store, sidecar, claimed


def _run(c, scope, ev, store, sidecar, claimed, es, *,
         owner_index=None, branches=None, semantic=None, **extra):
    return execute_claimed_nround_job(
        report_store=store,
        checkpoint_store=sidecar,
        claimed_job=claimed,
        coordinator=c,
        constraints=scope,
        evaluator=ev,
        authorized_indexes=("news_test",),
        es_client=es,
        semantic_assessor=(
            (lambda *_: True) if semantic is None else semantic
        ),
        check_owner_index=(
            (lambda job, index: job.owner_id == "PRIVATE_OWNER"
             and index == "news_test") if owner_index is None else owner_index
        ),
        check_question_branches=(
            (lambda job, original, queries:
             original is scope and queries == ("CANONICAL_MAIN",))
            if branches is None else branches
        ),
        query_for_snippet="甲軸乙軸丙軸",
        **extra,
    )


def test_two_round_claimed_job_integrates_real_sqlite_scope_lease_and_progress(tmp_path):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    es = FakeES(_verified_page("A"), _verified_page("B"))
    outcome = _run(c, scope, ev, reports, checkpoint, claimed, es)
    assert len(outcome.private_result.rounds) == 2
    assert c.safe_progress()["termination"] == "SUFFICIENT"
    assert planners == [1]
    assert [kind for kind, _ in es.calls] == [
        "open", "search", "close", "open", "search", "close"]
    sidecar = checkpoint.get_public(J)
    assert sidecar["state"] == "RETRIEVAL_STOPPED"
    assert sidecar["round_number"] == 2
    assert sidecar["completed_rounds"] == 2
    assert sidecar["termination"] == "SUFFICIENT"
    assert sidecar["report_generation_authorized"] is False
    assert reports.get(J).status == "running"  # NEVER complete single-round Job
    assert reports.get(J).docx_basename is None
    safe = json.dumps(outcome.safe_audit(), ensure_ascii=False)
    for secret in ("PRIVATE", "甲軸", "news_test", J, "api_key", "Bearer"):
        assert secret not in safe
    assert outcome.safe_audit()["word_download_authorized"] is False
    assert outcome.safe_audit()["report_job"] == "NOT_FINALIZED"
    assert "PRIVATE_DOC" not in repr(outcome)


def test_missing_explicit_sidecar_registration_blocks_all_es(tmp_path):
    c, scope, ev, _, reports, checkpoint, claimed = _case(
        tmp_path, sidecar_registered=False)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError,
                       match="claimed_nround_job_execution_failed"):
        _run(c, scope, ev, reports, checkpoint, claimed, es)
    assert es.calls == []
    assert checkpoint.get_public(J) is None
    assert reports.get(J).status == "running"


def test_cross_file_checkpoint_cannot_claim_other_databases_job(tmp_path):
    c, scope, ev, _, reports, _, claimed = _case(tmp_path / "real")
    wrong = NroundCheckpointStore(tmp_path / "other" / "PRIVATE_other.sqlite")
    wrong.initialize()
    assert wrong.create(J)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, wrong, claimed, es)
    assert es.calls == []
    assert wrong.get_public(J)["state"] == "QUEUED"


def test_denied_owner_policy_only_fails_its_own_lease_before_pit(tmp_path):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, checkpoint, claimed, es,
             owner_index=lambda *_: False)
    assert es.calls == []
    assert planners == []
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert checkpoint.get_public(J)["report_generation_authorized"] is False
    assert reports.get(J).status == "running"


def test_unsupported_multi_query_scope_is_never_silently_truncated(tmp_path):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, checkpoint, claimed, es,
             branches=lambda *_: False)
    assert es.calls == []
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert planners == []


def test_main_job_revoked_during_pit_fails_only_its_sidecar(tmp_path):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    # Another independent sidecar job must not be globally interrupted.
    other = "rpt_" + "9" * 32
    assert checkpoint.create(other)
    other_lease = checkpoint.claim(other)
    assert other_lease
    class RevokingES(FakeES):
        def search(self, **kwargs):
            response = super().search(**kwargs)
            reports.fail(J, "Revoked", "PRIVATE_REASON")
            return response
    es = RevokingES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, checkpoint, claimed, es)
    assert len(es.searches) == 1
    assert c.history == ()
    assert planners == []
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert checkpoint.get_public(other)["state"] == "RUNNING"
    assert reports.get(J).status == "failed"
    assert checkpoint.get_public(J)["report_generation_authorized"] is False


def test_semantic_provider_failure_redacted_and_cleanup_scoped(tmp_path):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    def broken(*_):
        raise RuntimeError("PRIVATE_LLM_PROVIDER_KEY")
    with pytest.raises(ClaimedNroundJobExecutionError) as exc:
        _run(c, scope, ev, reports, checkpoint, claimed,
             FakeES(_verified_page("A")), semantic=broken)
    assert str(exc.value) == "claimed_nround_job_execution_failed"
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    assert planners == []


def test_checkpoint_refused_after_pit_cancels_semantic_and_marks_only_lease_failed(
    tmp_path, monkeypatch,
):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    original = checkpoint.record_progress_for_running_report_job
    seen = []
    def selective_refuse(*args):
        seen.append(args[-1]["es_calls_admitted_this_round"])
        if len(seen) == 2:
            return False
        return original(*args)
    monkeypatch.setattr(
        checkpoint, "record_progress_for_running_report_job", selective_refuse)
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, checkpoint, claimed, es)
    assert seen == [0, 2]
    assert [name for name, _ in es.calls] == ["open", "search", "close"]
    assert planners == []
    assert checkpoint.get_public(J)["state"] == "FAILED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_persisted_job_changed_before_claim_prevents_checkpoint_lease(tmp_path):
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    with sqlite3.connect(reports.db_path) as con:
        con.execute("UPDATE report_jobs SET owner_id='DIFFERENT' WHERE job_id=?", (J,))
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, checkpoint, claimed, es)
    assert checkpoint.get_public(J)["state"] == "QUEUED"
    assert es.calls == []
    assert planners == []
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_no_running_report_job_auto_recovery_or_word_completion(tmp_path):
    c, scope, ev, _, reports, checkpoint, claimed = _case(tmp_path)
    assert reports.recover_running() == 1
    es = FakeES(_verified_page("A"))
    with pytest.raises(ClaimedNroundJobExecutionError):
        _run(c, scope, ev, reports, checkpoint, claimed, es)
    assert es.calls == []
    assert checkpoint.get_public(J)["state"] == "QUEUED"
    assert reports.get(J).status == "interrupted"


@pytest.mark.parametrize("revoked_policy", ["index", "branch"])
def test_terminal_handoff_rechecks_policy_revoked_during_last_semantic(
    tmp_path, revoked_policy,
):
    """Codex P2: final SUFFICIENT cannot hand off private Evidence on stale ACL."""
    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    policy = {"revoked": False}

    def index_access(job, index):
        return (not policy["revoked"] or revoked_policy != "index") and (
            job.owner_id == "PRIVATE_OWNER" and index == "news_test"
        )

    def question_coverage(job, original, branches):
        return (not policy["revoked"] or revoked_policy != "branch") and (
            original is scope and branches == ("CANONICAL_MAIN",)
        )

    def semantic(target, evidence):
        # Revocation happens only AFTER the second PIT was authorized and
        # attested, while the second round's private Evidence is assessed.
        if c.safe_progress()["round"] == 2:
            policy["revoked"] = True
        return True

    es = FakeES(_verified_page("A"), _verified_page("B"))
    with pytest.raises(ClaimedNroundJobExecutionError) as error:
        _run(
            c, scope, ev, reports, checkpoint, claimed, es,
            owner_index=index_access,
            branches=question_coverage,
            semantic=semantic,
        )
    assert str(error.value) == "claimed_nround_job_execution_failed"
    assert policy["revoked"] is True
    assert len(es.searches) == 2
    assert planners == [1]
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    # The stronger per-witness fence rejects during semantic processing
    # BEFORE a SUFFICIENT terminal checkpoint can be written; only this
    # owned lease transitions to FAILED (never Word/download authority).
    public = checkpoint.get_public(J)
    assert public["state"] == "FAILED"
    assert public["termination"] == "CANCELLED"
    assert public["completed_rounds"] == 1
    assert public["report_generation_authorized"] is False
    assert reports.get(J).status == "running"
    assert reports.get(J).docx_basename is None


def test_sufficient_receipt_revalidates_exact_sqlite_terminal_revision(tmp_path, monkeypatch):
    c, scope, ev, _, reports, checkpoint, claimed = _case(tmp_path)
    original = checkpoint.verify_terminal_for_running_report_job
    inspected = []

    def observing(report_store, job, *, expected_revision, completed_rounds):
        inspected.append((expected_revision, completed_rounds, job.job_id))
        return original(
            report_store, job, expected_revision=expected_revision,
            completed_rounds=completed_rounds,
        )

    monkeypatch.setattr(checkpoint, "verify_terminal_for_running_report_job",
                        observing)
    result = _run(
        c, scope, ev, reports, checkpoint, claimed,
        FakeES(_verified_page("A"), _verified_page("B")),
    )
    assert len(inspected) == 1
    assert inspected[0] == (
        result.safe_audit()["checkpoint_revision"], 2, J,
    )
    assert checkpoint.get_public(J)["state"] == "RETRIEVAL_STOPPED"
    assert reports.get(J).docx_basename is None
    assert result.safe_audit()["word_download_authorized"] is False


def test_revoked_report_job_inside_last_atomic_receipt_never_hands_off(
    tmp_path, monkeypatch,
):
    c, scope, ev, _, reports, checkpoint, claimed = _case(tmp_path)
    original = checkpoint.verify_terminal_for_running_report_job

    def revoke_during_terminal_handoff(*args, **kwargs):
        reports.fail(J, "PRIVATE_REVOKED", "PRIVATE_REASON")
        return original(*args, **kwargs)

    monkeypatch.setattr(checkpoint, "verify_terminal_for_running_report_job",
                        revoke_during_terminal_handoff)
    with pytest.raises(ClaimedNroundJobExecutionError) as error:
        _run(
            c, scope, ev, reports, checkpoint, claimed,
            FakeES(_verified_page("A"), _verified_page("B")),
        )
    assert str(error.value) == "claimed_nround_job_execution_failed"
    assert reports.get(J).status == "failed"
    assert reports.get(J).docx_basename is None
    assert checkpoint.get_public(J)["state"] == "RETRIEVAL_STOPPED"
    assert checkpoint.get_public(J)["report_generation_authorized"] is False
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_atomic_terminal_receipt_denied_after_revision_or_storage_failure(
    tmp_path, monkeypatch,
):
    c, scope, ev, _, reports, checkpoint, claimed = _case(tmp_path)
    calls = []

    def refuse(report_store, job, *, expected_revision, completed_rounds):
        calls.append((expected_revision, completed_rounds))
        raise ValueError("PRIVATE_SQLITE_DRIVER_FAILED")

    monkeypatch.setattr(checkpoint, "verify_terminal_for_running_report_job",
                        refuse)
    with pytest.raises(ClaimedNroundJobExecutionError) as error:
        _run(
            c, scope, ev, reports, checkpoint, claimed,
            FakeES(_verified_page("A"), _verified_page("B")),
        )
    assert len(calls) == 1
    assert str(error.value) == "claimed_nround_job_execution_failed"
    assert "PRIVATE" not in str(error.value)
    assert checkpoint.get_public(J)["report_generation_authorized"] is False
    assert reports.get(J).status == "running"
    assert reports.get(J).docx_basename is None
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_claimed_nround_uses_real_shared_report_synthesis_and_word(tmp_path, monkeypatch):
    from io import BytesIO
    from docx import Document
    from agent import report_agent
    from api.services.export_word_service import ExportWordService

    c, scope, ev, planners, reports, checkpoint, claimed = _case(tmp_path)
    es = FakeES(_verified_page("A"), _verified_page("B"))
    outcome = _run(c, scope, ev, reports, checkpoint, claimed, es)
    calls = []
    def model(prompt, **kwargs):
        calls.append((json.loads(prompt), kwargs))
        return "來源1及來源2顯示需要持續觀察。"
    def forbidden(*args, **kwargs):
        raise AssertionError("must not restart retrieval or refinement")
    monkeypatch.setattr(report_agent, "call_llm", model)
    monkeypatch.setattr(report_agent, "run_data_agent", forbidden)
    monkeypatch.setattr(report_agent, "refine_question_for_data_agent", forbidden)
    monkeypatch.setenv("REPORT_EV_FIELD_SELECTOR_MODE", "llm")
    monkeypatch.setenv("SRAF_REPORT_EVIDENCE_REVIEW", "on")
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "120")
    result = outcome.generate_report()
    assert len(calls) == 1 and calls[0][1]["stage"] == "report"
    prompt = calls[0][0]
    assert "agg" not in prompt and prompt["q0"] == scope.question
    assert len(prompt["ev"]) == 4
    assert len(es.searches) == 2 and planners == [1]
    assert len(result["citations"]) == 4
    assert {row["source_id"] for row in result["citations"]} == {
        "PRIVATE_DOC_A", "PRIVATE_DOC_B"}
    assert result["answer"].startswith("⚠️ 多輪分析範圍")
    assert result["evidence_usage"]["citation_labels"]["status"] == "labels_match"
    assert result["evidence_usage"]["nround_progress"]["completed_rounds"] == 2
    data, _ = ExportWordService().build_docx_bytes(result)
    paragraphs = "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    assert "多輪分析範圍" in paragraphs and "來源1" in paragraphs
    assert reports.get(J).status == "running" and reports.get(J).docx_basename is None
    with pytest.raises(ClaimedNroundJobExecutionError):
        outcome.generate_report()
    assert len(calls) == 1


@pytest.mark.parametrize("during", [False, True])
def test_generation_live_policy_revocation_blocks_output(tmp_path, monkeypatch, during):
    from agent import report_agent
    c, scope, ev, _, reports, checkpoint, claimed = _case(tmp_path)
    policy = {"allowed": True}
    outcome = _run(c, scope, ev, reports, checkpoint, claimed,
                   FakeES(_verified_page("A"), _verified_page("B")),
                   owner_index=lambda *_: policy["allowed"])
    calls = []
    def model(*args, **kwargs):
        calls.append(1)
        policy["allowed"] = False
        return "PRIVATE_RESULT"
    monkeypatch.setattr(report_agent, "call_llm", model)
    if not during:
        policy["allowed"] = False
    with pytest.raises(ClaimedNroundJobExecutionError, match="nround_report_generation_failed") as err:
        outcome.generate_report()
    assert "PRIVATE" not in str(err.value)
    assert len(calls) == int(during)
    assert reports.get(J).docx_basename is None


def test_generation_rejects_stale_checkpoint_before_llm(tmp_path, monkeypatch):
    from agent import report_agent
    c, scope, ev, _, reports, checkpoint, claimed = _case(tmp_path)
    outcome = _run(c, scope, ev, reports, checkpoint, claimed,
                   FakeES(_verified_page("A"), _verified_page("B")))
    with sqlite3.connect(reports.db_path) as con:
        con.execute("UPDATE sraf_nround_checkpoints SET revision=revision+1 WHERE job_id=?", (J,))
    calls = []
    monkeypatch.setattr(report_agent, "call_llm", lambda *a, **k: calls.append(1))
    with pytest.raises(ClaimedNroundJobExecutionError):
        outcome.generate_report()
    assert not calls
