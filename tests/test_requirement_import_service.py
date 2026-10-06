import json

import pytest
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


def test_preallocated_terminal_replay_returns_before_prepare(monkeypatch):
    class ReplayStore:
        def recover_preallocated_import_result(self, source_id, import_run_id, snapshot_id):
            assert (source_id, import_run_id, snapshot_id) == (
                "source-1", "run-1", "snap-1"
            )
            return {
                "import_run_id": "run-1",
                "snapshot_id": "snap-1",
                "status": "committed",
                "accepted_count": 1,
                "rejected_count": 0,
            }

    service = RequirementImportService(ReplayStore())
    monkeypatch.setattr(
        service,
        "_prepare",
        lambda *_args, **_kwargs: pytest.fail("_prepare must not run on terminal replay"),
    )
    result = service.commit(
        "source-1",
        actor="operator",
        upload_bytes=b"old-payload",
        upload_filename="old.json",
        import_run_id="run-1",
        snapshot_id="snap-1",
        expected_base_snapshot_id="snap-0",
    )
    assert result["snapshot_id"] == "snap-1"


def test_preallocated_first_commit_forwards_ids_and_snapshot_cas(monkeypatch):
    class FirstCommitStore:
        def __init__(self):
            self.kwargs = None

        def recover_preallocated_import_result(self, source_id, import_run_id, snapshot_id):
            return None

        def commit_candidate(self, *args, **kwargs):
            self.kwargs = kwargs
            return {
                "import_run_id": kwargs["import_run_id"],
                "snapshot_id": kwargs["snapshot_id"],
                "status": "committed",
                "accepted_count": 0,
                "rejected_count": 0,
            }

    store = FirstCommitStore()
    service = RequirementImportService(store)
    monkeypatch.setattr(
        service,
        "_prepare",
        lambda *_args, **_kwargs: (
            {"source_id": "source-1"},
            {"profile_version_id": "profile-1"},
            object(),
            object(),
            [],
        ),
    )
    result = service.commit(
        "source-1",
        actor="operator",
        import_run_id="run-fixed",
        snapshot_id="snap-fixed",
        expected_base_snapshot_id="base-snap",
    )
    assert result["snapshot_id"] == "snap-fixed"
    assert store.kwargs == {
        "import_run_id": "run-fixed",
        "snapshot_id": "snap-fixed",
        "expected_base_snapshot_id": "base-snap",
    }
