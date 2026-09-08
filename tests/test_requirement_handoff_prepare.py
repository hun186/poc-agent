from copy import deepcopy
from datetime import timedelta

import pytest

from requirement_scheduler.store import ScheduleStore
from tests.requirement_handoff_stateful_dbapi import (
    NOW, StatefulDatabase, initial_state, lease,
)

ROOT = "f" * 64


def prepare(db, proof=None, root=ROOT):
    return ScheduleStore(db, "db").prepare_next_handoff(
        lease=proof or lease(), output_root_fingerprint=root,
        now_utc=NOW - timedelta(days=30))


def test_prepare_happy_path_commits_root_submission_item_run_and_safe_audit():
    db=StatefulDatabase(); result=prepare(db); s=db.state
    assert result.submission_id == s["submission"]["submission_id"]
    assert s["run"]["root"] == ROOT and s["run"]["state"] == "running"
    assert s["item"]["state"] == "submitting"
    assert s["audits"][0]["action"] == "requirement_handoff.prepared"
    assert any("UPDLOCK" in sql and "HOLDLOCK" in sql for sql in s["locks"])


def test_database_time_is_authoritative_and_second_read_can_expire_after_locks():
    state=initial_state(deadline=NOW+timedelta(seconds=1))
    state["now_values"]=[NOW,NOW+timedelta(seconds=2)]
    db=StatefulDatabase(state); assert prepare(db) is None
    assert db.state["item"]["state"] == "expired"
    assert db.state["submission"] is None and db.state["run"]["root"] is None
    assert db.state["audits"][0]["payload"]["neutral_state"] == "expired"


@pytest.mark.parametrize("field,value",[(0,"other"),(1,"b"*64),(2,2),(3,NOW-timedelta(seconds=1))])
def test_stale_owner_token_generation_or_expired_lease_cannot_mutate(field,value):
    state=initial_state(); state["lease"][field]=value; before=deepcopy(state)
    db=StatefulDatabase(state)
    with pytest.raises(RuntimeError,match="lease_lost"): prepare(db)
    for key in ("run","item","submission","audits"): assert db.state[key] == before[key]


def test_root_binds_once_same_root_replays_and_changed_root_fails_closed():
    db=StatefulDatabase(); first=prepare(db)
    # Simulate crash/restart returning the durable item to the prepare scan.
    db.state["item"]["state"]="handoff_pending"
    second=prepare(db)
    assert second == first
    db.state["item"]["state"]="handoff_pending"
    before=deepcopy(db.state)
    with pytest.raises(RuntimeError,match="output_root_fingerprint_mismatch"): prepare(db,root="e"*64)
    assert db.state["run"] == before["run"] and db.state["submission"] == before["submission"]


def test_semantic_replay_drift_and_duplicate_race_fail_closed():
    state=initial_state(root=ROOT); db=StatefulDatabase(state); first=prepare(db)
    db.state["item"]["state"]="handoff_pending"
    db.state["submission"]["manifest"] += " "
    with pytest.raises(Exception,match="submission_semantic_drift"): prepare(db)
    assert db.state["item"]["state"] == "handoff_pending"
    assert first.submission_id == db.state["submission"]["submission_id"]


def test_duplicate_submission_race_accepts_only_the_exact_authoritative_winner():
    exact=StatefulDatabase(initial_state(),fail_at="duplicate_exact")
    assert prepare(exact).submission_id == exact.state["submission"]["submission_id"]
    drift=StatefulDatabase(initial_state(),fail_at="duplicate_drift")
    with pytest.raises(Exception,match="submission_semantic_drift"): prepare(drift)
    assert drift.state["submission"] is None and drift.state["run"]["root"] is None


@pytest.mark.parametrize("failure",["after_root_bind","after_submission_insert","after_item_update","audit_insert","commit"])
def test_prepare_failure_boundaries_roll_back_all_domain_state(failure):
    state=initial_state(); before=deepcopy(state); db=StatefulDatabase(state,fail_at=failure)
    with pytest.raises(RuntimeError,match="injected"): prepare(db)
    for key in ("run","item","submission","audits"): assert db.state[key] == before[key]


def test_prepare_sql_transaction_performs_no_http_or_filesystem_io(monkeypatch):
    monkeypatch.setattr("requests.Session.request",lambda *a,**k: pytest.fail("HTTP in SQL TX"))
    monkeypatch.setattr("pathlib.Path.open",lambda *a,**k: pytest.fail("filesystem in SQL TX"))
    assert prepare(StatefulDatabase()) is not None


def test_committed_prepare_audit_payload_is_action_allowlisted_and_secret_free():
    db=StatefulDatabase(); prepare(db)
    encoded=str(db.state["audits"][0]["payload"]).lower()
    for forbidden in ("private requirement prompt","authorization","credential","traceback","odbc","/server","owner"):
        assert forbidden not in encoded
