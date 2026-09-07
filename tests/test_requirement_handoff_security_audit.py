import pytest
from requirement_scheduler.store import ScheduleStore

def test_handoff_audit_allowlist_rejects_sensitive_or_arbitrary_values():
    safe={"batch_run_id":"b","run_item_id":"i","workflow_id":"report_v1","fencing_generation":1,"neutral_state":"pending"}
    ScheduleStore._audit_event("requirement_handoff.dispatched","worker","s",payload=safe)
    for key in ("prompt","authorization","secret","raw_http_body","absolute_path","traceback","metadata","langgraph_state"):
        with pytest.raises(ValueError): ScheduleStore._audit_event("requirement_handoff.dispatched","worker","s",payload={**safe,key:"x"})
