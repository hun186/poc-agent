from pathlib import Path
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.services.turn_execution import AgentTurnResult
from api.services import report_job_worker
from agent.external_capabilities import (
    mark_requirement_e2e_model, requirement_acceptance_active,
)

def setup_job(tmp_path, model="m"):
    s=ReportJobStore(tmp_path/"j.db"); s.initialize(); s.create(job_id="rpt_x",prompt="hello",filename="../../bad.docx",session_id="direct",model=model,options={},metadata={},idempotency_key=None,request_hash="h"); return s
def test_worker_direct_service_and_atomic_docx(tmp_path, monkeypatch):
    store=setup_job(tmp_path); job=store.claim_next(); seen={}
    def execute(**kw):
        seen.update(kw); seen["acceptance_active"] = requirement_acceptance_active()
        return AgentTurnResult("direct","turn","req","hello",{"answer":"ok","user_question":"hello"},{})
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",execute)
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert seen["request"] is None and seen["session_id"]=="direct"
    assert seen["acceptance_active"] is False and seen["payload"].model == "m"
    assert store.get(job.job_id).status=="completed" and (tmp_path/"reports/rpt_x.docx").is_file()
    assert not list((tmp_path/"reports").glob("*.tmp"))
def test_worker_scopes_only_marked_requirement_e2e_job(tmp_path, monkeypatch):
    store=setup_job(tmp_path, mark_requirement_e2e_model("m")); job=store.claim_next(); seen={}
    def execute(**kw):
        seen.update(kw); seen["acceptance_active"] = requirement_acceptance_active()
        return AgentTurnResult("direct","turn","req","hello",{"answer":"ok","user_question":"hello"},{})
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",execute)
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert seen["acceptance_active"] is True
    assert seen["payload"].model == "m"
    assert requirement_acceptance_active() is False
    assert store.get(job.job_id).status=="completed"


def test_failure_leaves_no_artifact(tmp_path, monkeypatch):
    store=setup_job(tmp_path); job=store.claim_next()
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",lambda **_: (_ for _ in ()).throw(RuntimeError("secret /tmp/x")))
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert store.get(job.job_id).status=="failed" and not list((tmp_path/"reports").glob("*"))
