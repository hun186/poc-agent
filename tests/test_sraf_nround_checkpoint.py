"""Pure SQLite N-round checkpoint safety tests; no live ES, LLM or Worker."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import sqlite3

import pytest

from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore


J = "rpt_" + "a" * 32

AUDIT = {
    "round": 1, "candidate_sources": 1, "parser_output": 1,
    "validated_rows": 1, "fallback": 0, "verified_in_round": 1,
    "new_verified": 1, "new_sources": 1, "cumulative_verified": 1,
    "cumulative_sources": 1, "complete": True,
    "request_wide_attested": True,
}


def progress(*, phase="SEARCHING", round_number=1, completed=0,
             es_calls=1, reason="NONE", ready=False):
    return {
        "schema": "sraf_nround_coordinator_progress_v1",
        "phase": phase, "round": round_number,
        "completed_rounds": completed,
        "es_calls_admitted_this_round": es_calls,
        "termination": reason,
        "ready_for_external_report_generation": ready,
        "canonical_evidence_history": (copy.deepcopy(AUDIT),) if completed else (),
        "live_es": "NOT_EXECUTED_BY_COORDINATOR",
        "report_job": "NOT_INTEGRATED",
        "checkpoint_resume": "NOT_IMPLEMENTED",
    }


def store(tmp_path):
    st = NroundCheckpointStore(tmp_path / "jobs.sqlite3")
    st.initialize()
    return st


def test_queue_claim_progress_and_terminal_never_authorize_docx(tmp_path):
    st = store(tmp_path)
    assert st.create(J) is True
    assert st.create(J) is False
    token = st.claim(J)
    assert token and token != st.claim(J)
    assert not st.record_progress(J, "forged-token", progress())
    assert st.record_progress(J, token, progress())
    assert st.record_progress(J, token, progress(phase="ASSESSED", completed=1))
    assert st.record_progress(J, token, progress(
        phase="TERMINAL", completed=1, reason="SUFFICIENT", ready=True))
    public = st.get_public(J)
    assert public["state"] == "RETRIEVAL_STOPPED"
    assert public["completed_rounds"] == 1
    assert public["report_generation_authorized"] is False
    assert public["checkpoint_resume_supported"] is False
    assert not st.record_progress(J, token, progress())
    assert st.interrupt_running() == 0
    assert st.claim(J) is None
    assert token not in json.dumps(public)


def test_crash_marks_running_interrupted_and_never_resumes(tmp_path):
    st = store(tmp_path)
    assert st.create(J)
    lease = st.claim(J)
    assert st.record_progress(J, lease, progress())
    restarted = NroundCheckpointStore(st.db_path)
    restarted.initialize()
    assert restarted.interrupt_running() == 1
    assert restarted.interrupt_running() == 0
    assert restarted.get_public(J)["state"] == "INTERRUPTED"
    assert restarted.get_public(J)["phase"] == "SEARCHING"
    assert restarted.claim(J) is None
    assert not restarted.record_progress(J, lease, progress(phase="ASSESSED", completed=1))
    assert restarted.get_public(J)["report_generation_authorized"] is False


def test_exactly_one_concurrent_claim(tmp_path):
    st = store(tmp_path)
    st.create(J)
    with ThreadPoolExecutor(max_workers=10) as pool:
        tokens = list(pool.map(lambda _i: st.claim(J), range(20)))
    assert len([token for token in tokens if token is not None]) == 1
    assert st.get_public(J)["state"] == "RUNNING"


def test_reject_untrusted_and_private_audit_without_storage(tmp_path):
    st = store(tmp_path)
    st.create(J)
    lease = st.claim(J)
    p = progress(phase="ASSESSED", completed=1)
    p["raw_question"] = "VERY_PRIVATE_SOURCE"
    with pytest.raises(ValueError, match="untrusted_nround_progress"):
        st.record_progress(J, lease, p)
    p = progress(phase="ASSESSED", completed=1)
    p["canonical_evidence_history"][0]["source_id"] = "VERY_PRIVATE_SOURCE"
    with pytest.raises(ValueError, match="untrusted_nround_audit"):
        st.record_progress(J, lease, p)
    p = progress()
    p["round"] = True
    with pytest.raises(ValueError, match="untrusted_nround_progress"):
        st.record_progress(J, lease, p)
    p = progress()
    p["termination"] = "PRIVATE EXCEPTION TRACE"
    with pytest.raises(ValueError, match="untrusted_nround_progress"):
        st.record_progress(J, lease, p)
    assert "VERY_PRIVATE_SOURCE" not in st.db_path.read_bytes().decode(
        "utf-8", errors="ignore")
    assert st.get_public(J)["completed_rounds"] == 0


def test_monotonic_progress_rejects_rollbacks_and_round_skips(tmp_path):
    st = store(tmp_path)
    st.create(J)
    lease = st.claim(J)
    assert st.record_progress(J, lease, progress(es_calls=2))
    assert not st.record_progress(J, lease, progress(es_calls=1))
    with pytest.raises(ValueError, match="untrusted_nround_progress"):
        st.record_progress(J, lease, progress(round_number=3))
    assert st.record_progress(J, lease, progress(phase="ASSESSED", completed=1, es_calls=2))
    assert st.record_progress(J, lease, progress(round_number=2, completed=1))
    assert not st.record_progress(J, lease, progress(round_number=1, completed=1))
    assert st.get_public(J)["round_number"] == 2


def test_inconsistent_round_evidence_is_rejected(tmp_path):
    st = store(tmp_path)
    st.create(J)
    lease = st.claim(J)
    p = progress(phase="ASSESSED", completed=1)
    p["canonical_evidence_history"][0]["new_verified"] = 2
    with pytest.raises(ValueError, match="untrusted_nround_audit"):
        st.record_progress(J, lease, p)
    p = progress(phase="ASSESSED", completed=1)
    p["canonical_evidence_history"] = [AUDIT]  # immutable coordinator tuple only
    with pytest.raises(ValueError, match="untrusted_nround_audit"):
        st.record_progress(J, lease, p)


def test_queued_cancel_is_one_way_and_does_not_touch_other_tables(tmp_path):
    st = store(tmp_path)
    with sqlite3.connect(st.db_path) as con:
        con.execute("CREATE TABLE report_jobs (original TEXT)")
        con.execute("INSERT INTO report_jobs VALUES ('unchanged')")
    st.create(J)
    assert st.cancel_queued(J)
    assert not st.cancel_queued(J)
    assert st.claim(J) is None
    assert st.get_public(J)["state"] == "CANCELLED"
    with sqlite3.connect(st.db_path) as con:
        assert con.execute("SELECT original FROM report_jobs").fetchone()[0] == "unchanged"


def test_existing_incompatible_table_is_never_overwritten(tmp_path):
    path = tmp_path / "untrusted.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE sraf_nround_checkpoints (secret TEXT)")
        con.execute("INSERT INTO sraf_nround_checkpoints VALUES ('preserve_me')")
    st = NroundCheckpointStore(path)
    with pytest.raises(RuntimeError, match="incompatible_nround_checkpoint_schema"):
        st.initialize()
    with sqlite3.connect(path) as con:
        assert con.execute(
            "SELECT secret FROM sraf_nround_checkpoints").fetchone()[0] == "preserve_me"


def test_refuse_invalid_ids_without_table_mutation(tmp_path):
    st = store(tmp_path)
    for invalid in ("../../etc/passwd", "rpt_abc", "", "rpt_" + "g" * 32):
        with pytest.raises(ValueError, match="invalid_report_job_id"):
            st.create(invalid)
        assert st.claim(invalid) is None
        assert st.get_public(invalid) is None
