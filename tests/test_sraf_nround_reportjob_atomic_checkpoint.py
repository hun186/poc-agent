"""Atomic ReportJob+N-round sidecar lease/record on one temporary SQLite file."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3

import pytest

from api.services.report_job_store import ReportJobStore
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from test_sraf_nround_checkpoint import progress


J = "rpt_" + "7" * 32


def setup(tmp_path, *, claimed=True):
    path = tmp_path / "PRIVATE-local-jobs.sqlite3"
    reports = ReportJobStore(path)
    reports.initialize()
    row, inserted = reports.create(
        job_id=J,
        prompt="PRIVATE_請分析2023外交經貿問題",
        filename="PRIVATE-report.docx",
        session_id="PRIVATE_session",
        model="SRA-Structured Retrieval Agent",
        options={}, metadata={"secret": "PRIVATE"},
        idempotency_key="PRIVATE_key", request_hash="c" * 64,
        owner_kind="api_key", owner_id="PRIVATE_OWNER",
    )
    assert inserted
    sidecar = NroundCheckpointStore(path)
    sidecar.initialize()
    assert sidecar.create(J)
    if claimed:
        row = reports.claim_next()
        assert row and row.job_id == J and row.status == "running"
    return reports, sidecar, row


def test_atomic_report_job_claim_progress_and_terminal_not_word_authority(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    token = sidecar.claim_for_running_report_job(reports, job)
    assert type(token) is str and len(token) == 43
    assert sidecar.claim_for_running_report_job(reports, job) is None
    assert sidecar.record_progress_for_running_report_job(
        reports, job, token, progress(round_number=1, completed=0))
    assert sidecar.record_progress_for_running_report_job(
        reports, job, token, progress(phase="ASSESSED", completed=1))
    assert sidecar.record_progress_for_running_report_job(
        reports, job, token, progress(
            phase="TERMINAL", completed=1, reason="SUFFICIENT", ready=True))
    public = sidecar.get_public(J)
    assert public["state"] == "RETRIEVAL_STOPPED"
    assert public["completed_rounds"] == 1
    assert public["termination"] == "SUFFICIENT"
    assert public["report_generation_authorized"] is False
    assert public["checkpoint_resume_supported"] is False
    assert not sidecar.record_progress_for_running_report_job(
        reports, job, token, progress())
    assert reports.get(J).status == "running"
    out = json.dumps(public)
    for private in ("PRIVATE", "api_key", "c"*64, token):
        assert private not in out


def test_queued_main_job_never_grants_sidecar_lease(tmp_path):
    reports, sidecar, queued = setup(tmp_path, claimed=False)
    assert sidecar.claim_for_running_report_job(reports, queued) is None
    assert sidecar.get_public(J)["state"] == "QUEUED"
    claimed = reports.claim_next()
    assert claimed
    assert sidecar.claim_for_running_report_job(reports, claimed)
    assert sidecar.get_public(J)["state"] == "RUNNING"


def test_other_database_cannot_claim_sidecar_for_matching_report_job_id(tmp_path):
    reports, sidecar, job = setup(tmp_path / "a")
    other_reports, other_sidecar, other_job = setup(tmp_path / "b")
    assert sidecar.claim_for_running_report_job(other_reports, job) is None
    assert sidecar.claim_for_running_report_job(reports, other_job) is None
    assert sidecar.claim_for_running_report_job(reports, job) is not None
    assert other_sidecar.claim_for_running_report_job(other_reports, other_job) is not None


@pytest.mark.parametrize("field,value", [
    ("owner_id", "OTHER_OWNER"),
    ("owner_kind", "other"),
    ("session_id", "OTHER_SESSION"),
    ("prompt", "OTHER_PROMPT"),
    ("request_hash", "d" * 64),
    ("started_at", "1900-01-01T00:00:00Z"),
    ("status", "interrupted"),
    ("phase", "docx_export"),
])
def test_changed_persisted_identity_or_state_prevents_atomic_claim(tmp_path, field, value):
    reports, sidecar, job = setup(tmp_path)
    with sqlite3.connect(reports.db_path) as con:
        # Fixed test-only SQL columns, not HTTP/LLM-provided identifiers.
        con.execute(f"UPDATE report_jobs SET {field}=? WHERE job_id=?", (value, J))
    assert sidecar.claim_for_running_report_job(reports, job) is None
    assert sidecar.get_public(J)["state"] == "QUEUED"


@pytest.mark.parametrize("field,value", [
    ("owner_id", "FAKE_OWNER"),
    ("request_hash", "f" * 64),
    ("started_at", "1900-01-01T00:00:00Z"),
])
def test_forged_in_memory_claim_rejected_by_canonical_db(tmp_path, field, value):
    reports, sidecar, job = setup(tmp_path)
    assert sidecar.claim_for_running_report_job(
        reports, replace(job, **{field: value})) is None
    assert sidecar.get_public(J)["state"] == "QUEUED"
    assert sidecar.claim_for_running_report_job(reports, job)


def test_one_lease_winner_with_concurrent_worker_claims(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=10) as pool:
        tokens = list(pool.map(
            lambda _: sidecar.claim_for_running_report_job(reports, job),
            range(20),
        ))
    winning = [v for v in tokens if v is not None]
    assert len(winning) == 1
    assert sidecar.get_public(J)["state"] == "RUNNING"
    assert not sidecar.record_progress_for_running_report_job(
        reports, job, "x"*43, progress())
    assert sidecar.record_progress_for_running_report_job(
        reports, job, winning[0], progress())


def test_main_job_terminal_or_recovered_prevents_sidecar_progress(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    lease = sidecar.claim_for_running_report_job(reports, job)
    assert lease
    assert sidecar.record_progress_for_running_report_job(
        reports, job, lease, progress())
    before = sidecar.get_public(J).copy()
    reports.fail(J, "ForcedFailure", "PRIVATE_REASON")
    assert not sidecar.record_progress_for_running_report_job(
        reports, job, lease, progress(phase="ASSESSED", completed=1))
    assert sidecar.get_public(J) == before
    # Startup recovery is fail-closed and never reissues a live lease.
    assert sidecar.interrupt_running() == 1
    assert sidecar.get_public(J)["state"] == "INTERRUPTED"
    assert not sidecar.record_progress_for_running_report_job(
        reports, job, lease, progress())


def test_owner_changed_after_lease_stops_atomic_progress(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    lease = sidecar.claim_for_running_report_job(reports, job)
    with sqlite3.connect(reports.db_path) as con:
        con.execute(
            "UPDATE report_jobs SET owner_id='OTHER_OWNER' WHERE job_id=?", (J,))
    assert not sidecar.record_progress_for_running_report_job(
        reports, job, lease, progress())
    assert sidecar.get_public(J)["revision"] == 1
    assert sidecar.get_public(J)["round_number"] == 0


def test_untracked_query_admission_terminal_reason_is_durable(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    lease = sidecar.claim_for_running_report_job(reports, job)
    assert sidecar.record_progress_for_running_report_job(
        reports, job, lease, progress(
            phase="TERMINAL", completed=0,
            reason="UNTRACKED_QUERY_ADMISSION", ready=False,
        ))
    public = sidecar.get_public(J)
    assert public["state"] == "RETRIEVAL_STOPPED"
    assert public["termination"] == "UNTRACKED_QUERY_ADMISSION"
    assert public["report_generation_authorized"] is False


def test_rollback_on_missing_report_jobs_table_no_sidecar_mutation(tmp_path):
    path = tmp_path / "sidecar-only.sqlite"
    sidecar = NroundCheckpointStore(path)
    sidecar.initialize()
    assert sidecar.create(J)
    trusted_other_store, _, job = setup(tmp_path / "trusted")
    # An uninitialized ReportJobStore pointing at the sidecar-only file
    # cannot magically authorize a claim just because the job object exists.
    uninitialized_report_store = ReportJobStore(path)
    with pytest.raises(ValueError, match="nround_report_job_claim_unverified"):
        sidecar.claim_for_running_report_job(uninitialized_report_store, job)
    assert sidecar.get_public(J)["state"] == "QUEUED"


def test_existing_legacy_unbound_checkpoint_path_remains_isolated(tmp_path):
    reports, sidecar, job = setup(tmp_path)
    # Original sidecar-only path is intentionally preserved for old offline
    # tests; it is not a valid production owner-authenticated admission.
    lease = sidecar.claim(J)
    assert lease
    assert sidecar.claim_for_running_report_job(reports, job) is None
    public = sidecar.get_public(J)
    assert public["state"] == "RUNNING"
    assert public["report_generation_authorized"] is False
