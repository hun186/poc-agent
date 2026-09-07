from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import ANY
from requirement_scheduler.execution import ExecutionFailure, ExecutionHandle, FailureCategory, build_execution_manifest
from requirement_scheduler.handoff import RequirementHandoffService, prepared_handoff
from requirement_scheduler.lease import LeaseProof

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
