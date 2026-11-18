"""Owner-bound N-round progress read over real temporary SQLite snapshots."""
from __future__ import annotations

import json
import sqlite3

import pytest

from api.services.report_job_store import ReportJobStore
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from api.services.sraf_nround_owned_progress import (
    NroundOwnedProgressError, get_owned_nround_progress,
)
from test_sraf_nround_reportjob_atomic_checkpoint import J, setup
from test_sraf_nround_checkpoint import progress


def _view(report_store, sidecar, *,
          job_id=J, owner_kind="api_key", owner_id="PRIVATE_OWNER"):
    return get_owned_nround_progress(
        report_store=report_store, checkpoint_store=sidecar,
        job_id=job_id, owner_kind=owner_kind, owner_id=owner_id,
    )


def test_only_own_existing_job_returns_count_only_checkpoint(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    state = _view(reports, sidecar)
    assert state["schema"] == "sraf_nround_owned_progress_v1"
    assert state["report_job_status"] == "running"
    assert state["state"] == "QUEUED"
    assert state["completed_rounds"] == 0
    assert state["report_generation_authorized"] is False
    assert state["word_download_authorized"] is False
    assert state["checkpoint_resume_supported"] is False
    for private in ("PRIVATE_", "news_test", J, job.prompt,
                    job.session_id, job.owner_id, job.request_hash):
        assert private not in json.dumps(state, ensure_ascii=False)
    assert reports.get(J).status == "running"


def test_current_progress_and_main_job_state_are_read_in_same_snapshot(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    token = sidecar.claim_for_running_report_job(reports, job)
    assert token
    assert sidecar.record_progress_for_running_report_job(
        reports, job, token, progress(round_number=1, completed=0))
    state = _view(reports, sidecar)
    assert state["state"] == "RUNNING"
    assert state["phase"] == "SEARCHING"
    assert state["round_number"] == 1
    assert state["revision"] == 2
    assert "lease_hash" not in state and token not in json.dumps(state)
    reports.fail(J, "PRIVATE_ERROR", "PRIVATE_MESSAGE")
    # Truthfully report the two distinct persisted lifecycles; do not infer
    # success or mark a still-running sidecar as a completed ReportJob.
    newer = _view(reports, sidecar)
    assert newer["report_job_status"] == "failed"
    assert newer["state"] == "RUNNING"
    assert newer["report_generation_authorized"] is False


@pytest.mark.parametrize("kind,principal", [
    ("api_key", "OTHER_OWNER"),
    ("other", "PRIVATE_OWNER"),
    ("api_key", ""),
    ("api_key", 7),
    ("", "PRIVATE_OWNER"),
])
def test_wrong_or_invalid_principal_is_indistinguishable_from_not_found(
    tmp_path, kind, principal,
):
    reports, sidecar, _ = setup(tmp_path)
    assert _view(reports, sidecar, owner_kind=kind, owner_id=principal) is None


def test_missing_unknown_or_ownerless_job_returns_none(tmp_path):
    reports, sidecar, _ = setup(tmp_path)
    assert _view(reports, sidecar, job_id="rpt_" + "f" * 32) is None
    assert _view(reports, sidecar, job_id="INVALID_JOB") is None
    with sqlite3.connect(reports.db_path) as con:
        con.execute("UPDATE report_jobs SET owner_kind=NULL,owner_id=NULL "
                    "WHERE job_id=?", (J,))
    assert _view(reports, sidecar) is None


def test_other_database_is_never_cross_tenant_authority(tmp_path):
    reports, sidecar, _ = setup(tmp_path / "canonical")
    other_reports, other_sidecar, _ = setup(tmp_path / "separate")
    assert _view(reports, other_sidecar) is None
    assert _view(other_reports, sidecar) is None
    assert _view(reports, sidecar)["report_job_status"] == "running"


def test_queued_job_without_explicit_sidecar_has_no_nround_progress(tmp_path):
    path = tmp_path / "PRIVATE_no_sidecar.sqlite3"
    reports = ReportJobStore(path)
    reports.initialize()
    row, ok = reports.create(
        job_id=J, prompt="PRIVATE_PROMPT", filename="report.docx",
        session_id="PRIVATE_SESSION", model="SRAF", options={},
        metadata={}, idempotency_key="KEY", request_hash="b" * 64,
        owner_kind="api_key", owner_id="PRIVATE_OWNER",
    )
    assert ok
    sidecar = NroundCheckpointStore(path)
    # no initialize(), no implicit table creation
    assert _view(reports, sidecar) is None
    with sqlite3.connect(path) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name='sraf_nround_checkpoints'"
        ).fetchone()[0] == 0


def test_reportjob_schema_or_sidecar_structure_drift_fails_closed(tmp_path):
    reports, sidecar, _ = setup(tmp_path / "bad_version")
    with sqlite3.connect(reports.db_path) as con:
        con.execute("PRAGMA user_version=999")
    with pytest.raises(NroundOwnedProgressError) as err:
        _view(reports, sidecar)
    assert str(err.value) == "nround_owned_progress_unverified"

    reports2, sidecar2, _ = setup(tmp_path / "bad_sidecar")
    with sqlite3.connect(reports2.db_path) as con:
        con.execute("ALTER TABLE sraf_nround_checkpoints ADD COLUMN PRIVATE_TOKEN TEXT")
    with pytest.raises(NroundOwnedProgressError) as err2:
        _view(reports2, sidecar2)
    assert str(err2.value) == "nround_owned_progress_unverified"
    assert "PRIVATE" not in str(err2.value)


def test_missing_private_database_does_not_create_file_or_leak_path(tmp_path):
    db = tmp_path / "PRIVATE_MISSING" / "PRIVATE_database.sqlite"
    reports, sidecar = ReportJobStore(db), NroundCheckpointStore(db)
    with pytest.raises(NroundOwnedProgressError) as err:
        _view(reports, sidecar)
    assert "PRIVATE" not in str(err.value)
    assert not db.exists()
