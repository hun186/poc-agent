from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import ANY
from requirement_scheduler.execution import ExecutionFailure, ExecutionHandle, FailureCategory, build_execution_manifest
from requirement_scheduler.handoff import RequirementHandoffService, prepared_handoff
from requirement_scheduler.lease import LeaseProof
from requirement_scheduler.store import ScheduleStore
from tests.requirement_handoff_stateful_dbapi import (
    StatefulDatabase, durable_submission, initial_state, lease,
)

NOW=datetime(2026,9,7,tzinfo=timezone.utc)
def prepared():
    source={"schedule_id":"s","schedule_version_id":"sv","batch_run_id":"b","run_item_id":"i","snapshot_id":"sn","requirement_id":"r","requirement_version_id":"rv","requirement_version_number":1,"resolved_prompt":"private","resolved_model":"m","deadline_at":NOW}
    return prepared_handoff("i",build_execution_manifest(source))

class Store:
    def __init__(self): self.calls=[]
    def acknowledge_submission(self,*a,**k): self.calls.append(("ack",a,k))
    def mark_reconciling(self,*a): self.calls.append(("reconcile",a))
class Gateway:
    def __init__(self,error=None): self.error=error; self.keys=[]
    def submit(self,manifest,*,idempotency_key):
        self.keys.append(idempotency_key)
        if self.error: raise self.error
        return ExecutionHandle(idempotency_key,"job")

def test_submit_uses_stable_key_then_acknowledges_after_http():
    store=Store(); gateway=Gateway(); p=prepared(); lease=LeaseProof("requirement-report-v1","o","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",1,NOW)
    RequirementHandoffService(store,gateway,Path("/server")).submit_prepared(p,lease)
    assert gateway.keys == [p.submission_id]
    assert store.calls[0][0] == "ack"

def test_ambiguous_submit_marks_same_submission_reconciling():
    store=Store(); gateway=Gateway(ExecutionFailure(FailureCategory.TRANSPORT_AMBIGUOUS,"remote_transport_ambiguous")); p=prepared()
    with pytest.raises(ExecutionFailure): RequirementHandoffService(store,gateway,Path("/server")).submit_prepared(p,LeaseProof("requirement-report-v1","o","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",1,NOW))
    assert store.calls == [("reconcile",("i",ANY,"transport_ambiguous"))]


def ack_db(*, state="submitting", remote_job_id=None):
    data=initial_state(item_state=state,root="f"*64)
    prepared=durable_submission(data); data["item"]["remote_job_id"]=remote_job_id
    return StatefulDatabase(data),prepared


def test_acknowledge_commits_remote_identity_item_run_and_audit_atomically():
    db,p=ack_db(); ScheduleStore(db,"db").acknowledge_submission(
        p,ExecutionHandle(p.submission_id,"job-1"),lease())
    assert db.state["item"]["state"] == "pending"
    assert db.state["item"]["remote_job_id"] == "job-1"
    assert db.state["run"]["handed_off_at"] is not None
    assert db.state["audits"][-1]["action"] == "requirement_handoff.dispatched"


@pytest.mark.parametrize("field,value",[(0,"successor"),(1,"b"*64),(2,2),(3,NOW)])
def test_acknowledge_rejects_stale_or_expired_lease_without_mutation(field,value):
    db,p=ack_db(); db.state["lease"][field]=value
    with pytest.raises(RuntimeError,match="lease_lost"):
        ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle(p.submission_id,"job-1"),lease())
    assert db.state["item"]["remote_job_id"] is None and db.state["audits"] == []


def test_acknowledge_exact_replay_and_conflicting_remote_identity():
    db,p=ack_db(state="reconciling",remote_job_id="job-1")
    ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle(p.submission_id,"job-1"),lease())
    assert db.state["item"]["remote_job_id"] == "job-1"
    db,p=ack_db(remote_job_id="other")
    with pytest.raises(RuntimeError,match="remote_job_identity_conflict"):
        ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle(p.submission_id,"job-1"),lease())


def test_acknowledge_rejects_wrong_state_id_and_semantic_drift():
    db,p=ack_db(state="running")
    with pytest.raises(RuntimeError,match="handoff_state_conflict"):
        ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle(p.submission_id,"job-1"),lease())
    db,p=ack_db()
    with pytest.raises(RuntimeError,match="submission_semantic_drift"):
        ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle("wrong","job-1"),lease())
    db,p=ack_db(); db.state["submission"]["manifest"] += " "
    with pytest.raises(Exception,match="submission_semantic_drift"):
        ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle(p.submission_id,"job-1"),lease())


@pytest.mark.parametrize("failure",["remote_update","after_remote_update","run_evidence","audit_insert","commit"])
def test_acknowledge_failure_boundaries_roll_back_everything(failure):
    db,p=ack_db(); db.fail_at=failure
    with pytest.raises(RuntimeError,match="injected"):
        ScheduleStore(db,"db").acknowledge_submission(p,ExecutionHandle(p.submission_id,"job-1"),lease())
    assert db.state["item"]["state"] == "submitting"
    assert db.state["item"]["remote_job_id"] is None
    assert db.state["audits"] == []
