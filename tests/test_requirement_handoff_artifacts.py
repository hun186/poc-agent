from io import BytesIO
from pathlib import Path
import zipfile, pytest
from requirement_scheduler.artifacts import ArtifactPublisher, output_root_fingerprint
from requirement_scheduler.execution import ExecutionHandle
from requirement_scheduler.handoff import RequirementHandoffService
from requirement_scheduler.store import ScheduleStore
from tests.requirement_handoff_stateful_dbapi import StatefulDatabase, durable_submission, initial_state, lease

def docx():
    out=BytesIO()
    with zipfile.ZipFile(out,"w") as z:
        z.writestr("[Content_Types].xml","<Types/>"); z.writestr("word/document.xml","<doc/>")
    return out.getvalue()

def test_atomic_publication_and_identical_reconciliation(tmp_path: Path):
    publisher=ArtifactPublisher(tmp_path); fp=output_root_fingerprint(tmp_path)
    first=publisher.publish_or_reconcile("item","report.docx",docx(),fp)
    assert first==publisher.publish_or_reconcile("item","report.docx",docx(),fp)
    assert not Path(first.relative_path).is_absolute()

def test_root_and_docx_fail_closed(tmp_path: Path):
    publisher=ArtifactPublisher(tmp_path)
    with pytest.raises(Exception,match="fingerprint"): publisher.publish_or_reconcile("item","a.docx",docx(),"0"*64)
    with pytest.raises(Exception,match="artifact_invalid"): publisher.publish_or_reconcile("item","a.docx",b"bad",output_root_fingerprint(tmp_path))

@pytest.mark.parametrize("name,data,error",[
    ("../escape.docx",docx(),"artifact_path_invalid"),
    ("report.txt",docx(),"artifact_path_invalid"),
    ("report.docx",b"not-a-zip","artifact_invalid"),
])
def test_traversal_non_docx_and_malformed_zip_are_rejected(tmp_path,name,data,error):
    with pytest.raises(Exception,match=error):
        ArtifactPublisher(tmp_path).publish_or_reconcile("item",name,data,output_root_fingerprint(tmp_path))

def test_required_docx_entries_and_conflicting_existing_publication(tmp_path):
    out=BytesIO()
    with zipfile.ZipFile(out,"w") as z: z.writestr("[Content_Types].xml","<Types/>")
    with pytest.raises(Exception,match="artifact_invalid"):
        ArtifactPublisher(tmp_path).publish_or_reconcile("item","report.docx",out.getvalue(),output_root_fingerprint(tmp_path))
    publisher=ArtifactPublisher(tmp_path); fp=output_root_fingerprint(tmp_path)
    publisher.publish_or_reconcile("item","report.docx",docx(),fp)
    different=docx()+b"different"
    with pytest.raises(Exception,match="artifact_conflict"):
        publisher.publish_or_reconcile("item","report.docx",different,fp)

def test_integrated_download_publish_sql_evidence_and_terminal_closure(tmp_path):
    root=output_root_fingerprint(tmp_path)
    state=initial_state(item_state="reconciling",remote_state="completed",root=root)
    prepared=durable_submission(state); state["item"]["remote_job_id"]="job-1"
    db=StatefulDatabase(state)
    class Gateway:
        def download_artifact(self,handle): return docx()
    row={"run_item_id":"item-1","prepared":prepared,"handle":ExecutionHandle(prepared.submission_id,"job-1"),"output_root_fingerprint":root}
    RequirementHandoffService(ScheduleStore(db,"db"),Gateway(),tmp_path).reconcile_completed(row,lease())
    item=db.state["item"]
    assert item["state"] == "completed" and item["path"] == "item-1/requirement-requirement-1-v2.docx"
    assert len(item["digest"]) == 64 and not Path(item["path"]).is_absolute()

def test_filesystem_success_then_sql_failure_is_restart_reconcilable(tmp_path):
    root=output_root_fingerprint(tmp_path); publisher=ArtifactPublisher(tmp_path)
    first=publisher.publish_or_reconcile("item","report.docx",docx(),root)
    state=initial_state(item_state="reconciling",remote_state="completed",root=root); durable_submission(state)
    failing=StatefulDatabase(state,fail_at="artifact_update")
    with pytest.raises(RuntimeError,match="injected"):
        ScheduleStore(failing,"db").record_artifact_reconciled(lease=lease(),run_item_id="item-1",relative_path=first.relative_path,sha256=first.sha256,output_root_fingerprint=root)
    assert publisher.publish_or_reconcile("item","report.docx",docx(),root) == first
