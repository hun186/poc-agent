"""Report Job v2 durable phase and truthful, owner-scoped progress (offline)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
import requests

from api.routers.report_jobs import _view
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.services import report_job_worker
from api.services.turn_execution import AgentTurnResult


def new_store(tmp_path):
    store = ReportJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    store.create(
        job_id="rpt_progress", prompt="PRIVATE-PROMPT", filename="report.docx",
        session_id="sid", model="private-model", options={},
        metadata={"source": "user"}, idempotency_key="same-owner-key",
        request_hash="sha", owner_kind="user", owner_id="a",
    )
    return store


def test_v2_claim_progress_completion_and_no_resurrection(tmp_path):
    store = new_store(tmp_path)
    job = store.get("rpt_progress")
    assert job.status == "queued" and job.phase == "queued"
    assert job.phase_updated_at
    assert store.claim_next().phase == "agent_execution"
    assert store.update_phase(job.job_id, "docx_export")
    assert store.get(job.job_id).phase == "docx_export"
    assert store.update_phase(job.job_id, "finalizing")
    assert store.get(job.job_id).phase == "finalizing"
    assert not store.update_phase(job.job_id, "docx_export")
    store.complete(job.job_id, "turn1", "rpt_progress.docx")
    final = store.get(job.job_id)
    assert final.status == "completed" and final.phase == "completed"
    assert final.failure_category is None
    assert not store.update_phase(job.job_id, "finalizing")
    assert store.claim_next() is None
    assert store.get(job.job_id).status == "completed"


def test_failure_category_and_recovery_are_durable(tmp_path):
    store = new_store(tmp_path)
    job = store.claim_next()
    store.fail(job.job_id, "RuntimeError", "Report generation failed", failure_category="timeout")
    assert store.get(job.job_id).failure_category == "timeout"
    assert store.get(job.job_id).phase == "failed"
    assert store.recover_running() == 0
    with pytest.raises(ValueError, match="unsupported_report_failure_category"):
        store.fail(job.job_id, "X", "X", failure_category="SECRET-STRING")


def test_recovery_is_interrupted_not_guessed_as_timeout(tmp_path):
    store = new_store(tmp_path)
    job = store.claim_next()
    assert store.recover_running() == 1
    stopped = store.get(job.job_id)
    assert stopped.phase == "interrupted"
    assert stopped.failure_category is None
    assert not store.update_phase(job.job_id, "docx_export")


def test_v1_canonical_migrates_to_v2_with_legacy_running_unknown(tmp_path):
    path = tmp_path / "older-v1.sqlite3"
    with sqlite3.connect(path) as con:
        ReportJobStore._create_v1(con, "report_jobs")
        ReportJobStore._create_owner_index(con)
        con.execute("PRAGMA user_version=1")
        con.execute(
            "INSERT INTO report_jobs(job_id,status,prompt,session_id,model,options_json,metadata_json,request_hash,owner_kind,owner_id,created_at,updated_at) "
            "VALUES ('legacy','running','SECRET-PROMPT','s','m','{}','{}','h','user','a','now','now')"
        )
    store = ReportJobStore(path)
    store.initialize()
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
    legacy = store.get("legacy")
    assert legacy.status == "running" and legacy.phase == "unobserved"
    assert legacy.phase_updated_at == "now"
    assert legacy.failure_category is None
    assert store.recover_running() == 1
    assert store.get("legacy").phase == "interrupted"
    store.initialize()  # idempotent reopening


@pytest.mark.parametrize("step", ["v2_phase", "v2_backfill", "v2_user_version"])
def test_v1_v2_failure_rolls_back_whole_migration(tmp_path, step):
    path = tmp_path / f"{step}.sqlite3"
    with sqlite3.connect(path) as con:
        ReportJobStore._create_v1(con, "report_jobs")
        ReportJobStore._create_owner_index(con)
        con.execute("PRAGMA user_version=1")
    class Failing(ReportJobStore):
        def _migration_execute(self, con, operation, sql):
            if operation == step:
                raise sqlite3.OperationalError("synthetic migration error")
            return super()._migration_execute(con, operation, sql)
    with pytest.raises(sqlite3.OperationalError):
        Failing(path).initialize()
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "phase" not in [row[1] for row in con.execute("PRAGMA table_info(report_jobs)")]
    ReportJobStore(path).initialize()


def test_status_progress_elapsed_is_observation_not_timeout(tmp_path):
    store = new_store(tmp_path)
    job = store.claim_next()
    with sqlite3.connect(store.db_path) as con:
        con.execute("UPDATE report_jobs SET phase_updated_at=? WHERE job_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(), job.job_id))
    data = _view(store.get(job.job_id))
    assert data["status"] == "running"
    assert data["progress"]["phase"] == "agent_execution"
    assert data["progress"]["elapsed_seconds"] >= 85
    assert data["progress"]["long_running"] is True
    assert data["progress"]["observation"] == "long_running"
    assert data["progress"]["failure_category"] is None
    assert data["error_message"] is None
    assert "prompt" not in data and "request_hash" not in data
    assert "PRIVATE-PROMPT" not in str(data)


def test_legacy_bad_clock_never_invents_duration(tmp_path):
    store = new_store(tmp_path)
    job = store.claim_next()
    with sqlite3.connect(store.db_path) as con:
        con.execute("UPDATE report_jobs SET phase_updated_at='now' WHERE job_id=?", (job.job_id,))
    progress = _view(store.get(job.job_id))["progress"]
    assert progress["elapsed_seconds"] is None
    assert progress["observation"] == "duration_unavailable"
    assert progress["long_running"] is False


def test_actual_worker_reports_agent_docx_and_finalizing(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    job = store.claim_next()
    seen = []

    def fake_turn(**kwargs):
        seen.append(store.get(job.job_id).phase)
        return AgentTurnResult("direct","turn","req","hello",
                               {"answer":"ok", "user_question":"hello"}, {})

    monkeypatch.setattr(report_job_worker, "execute_agent_turn", fake_turn)
    orig = report_job_worker.ExportWordService.build_docx_bytes
    def wrapped_word(self, *args, **kwargs):
        seen.append(store.get(job.job_id).phase)
        return orig(self, *args, **kwargs)
    monkeypatch.setattr(report_job_worker.ExportWordService, "build_docx_bytes", wrapped_word)
    orig_complete = store.complete
    def wrapped_complete(job_id, turn_id, basename):
        seen.append(store.get(job_id).phase)
        return orig_complete(job_id, turn_id, basename)
    monkeypatch.setattr(store, "complete", wrapped_complete)
    ReportJobWorker(store, tmp_path / "reports").execute(job)
    assert seen == ["agent_execution", "docx_export", "finalizing"]
    assert store.get(job.job_id).status == "completed"


def test_worker_real_nested_read_timeout_is_failure_not_waiting(tmp_path, monkeypatch):
    store = new_store(tmp_path)
    job = store.claim_next()
    def fake_turn(**kwargs):
        try:
            raise requests.exceptions.ReadTimeout("PRIVATE-TOKEN")
        except requests.exceptions.ReadTimeout as exc:
            raise RuntimeError("llm_runtime_failure") from exc
    monkeypatch.setattr(report_job_worker, "execute_agent_turn", fake_turn)
    ReportJobWorker(store, tmp_path / "reports").execute(job)
    persisted = store.get(job.job_id)
    assert persisted.status == "failed"
    assert persisted.phase == "failed"
    assert persisted.failure_category == "timeout"
    result = _view(persisted)
    assert result["progress"]["observation"] == "terminal"
    assert result["progress"]["failure_category"] == "timeout"
    assert "PRIVATE-TOKEN" not in str(result)
