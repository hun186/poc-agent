from pathlib import Path
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.services.turn_execution import AgentTurnResult
from api.services import report_job_worker

def setup_job(tmp_path):
    s=ReportJobStore(tmp_path/"j.db"); s.initialize(); s.create(job_id="rpt_x",prompt="hello",filename="../../bad.docx",session_id="direct",model="m",options={},metadata={},idempotency_key=None,request_hash="h"); return s
def test_worker_direct_service_and_atomic_docx(tmp_path, monkeypatch):
    store=setup_job(tmp_path); job=store.claim_next(); seen={}
    def execute(**kw):
        seen.update(kw); return AgentTurnResult("direct","turn","req","hello",{"answer":"ok","user_question":"hello"},{})
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",execute)
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert seen["request"] is None and seen["session_id"]=="direct"
    assert store.get(job.job_id).status=="completed" and (tmp_path/"reports/rpt_x.docx").is_file()
    assert not list((tmp_path/"reports").glob("*.tmp"))
def test_failure_leaves_no_artifact(tmp_path, monkeypatch):
    store=setup_job(tmp_path); job=store.claim_next()
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",lambda **_: (_ for _ in ()).throw(RuntimeError("secret /tmp/x")))
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert store.get(job.job_id).status=="failed" and not list((tmp_path/"reports").glob("*"))
