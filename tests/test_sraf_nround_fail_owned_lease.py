"""Bounded failure CAS for one N-round lease; no real Worker/ES or credentials."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from test_sraf_nround_checkpoint import progress

A = "rpt_" + "a" * 32
B = "rpt_" + "b" * 32


def _store(tmp_path):
    store = NroundCheckpointStore(tmp_path / "PRIVATE-nround.sqlite")
    store.initialize()
    assert store.create(A)
    assert store.create(B)
    a, b = store.claim(A), store.claim(B)
    assert a and b and a != b
    return store, a, b


def test_only_current_secret_lease_can_fail_exact_job(tmp_path):
    st, a, b = _store(tmp_path)
    assert not st.fail_owned_lease(A, b)  # another Job token
    assert not st.fail_owned_lease(A, "x" * 43)
    assert st.fail_owned_lease(A, a)
    assert not st.fail_owned_lease(A, a)  # fail is one-way
    one, two = st.get_public(A), st.get_public(B)
    assert one["state"] == "FAILED"
    assert one["phase"] == "TERMINAL"
    assert one["termination"] == "CANCELLED"
    assert one["report_generation_authorized"] is False
    assert two["state"] == "RUNNING"
    assert two["revision"] == 1
    assert st.record_progress(B, b, progress())
    assert not st.record_progress(A, a, progress())
    assert st.claim(A) is None
    public = json.dumps(one)
    for private in ("PRIVATE", a, b, "api_key"):
        assert private not in public


def test_failure_after_sidecar_terminal_cannot_overwrite_success_counts(tmp_path):
    st, a, _ = _store(tmp_path)
    assert st.record_progress(
        A, a, progress(phase="TERMINAL", completed=0,
                       reason="CANCELLED", ready=False))
    before = st.get_public(A)
    assert before["state"] == "RETRIEVAL_STOPPED"
    assert not st.fail_owned_lease(A, a)
    assert st.get_public(A) == before


def test_restart_interruption_cannot_be_falsely_failed_by_stale_worker(tmp_path):
    st, a, b = _store(tmp_path)
    assert st.interrupt_running() == 2
    assert not st.fail_owned_lease(A, a)
    assert not st.fail_owned_lease(B, b)
    assert st.get_public(A)["state"] == "INTERRUPTED"
    assert st.get_public(B)["state"] == "INTERRUPTED"


def test_concurrent_failures_only_one_commits_and_no_resurrection(tmp_path):
    st, a, b = _store(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: st.fail_owned_lease(A, a), range(20)))
    assert sum(results) == 1
    assert st.get_public(A)["state"] == "FAILED"
    assert st.get_public(A)["revision"] == 2
    assert st.get_public(B)["state"] == "RUNNING"
    assert st.record_progress(B, b, progress())


def test_invalid_lease_and_job_id_never_change_checkpoint(tmp_path):
    st, a, b = _store(tmp_path)
    before = st.get_public(A)
    for job_id, secret in [
        ("SECRET_JOB_ID", a),
        (A, ""),
        (A, 123),
        (A, None),
        (A, "x" * 42),
    ]:
        assert not st.fail_owned_lease(job_id, secret)
    assert st.get_public(A) == before


def test_one_job_failure_does_not_clear_other_running_checkpoint(tmp_path):
    st, a, b = _store(tmp_path)
    assert st.record_progress(B, b, progress(round_number=1, es_calls=2))
    rev = st.get_public(B)["revision"]
    assert st.fail_owned_lease(A, a)
    assert st.get_public(B)["revision"] == rev
    assert st.get_public(B)["state"] == "RUNNING"
    assert st.record_progress(
        B, b, progress(phase="ASSESSED", completed=1, es_calls=2))


def test_lease_failure_exception_never_reveals_db_path(tmp_path):
    from pathlib import Path
    parent = tmp_path / "PRIVATE_PARENT_IS_FILE"
    parent.write_text("not a directory")
    st = NroundCheckpointStore(parent / "private.sqlite")
    try:
        st.fail_owned_lease(A, "x" * 43)
    except ValueError as exc:
        assert str(exc) == "nround_lease_failure_unverified"
        assert "PRIVATE_" not in str(exc)
    else:
        raise AssertionError("expected fail-closed error")
