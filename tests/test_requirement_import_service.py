import json
from data_ingestion.requirements.service import RequirementImportService
from tests.requirement_test_support import MemoryStore, sample_profile, sample_row

def setup_service():
    store=MemoryStore(); p=store.create_profile("p","","admin",enabled=True); v=store.create_profile_version(p["profile_id"],sample_profile(),"op"); store.approve_profile_version(p["profile_id"],1,"admin"); s=store.create_source("s","manual_upload","authoritative_snapshot",{},p["profile_id"],"admin",enabled=True); return store,s,RequirementImportService(store)
def blob(rows): return json.dumps(rows).encode()
def test_preview_is_side_effect_free_and_commit_activates_snapshot():
    store,source,service=setup_service(); preview=service.preview(source["source_id"],upload_bytes=blob([sample_row()]),upload_filename="x.json"); assert preview["counts"]=={"new":1} and not store.snapshots
    result=service.commit(source["source_id"],actor="op",upload_bytes=blob([sample_row()]),upload_filename="x.json"); assert result["status"]=="committed" and len(store.list_snapshot_items(result["snapshot_id"]))==1
def test_anomaly_and_stale_never_switch_snapshot():
    store,source,service=setup_service(); first=service.commit(source["source_id"],actor="op",upload_bytes=blob([sample_row()]),upload_filename="x.json"); active=store.sets[source["source_id"]]["active_snapshot_id"]
    anomaly=service.preview(source["source_id"],upload_bytes=blob([sample_row(**{"CONTENT ":"changed"})]),upload_filename="x.json"); assert anomaly["has_errors"] and anomaly["diagnostics"][0]["code"]=="source_version_anomaly" and store.sets[source["source_id"]]["active_snapshot_id"]==active
    stale=service.preview(source["source_id"],upload_bytes=blob([sample_row(UPDT="2020-01-01")]),upload_filename="x.json"); assert stale["diagnostics"][0]["code"]=="stale_source_version"
