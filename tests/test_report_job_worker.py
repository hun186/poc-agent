from pathlib import Path

import pytest
from agent.external_capabilities import BackendPlan, install_plan, reset_plan_for_tests
from api.services.report_job_store import ReportJobStore
from api.services.report_job_worker import ReportJobWorker
from api.services.turn_execution import AgentTurnResult
from api.services import report_job_worker
from agent.external_capabilities import (
    mark_requirement_e2e_model, requirement_acceptance_active,
)

@pytest.fixture(autouse=True)
def _isolate_acceptance_plan():
    reset_plan_for_tests()
    yield
    reset_plan_for_tests()


HANDOFF_OWNER = "requirement-handoff-runtime"
HANDOFF_SUBMISSION = "rhsub_" + "a" * 48

def setup_job(tmp_path, model="m", *, trusted_handoff=False, owner_id=None):
    s=ReportJobStore(tmp_path/"j.db"); s.initialize()
    submission = HANDOFF_SUBMISSION if trusted_handoff else None
    session_id = f"requirement-handoff:{submission}" if trusted_handoff else "direct"
    metadata = {"submission_id": submission, "workflow_id": "report_v1"} if trusted_handoff else {}
    s.create(
        job_id="rpt_x", prompt="hello", filename="../../bad.docx",
        session_id=session_id, model=model, options={}, metadata=metadata,
        idempotency_key=submission, request_hash="h",
        owner_kind="service" if owner_id is not None else None, owner_id=owner_id,
    )
    return s
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
def test_worker_scopes_only_verified_requirement_e2e_job(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL", HANDOFF_OWNER)
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    install_plan(BackendPlan("live", "live", "live", "pass", "pass"))
    store=setup_job(
        tmp_path, mark_requirement_e2e_model("m"),
        trusted_handoff=True, owner_id=HANDOFF_OWNER,
    ); job=store.claim_next(); seen={}
    def execute(**kw):
        seen.update(kw); seen["acceptance_active"] = requirement_acceptance_active()
        return AgentTurnResult("direct","turn","req","hello",{"answer":"ok","user_question":"hello"},{})
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",execute)
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert seen["acceptance_active"] is True
    assert seen["payload"].model == "m"
    assert requirement_acceptance_active() is False
    assert store.get(job.job_id).status=="completed"


def test_worker_keeps_normal_handoff_job_in_production_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL", HANDOFF_OWNER)
    store=setup_job(
        tmp_path, "m", trusted_handoff=True, owner_id=HANDOFF_OWNER,
    )
    job=store.claim_next(); seen={}

    def execute(**kw):
        seen.update(kw); seen["acceptance_active"] = requirement_acceptance_active()
        return AgentTurnResult("direct","turn","req","hello",{"answer":"ok","user_question":"hello"},{})

    monkeypatch.setattr(report_job_worker,"execute_agent_turn",execute)
    ReportJobWorker(store,tmp_path/"reports").execute(job)

    assert seen["acceptance_active"] is False
    assert seen["payload"].model == "m"
    assert store.get(job.job_id).status == "completed"


def test_worker_rejects_forged_requirement_e2e_model_without_handoff_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL", HANDOFF_OWNER)
    store=setup_job(tmp_path, mark_requirement_e2e_model("m"))
    job=store.claim_next()
    monkeypatch.setattr(
        report_job_worker, "execute_agent_turn",
        lambda **_: (_ for _ in ()).throw(AssertionError("untrusted E2E marker must not execute")),
    )

    ReportJobWorker(store,tmp_path/"reports").execute(job)

    persisted = store.get(job.job_id)
    assert persisted.status == "failed"
    assert persisted.error_type == "CapabilityError"
    assert requirement_acceptance_active() is False


def test_worker_rejects_handoff_shaped_metadata_from_wrong_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL", HANDOFF_OWNER)
    store=setup_job(
        tmp_path, mark_requirement_e2e_model("m"),
        trusted_handoff=True, owner_id="ordinary-report-service",
    )
    job=store.claim_next()
    monkeypatch.setattr(
        report_job_worker, "execute_agent_turn",
        lambda **_: (_ for _ in ()).throw(AssertionError("wrong owner must not execute")),
    )

    ReportJobWorker(store,tmp_path/"reports").execute(job)

    assert store.get(job.job_id).status == "failed"
    assert requirement_acceptance_active() is False


def test_failure_leaves_no_artifact(tmp_path, monkeypatch):
    store=setup_job(tmp_path); job=store.claim_next()
    monkeypatch.setattr(report_job_worker,"execute_agent_turn",lambda **_: (_ for _ in ()).throw(RuntimeError("secret /tmp/x")))
    ReportJobWorker(store,tmp_path/"reports").execute(job)
    assert store.get(job.job_id).status=="failed" and not list((tmp_path/"reports").glob("*"))


def test_unprepared_e2e_job_fails_closed_without_running_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL", HANDOFF_OWNER)
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    store = setup_job(tmp_path, mark_requirement_e2e_model("m"),
                      trusted_handoff=True, owner_id=HANDOFF_OWNER)
    job = store.claim_next()
    monkeypatch.setattr(report_job_worker, "execute_agent_turn",
                        lambda **_: (_ for _ in ()).throw(AssertionError("E2E ran")))
    ReportJobWorker(store, tmp_path / "reports").execute(job)
    assert store.get(job.job_id).status == "failed"
    assert store.get(job.job_id).error_type == "CapabilityError"
