from datetime import datetime, timezone
import pytest
from requirement_scheduler.execution import build_execution_manifest, semantic_fingerprint, submission_id
from requirement_scheduler.handoff import checkpoint_outcome, prepared_handoff, verify_prepared

def source(**changes):
    value={"schedule_id":"s","schedule_version_id":"sv","batch_run_id":"b","run_item_id":"i","snapshot_id":"snap","requirement_id":"req/1","requirement_version_id":"rv","requirement_version_number":2,"resolved_prompt":"內容","resolved_model":"m","deadline_at":datetime(2026,1,1,tzinfo=timezone.utc)}
    value.update(changes); return value

def test_manifest_is_canonical_and_stable():
    manifest=build_execution_manifest(source()); prepared=prepared_handoff("i",manifest)
    assert prepared.submission_id==submission_id("i") and len(prepared.submission_id)==54
    assert semantic_fingerprint(manifest)==prepared.semantic_fingerprint
    assert '"legacy_session_id":"requirement-handoff:rhsub_' in prepared.semantic_manifest_json
    verify_prepared(prepared,prepared)

def test_checkpoint_matrix_separates_success_from_advance():
    assert checkpoint_outcome(None,None,2,"rv")=="advance"
    assert checkpoint_outcome(1,"old",2,"rv")=="advance"
    assert checkpoint_outcome(3,"new",2,"rv")=="noop"
    assert checkpoint_outcome(2,"rv",2,"rv")=="noop"
    with pytest.raises(Exception,match="checkpoint_identity_inconsistent"): checkpoint_outcome(2,"other",2,"rv")
