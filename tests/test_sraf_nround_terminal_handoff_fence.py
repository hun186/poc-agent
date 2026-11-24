"""Read-only transactional ReportJob + N-round terminal checkpoint handoff fence.

Uses real temporary SQLite; no ES, LLM, Word, live Worker, or user API.
"""
from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from api.services.report_job_store import ReportJobStore
from test_sraf_nround_checkpoint import progress
from test_sraf_nround_reportjob_atomic_checkpoint import J, make_claimed_report_job


def _terminal(tmp_path, *, reason="SUFFICIENT"):
    reports, sidecar, job = make_claimed_report_job(tmp_path)
    token = sidecar.claim_for_running_report_job(reports, job)
    assert token
    assert sidecar.record_progress_for_running_report_job(
        reports, job, token, progress(round_number=1, completed=0))
    assert sidecar.record_progress_for_running_report_job(
        reports, job, token, progress(
            phase="TERMINAL", round_number=1, completed=1,
            reason=reason, ready=(reason == "SUFFICIENT"),
        ))
    state = sidecar.get_public(J)
    return reports, sidecar, job, state


def _verify(reports, sidecar, job, state, *, completed=1, revision=None):
    return sidecar.verify_terminal_for_running_report_job(
        reports, job,
        expected_revision=state["revision"] if revision is None else revision,
        completed_rounds=completed,
    )


def test_sufficient_terminal_and_exact_revision_only_no_word_permission(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path)
    assert state["state"] == "RETRIEVAL_STOPPED"
    assert _verify(reports, sidecar, job, state)
    assert _verify(reports, sidecar, job, state)  # read-only, no single use grant
    assert sidecar.get_public(J) == state
    assert state["report_generation_authorized"] is False
    assert reports.get(J).status == "running"
    assert reports.get(J).docx_basename is None


@pytest.mark.parametrize("completed,revision_delta", [
    (0, 0), (2, 0), (1, -1), (1, 1),
])
def test_wrong_completed_round_or_stale_revision_fails_closed(
    tmp_path, completed, revision_delta,
):
    reports, sidecar, job, state = _terminal(tmp_path)
    assert not _verify(reports, sidecar, job, state,
                       completed=completed,
                       revision=state["revision"] + revision_delta)
    assert sidecar.get_public(J) == state


@pytest.mark.parametrize("reason", ["ROUND_BUDGET_EXHAUSTED", "CANCELLED"])
def test_non_sufficient_terminal_is_not_automatically_reportable(tmp_path, reason):
    reports, sidecar, job, state = _terminal(tmp_path, reason=reason)
    assert state["termination"] == reason
    assert not _verify(reports, sidecar, job, state)
    assert state["report_generation_authorized"] is False


def test_cancelled_or_changed_report_job_rejects_even_matching_checkpoint(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path / "changed")
    reports.fail(J, "PRIVATE_FAILURE", "PRIVATE_MESSAGE")
    assert not _verify(reports, sidecar, job, state)
    assert state == sidecar.get_public(J)

    reports2, sidecar2, job2, state2 = _terminal(tmp_path / "owner")
    with sqlite3.connect(reports2.db_path) as con:
        con.execute("UPDATE report_jobs SET owner_id=? WHERE job_id=?",
                    ("OTHER_OWNER", J))
    assert not _verify(reports2, sidecar2, job2, state2)
    assert not _verify(reports2, sidecar2,
                       replace(job2, session_id="PRIVATE_DIFFERENT"), state2)


def test_cross_db_and_preexisting_artifact_never_attest(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path / "canonical")
    wrong_reports = ReportJobStore(tmp_path / "other" / "jobs.sqlite")
    wrong_reports.initialize()
    assert not _verify(wrong_reports, sidecar, job, state)
    with sqlite3.connect(reports.db_path) as con:
        con.execute("UPDATE report_jobs SET docx_basename=? WHERE job_id=?",
                    ("PRIVATE_STALE_DOCX.docx", J))
    assert not _verify(reports, sidecar, job, state)


def test_running_sidecar_and_interrupted_sidecar_never_attest(tmp_path):
    reports, sidecar, job = make_claimed_report_job(tmp_path)
    token = sidecar.claim_for_running_report_job(reports, job)
    assert token
    pending = sidecar.get_public(J)
    assert pending["state"] == "RUNNING"
    assert not _verify(reports, sidecar, job, pending)
    assert sidecar.interrupt_running() == 1
    assert not _verify(reports, sidecar, job, sidecar.get_public(J))


@pytest.mark.parametrize("bad_revision", [True, 0, "3", None])
def test_invalid_revision_type_or_bounds_denied_without_store_change(
    tmp_path, bad_revision,
):
    reports, sidecar, job, state = _terminal(tmp_path)
    assert not sidecar.verify_terminal_for_running_report_job(
        reports, job, expected_revision=bad_revision, completed_rounds=1,
    )
    assert sidecar.get_public(J) == state


def test_schema_drift_and_sqlite_path_failures_redacted(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path / "schema")
    with sqlite3.connect(reports.db_path) as con:
        con.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="nround_terminal_handoff_unverified") as err:
        _verify(reports, sidecar, job, state)
    assert "PRIVATE" not in str(err.value)
    broken_parent = tmp_path / "PRIVATE_NOT_A_DIRECTORY"
    broken_parent.write_text("file")
    fake_file = broken_parent / "PRIVATE_REPORT_DB"
    wrong_reports = ReportJobStore(fake_file)
    wrong_sidecar = NroundCheckpointStore(fake_file)
    with pytest.raises(ValueError, match="nround_terminal_handoff_unverified") as err:
        wrong_sidecar.verify_terminal_for_running_report_job(
            wrong_reports, job, expected_revision=state["revision"],
            completed_rounds=1,
        )
    assert "PRIVATE_" not in str(err.value)


def _begin(reports, sidecar, job, state, *, completed=1, revision=None):
    return sidecar.begin_docx_export_for_terminal_job(
        reports, job, expected_revision=state["revision"] if revision is None else revision,
        completed_rounds=completed,
    )


def test_terminal_export_phase_is_single_use_and_does_not_complete_job(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path)
    assert _begin(reports, sidecar, job, state)
    persisted = reports.get(J)
    assert persisted.status == "running"
    assert persisted.phase == "docx_export"
    assert persisted.phase_updated_at == persisted.updated_at
    assert persisted.docx_basename is None and persisted.turn_id is None
    assert sidecar.get_public(J) == state
    assert not _begin(reports, sidecar, job, state)
    assert not _verify(reports, sidecar, job, state)


def test_concurrent_terminal_export_admission_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    reports, sidecar, job, state = _terminal(tmp_path)
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        # Independent instances share the same canonical SQLite file.
        other = NroundCheckpointStore(sidecar.db_path)
        return _begin(ReportJobStore(reports.db_path), other, job, state)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(claim), pool.submit(claim)
        assert sorted([a.result(timeout=15), b.result(timeout=15)]) == [False, True]
    assert reports.get(J).phase == "docx_export"


@pytest.mark.parametrize("reason", ["ROUND_BUDGET_EXHAUSTED", "CANCELLED"])
def test_partial_terminal_never_enters_export_phase(tmp_path, reason):
    reports, sidecar, job, state = _terminal(tmp_path, reason=reason)
    assert not _begin(reports, sidecar, job, state)
    assert reports.get(J).phase == "agent_execution"


def test_export_admission_rejects_wrong_revision_round_owner_and_artifact(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path)
    assert not _begin(reports, sidecar, job, state, revision=state["revision"] + 1)
    assert not _begin(reports, sidecar, job, state, completed=2)
    assert not _begin(reports, sidecar, replace(job, owner_id="OTHER"), state)
    with sqlite3.connect(reports.db_path) as con:
        con.execute("UPDATE report_jobs SET docx_basename=? WHERE job_id=?",
                    ("PRIVATE_STALE.docx", J))
    assert not _begin(reports, sidecar, job, state)
    assert reports.get(J).phase == "agent_execution"


def test_recovered_job_and_other_database_cannot_enter_export_phase(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path / "canonical")
    wrong = ReportJobStore(tmp_path / "wrong" / "jobs.sqlite")
    wrong.initialize()
    assert not _begin(wrong, sidecar, job, state)
    assert reports.recover_running() == 1
    assert not _begin(reports, sidecar, job, state)
    assert reports.get(J).status == "interrupted"


def test_export_admission_schema_failure_is_redacted_and_rolls_back(tmp_path):
    reports, sidecar, job, state = _terminal(tmp_path)
    # Inject a real SQLite write error after valid authority reads.
    with sqlite3.connect(reports.db_path) as con:
        con.execute("""CREATE TRIGGER deny_export BEFORE UPDATE OF phase ON report_jobs
                       BEGIN SELECT RAISE(ABORT, 'PRIVATE_WRITE_FAILURE'); END""")
    with pytest.raises(ValueError, match="nround_docx_export_admission_unverified") as err:
        _begin(reports, sidecar, job, state)
    assert "PRIVATE" not in str(err.value)
    assert reports.get(J).phase == "agent_execution"
    assert sidecar.get_public(J) == state
