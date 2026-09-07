from datetime import datetime, timedelta, timezone
from requirement_scheduler.execution import ExecutionHandle, ExecutionState, ExecutionStatus
from requirement_scheduler.reconciliation import RequirementReconciler

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
