from copy import deepcopy
from datetime import timedelta

import pytest

from requirement_scheduler.store import ScheduleStore
from tests.requirement_handoff_stateful_dbapi import (
    NOW, StatefulDatabase, durable_submission, initial_state, lease,
)

ROOT="f"*64


def ready(checkpoint=(None,None,None), version=2, version_id="rv-1"):
    s=initial_state(checkpoint=checkpoint,item_state="reconciling",remote_state="completed",root=ROOT)
    s["item"].update(requirement_version_number=version,requirement_version_id=version_id,
                     path="item-1/report.docx",digest="d"*64,reconciled_at=NOW)
    durable_submission(s); return s


def close(db):
    return ScheduleStore(db,"db").close_completed_item(
        lease=lease(),run_item_id="item-1",output_root_fingerprint=ROOT)


@pytest.mark.parametrize("checkpoint,version,version_id,expected",[
    ((None,None,None),2,"rv-1",("rv-1",2,"item-1")),                 # A
    (("rv-old",1,"old-item"),2,"rv-1",("rv-1",2,"item-1")),      # B
    (("rv-new",3,"new-item"),2,"rv-1",("rv-new",3,"new-item")),  # C
    (("rv-1",2,"item-1"),2,"rv-1",("rv-1",2,"item-1")),          # D1
    (("rv-1",2,"other-item"),2,"rv-1",("rv-1",2,"other-item")),  # D2
])
def test_checkpoint_cases_a_through_d_commit_completed_item(checkpoint,version,version_id,expected):
    db=StatefulDatabase(ready(checkpoint,version,version_id)); close(db)
    assert db.state["item"]["state"] == "completed"
    assert tuple(db.state["checkpoint"]) == expected
    assert db.state["run"]["success_count"] == 1
    assert db.state["audits"][-1]["action"] == "requirement_handoff.item_completed"


def test_case_e_equal_number_different_immutable_identity_rolls_back_everything():
    state=ready(("rv-conflict",2,"old-item")); before=deepcopy(state); db=StatefulDatabase(state)
    with pytest.raises(Exception,match="checkpoint_identity_inconsistent"): close(db)
    for key in ("item","run","checkpoint","audits"): assert db.state[key] == before[key]


@pytest.mark.parametrize("change,error",[
    ({"remote_state":"running"},"artifact_proof_incomplete"),
    ({"path":None},"artifact_proof_incomplete"),({"digest":None},"artifact_proof_incomplete"),
    ({"reconciled_at":None},"artifact_proof_incomplete"),
])
def test_success_requires_complete_remote_and_artifact_proof(change,error):
    state=ready(); state["item"].update(change); db=StatefulDatabase(state)
    with pytest.raises(RuntimeError,match=error): close(db)
    assert db.state["item"]["state"] == "reconciling"


def test_success_requires_frozen_root_and_submission():
    state=ready(); db=StatefulDatabase(state)
    with pytest.raises(RuntimeError,match="output_root_fingerprint_mismatch"):
        ScheduleStore(db,"db").close_completed_item(lease=lease(),run_item_id="item-1",output_root_fingerprint="e"*64)
    state=ready(); state["submission"]=None; db=StatefulDatabase(state)
    with pytest.raises(RuntimeError,match="submission_not_found"): close(db)


@pytest.mark.parametrize("failure",["item_update","after_item_update","checkpoint_update","after_checkpoint_update","run_update","after_run_update","audit_insert","commit"])
def test_terminal_success_failure_boundaries_restore_item_run_checkpoint_and_audit(failure):
    state=ready(); before=deepcopy(state); db=StatefulDatabase(state,fail_at=failure)
    with pytest.raises(RuntimeError,match="injected"): close(db)
    for key in ("item","run","checkpoint","audits"): assert db.state[key] == before[key]


def test_counters_recompute_selected_states_and_exclude_not_selected_items():
    state=ready(); state["other_items"]=[
        {"state":"failed"},{"state":"recovery_required"},{"state":"expired"},
        {"state":"running"},{"state":"failed","selected":False}]
    db=StatefulDatabase(state); close(db)
    assert (db.state["run"]["success_count"],db.state["run"]["failure_count"],db.state["run"]["state"]) == (1,3,"running")
    assert db.state["run"]["completed_at"] is None


def test_counters_derive_terminal_run_and_completed_at_from_authoritative_rows():
    state=ready(); state["other_items"]=[{"state":"failed"},{"state":"expired"}]
    db=StatefulDatabase(state); close(db)
    assert db.state["run"]["state"] == "completed_with_failures"
    assert db.state["run"]["completed_at"] == NOW


@pytest.mark.parametrize("terminal",["failed","recovery_required"])
def test_failed_and_recovery_terminal_methods_are_atomic_and_do_not_advance_checkpoint(terminal):
    state=initial_state(checkpoint=("rv-old",1,"old"),item_state="running",root=ROOT); durable_submission(state)
    db=StatefulDatabase(state)
    ScheduleStore(db,"db").close_failed_or_recovery_item(lease(),"item-1",terminal,"remote_execution_failed")
    assert db.state["item"]["state"] == terminal
    assert db.state["checkpoint"] == ["rv-old",1,"old"]
    assert db.state["audits"][-1]["payload"]["neutral_state"] == terminal


def test_duplicate_terminal_replay_is_idempotent():
    db=StatefulDatabase(ready()); close(db); snapshot=deepcopy(db.state)
    close(db)
    assert db.state["item"] == snapshot["item"] and db.state["checkpoint"] == snapshot["checkpoint"]
