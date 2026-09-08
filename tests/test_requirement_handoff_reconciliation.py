from datetime import datetime, timedelta, timezone
import pytest
from requirement_scheduler.execution import ExecutionHandle, ExecutionState, ExecutionStatus
from requirement_scheduler.reconciliation import RequirementReconciler
from requirement_scheduler.store import ScheduleStore
from tests.requirement_handoff_stateful_dbapi import StatefulDatabase, durable_submission, initial_state, lease

NOW=datetime.now(timezone.utc)
class Store:
    def __init__(self,rows): self.rows=rows; self.events=[]
    def list_unfinished_handoffs(self,**kw): return self.rows
    def record_reconciliation(self,row,status,lease): self.events.append(status.state)
class Gateway:
    def __init__(self,status): self.status=status
    def inspect(self,handle): return self.status
class Service:
    def __init__(self,status): self.gateway=Gateway(status); self.events=[]
    def submit_prepared(self,p,l): self.events.append("submit")
    def reconcile_completed(self,row,l): self.events.append("artifact")

def test_missing_ack_replays_before_polling():
    store=Store([{"remote_job_id":None,"prepared":object()}]); service=Service(None)
    assert RequirementReconciler(store,service).reconcile_batch(object(),20).processed == 1
    assert service.events == ["submit"]

def test_completed_remote_integrates_artifact_after_durable_observation():
    status=ExecutionStatus(ExecutionState.COMPLETED,NOW); row={"remote_job_id":"j","handle":ExecutionHandle("s","j")}
    store=Store([row]); service=Service(status)
    RequirementReconciler(store,service).reconcile_batch(object(),20)
    assert store.events == [ExecutionState.COMPLETED] and service.events == ["artifact"]

def stateful_row(state="pending"):
    data=initial_state(item_state=state,root="f"*64); p=durable_submission(data)
    data["item"]["remote_job_id"]="job-1"
    return data,{"run_item_id":"item-1","remote_job_id":"job-1","prepared":p}

@pytest.mark.parametrize("observed,target",[(ExecutionState.PENDING,"pending"),(ExecutionState.RUNNING,"running"),(ExecutionState.COMPLETED,"reconciling")])
def test_actual_store_reconciliation_is_fenced_and_audited(observed,target):
    data,row=stateful_row(); db=StatefulDatabase(data)
    ScheduleStore(db,"db").record_reconciliation(row,ExecutionStatus(observed,NOW),lease())
    assert db.state["item"]["state"] == target
    assert db.state["audits"][-1]["action"] == "requirement_handoff.reconciled"

@pytest.mark.parametrize("observed,target",[(ExecutionState.FAILED,"failed"),(ExecutionState.RECOVERY_REQUIRED,"recovery_required")])
def test_actual_store_terminal_reconciliation_updates_counters_and_audit(observed,target):
    data,row=stateful_row("running"); db=StatefulDatabase(data)
    ScheduleStore(db,"db").record_reconciliation(row,ExecutionStatus(observed,NOW),lease())
    assert db.state["item"]["state"] == target and db.state["run"]["failure_count"] == 1

def test_stale_predecessor_reconciliation_response_cannot_mutate_sql():
    data,row=stateful_row(); data["lease"][0]="successor"; db=StatefulDatabase(data)
    with pytest.raises(RuntimeError,match="lease_lost"):
        ScheduleStore(db,"db").record_reconciliation(row,ExecutionStatus(ExecutionState.RUNNING,NOW),lease())
    assert db.state["item"]["state"] == "pending" and db.state["audits"] == []
