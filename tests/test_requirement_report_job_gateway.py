from datetime import datetime, timezone
from pathlib import Path
import pytest
from requirement_scheduler.config import RequirementHandoffConfig
from requirement_scheduler.execution import ExecutionFailure, ExecutionState, build_execution_manifest, submission_id
from requirement_scheduler.legacy_report_job_gateway import LegacyReportJobGateway, translate_native_state

@pytest.mark.parametrize("native,neutral",[("queued",ExecutionState.PENDING),("running",ExecutionState.RUNNING),("completed",ExecutionState.COMPLETED),("failed",ExecutionState.FAILED),("interrupted",ExecutionState.RECOVERY_REQUIRED)])
def test_native_states_are_translated_only_at_gateway(native,neutral): assert translate_native_state(native).state==neutral

def test_unknown_native_state_fails_closed():
    with pytest.raises(ExecutionFailure): translate_native_state("framework-private")

class Response:
    status_code=201
    def json(self): return {"job_id":"job-1"}
class Session:
    def __init__(self): self.call=None
    def request(self,*args,**kwargs): self.call=(args,kwargs); return Response()

def test_submit_payload_has_exact_stable_identity_and_no_owner_impersonation(tmp_path):
    config=RequirementHandoffConfig("https://example.test","scheduler",lambda _:"runtime-only",tmp_path)
    session=Session(); gateway=LegacyReportJobGateway(config,session=session)
    source={"schedule_id":"s","schedule_version_id":"sv","batch_run_id":"b","run_item_id":"i","snapshot_id":"sn","requirement_id":"r","requirement_version_id":"rv","requirement_version_number":1,"resolved_prompt":"prompt","resolved_model":"model","deadline_at":datetime(2026,9,8,tzinfo=timezone.utc)}
    manifest=build_execution_manifest(source); sid=submission_id("i")
    assert gateway.submit(manifest,idempotency_key=sid).remote_job_id=="job-1"
    _,kwargs=session.call
    assert kwargs["headers"]["Idempotency-Key"]==sid
    assert kwargs["json"]["session_id"]=="requirement-handoff:"+sid
    assert "owner" not in kwargs["json"] and "runtime-only" not in str(kwargs["json"])
