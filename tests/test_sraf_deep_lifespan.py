"""Real FastAPI lifespan, auth, SQLite and Worker; synthetic config, no provider IO."""
import json
from threading import Event
from pathlib import Path

import certifi
from elasticsearch import Elasticsearch
from elastic_transport import Transport
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.main import lifespan
from api.routers import nround_admission
from api.services.report_job_worker import ReportJobWorker
from api.services.sraf_deep_startup_config import DeepStartupConfigError
from api.services.sraf_deep_es_connection import DeepESConfigError
from api.services.sraf_deep_scope_policy import DeepScopePolicy
from api.services.sraf_adaptive_job_runtime import AdaptiveJobRuntime
from test_sraf_deep_scope_policy import setup, QUESTION
from test_sraf_deep_startup_config import valid


def prepare(tmp_path, monkeypatch):
    auth, _, _, owner, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setenv("REPORT_JOBS_DB_PATH", str(tmp_path / "lifespan.sqlite"))
    monkeypatch.setenv("REPORT_JOBS_REPORTS_ROOT", str(tmp_path / "reports"))
    monkeypatch.setenv("REQUIREMENT_PIPELINE_ENABLED", "false")
    monkeypatch.setenv("REQUIREMENT_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "auto")
    monkeypatch.setenv("SRA_SIGNED_URL_SECRET", "synthetic-lifespan-" + "s" * 48)
    for k, v in valid().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SRAF_DEEP_OWNER_GRANTS_JSON", json.dumps([{
        "owner_id": "owner", "account_created_at": auth.get_user("owner")["created_at"],
        "indexes": ["news_test"],
    }]))
    monkeypatch.setenv("ES_URL", "https://127.0.0.1:9200")
    monkeypatch.setenv("ES_USERNAME", "synthetic-reader")
    monkeypatch.setenv("ES_PASSWORD", "synthetic-password")
    monkeypatch.setenv("SRAF_DEEP_ES_CA_CERT", certifi.where())
    def forbid(*a, **k):
        raise AssertionError("provider IO forbidden in synthetic lifespan test")
    monkeypatch.setattr(Transport, "perform_request", forbid)
    import requests
    monkeypatch.setattr(requests.Session, "post", forbid)
    app = FastAPI(lifespan=lifespan)
    app.include_router(nround_admission.router)
    from api.services.auth_support import AuthUser
    from api.services.auth_tokens import create_token
    token = create_token(AuthUser("owner", auth.get_user("owner")["role"], "active"), auth.get_user)
    return app, {"Authorization": "Bearer " + token, "Idempotency-Key": "synthetic"}


def test_real_lifespan_composes_exact_policy_runtime_and_local_models(tmp_path, monkeypatch):
    app, headers = prepare(tmp_path, monkeypatch)
    closed = []
    original_close = Elasticsearch.close
    def close(self):
        closed.append(self)
        return original_close(self)
    monkeypatch.setattr(Elasticsearch, "close", close)
    # Prevent consumption of the admitted job, not creation of the real thread.
    monkeypatch.setattr(ReportJobWorker, "execute", lambda self, job: None)
    with TestClient(app) as c:
        policy = app.state.deep_scope_policy
        worker = app.state.report_job_worker
        runtime = worker.adaptive_runtime
        assert type(policy) is DeepScopePolicy
        assert type(runtime) is AdaptiveJobRuntime
        assert worker.store is app.state.report_job_store
        assert worker.thread.is_alive()
        assert runtime.check_owner_index.__self__ is policy
        assert runtime.check_question_branches.__self__ is policy
        assert runtime.report_model_id == "synthetic-report"
        assert runtime.report_call.__self__ is runtime.planner_call.__self__
        assert runtime.report_call.__self__ is runtime.semantic_assessor.__self__
        es = runtime.es_client_factory()
        assert type(es) is Elasticsearch
        assert c.post("/v1/report/jobs/deep", headers=headers,
                      json={"prompt": QUESTION}).status_code == 202
    assert app.state.deep_scope_policy is None
    assert not worker.thread.is_alive()
    assert closed == [es]
    # A new disabled lifespan has no deep runtime or inherited policy.
    monkeypatch.setenv("SRAF_DEEP_REPORT_ENABLED", "0")
    with TestClient(app) as c:
        assert app.state.deep_scope_policy is None
        assert app.state.report_job_worker.adaptive_runtime is None
        assert c.post("/v1/report/jobs/deep", headers=headers,
                      json={"prompt": QUESTION}).status_code == 503
    assert closed == [es]


@pytest.mark.parametrize("bad", ["flag", "es"])
def test_explicit_invalid_config_fails_before_job_store_initialization(tmp_path, monkeypatch, bad):
    app, _ = prepare(tmp_path, monkeypatch)
    if bad == "flag":
        monkeypatch.setenv("SRAF_DEEP_REPORT_ENABLED", "yes")
        exc = DeepStartupConfigError
    else:
        monkeypatch.setenv("ES_URL", "http://127.0.0.1:9200")
        exc = DeepESConfigError
    with pytest.raises(exc):
        with TestClient(app):
            pytest.fail("bad enabled configuration started API")
    assert app.state.deep_scope_policy is None
    assert not (tmp_path / "lifespan.sqlite").exists()


def test_worker_start_failure_closes_connection(tmp_path, monkeypatch):
    app, _ = prepare(tmp_path, monkeypatch)
    closed = []
    original_close = Elasticsearch.close
    def close(self):
        closed.append(self)
        return original_close(self)
    monkeypatch.setattr(Elasticsearch, "close", close)
    def broken(self):
        raise RuntimeError("synthetic startup failure")
    monkeypatch.setattr(ReportJobWorker, "start", broken)
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        with TestClient(app):
            pytest.fail("worker failed startup")
    assert len(closed) == 1
    assert app.state.deep_scope_policy is None


def test_shutdown_does_not_close_es_under_running_worker(tmp_path, monkeypatch):
    app, headers = prepare(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    closed = []
    original_close = Elasticsearch.close
    original_stop = ReportJobWorker.stop
    def close(self):
        closed.append(self)
        return original_close(self)
    def execute(self, job):
        entered.set()
        release.wait(15)
    monkeypatch.setattr(Elasticsearch, "close", close)
    monkeypatch.setattr(ReportJobWorker, "execute", execute)
    monkeypatch.setattr(ReportJobWorker, "stop", lambda self: original_stop(self, timeout=0))
    worker = None
    try:
        with TestClient(app) as c:
            worker = app.state.report_job_worker
            assert c.post("/v1/report/jobs/deep", headers=headers,
                          json={"prompt": QUESTION}).status_code == 202
            assert entered.wait(5)
        assert app.state.deep_scope_policy is None
        assert worker.thread.is_alive()
        assert closed == []
        with pytest.raises(RuntimeError, match="report_worker_previous_lifespan_active"):
            with TestClient(app):
                pytest.fail("overlapping worker started")
    finally:
        release.set()
        if worker is not None:
            worker.thread.join(5)
    assert not worker.thread.is_alive()
    assert len(closed) == 1


@pytest.mark.parametrize("bad,expected", [
    ("flag", "DEGRADED_CONFIG"),
    ("es", "DEGRADED_ES_CONFIG"),
])
def test_opt_in_ordinary_only_holds_deep_queue_and_serves_ordinary(tmp_path, monkeypatch, bad, expected):
    from api.services.report_job_store import ReportJobStore
    from test_sraf_adaptive_job_runtime import _submit
    app, headers = prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("SRAF_DEEP_STARTUP_FAILURE_POLICY", "ordinary_only")
    store = ReportJobStore(tmp_path / "lifespan.sqlite")
    store.initialize()
    deep, _ = _submit(store)
    ordinary, _ = store.create(
        job_id="ordinary-fixture", prompt="ordinary", filename="ordinary.docx",
        session_id="ordinary-session", model="ordinary-model", options={}, metadata={},
        idempotency_key="ordinary-key", request_hash="ordinary-hash")
    if bad == "flag":
        monkeypatch.setenv("SRAF_DEEP_REPORT_ENABLED", "yes")
    else:
        monkeypatch.setenv("SRAF_DEEP_ES_URL", "")
    executed = Event()
    observed = []
    def execute(worker, job):
        observed.append(job.job_id)
        worker.store.fail(job.job_id, "synthetic", "synthetic")
        executed.set()
    monkeypatch.setattr(ReportJobWorker, "execute", execute)
    with TestClient(app) as c:
        assert app.state.deep_startup_status == expected
        assert app.state.deep_scope_policy is None
        assert app.state.deep_chat_auto_base_url is None
        assert app.state.report_job_worker.adaptive_runtime is None
        assert c.post("/v1/report/jobs/deep", headers=headers,
                      json={"prompt": QUESTION}).status_code == 503
        assert executed.wait(5)
        assert observed == [ordinary.job_id]
        assert store.get(deep.job_id).status == "queued"
        from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
        assert NroundCheckpointStore(store.db_path).get_public(deep.job_id)["state"] == "QUEUED"
    # Restoring configuration resumes only via the normal exact runtime.
    monkeypatch.setenv("SRAF_DEEP_REPORT_ENABLED", "1")
    monkeypatch.delenv("SRAF_DEEP_ES_URL", raising=False)
    executed.clear()
    with TestClient(app):
        assert app.state.deep_startup_status == "CONFIGURED"
        assert executed.wait(5)
        assert observed == [ordinary.job_id, deep.job_id]


def test_unknown_failure_policy_does_not_silently_degrade(tmp_path, monkeypatch):
    app, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("SRAF_DEEP_STARTUP_FAILURE_POLICY", "typo")
    with pytest.raises(RuntimeError, match="deep_startup_failure_policy_invalid"):
        with TestClient(app):
            pytest.fail("invalid policy started service")


def test_unexpected_composition_bug_still_aborts_startup(tmp_path, monkeypatch):
    app, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("SRAF_DEEP_STARTUP_FAILURE_POLICY", "ordinary_only")
    from api.services import sraf_deep_runtime_composition
    def broken(*a, **k):
        raise RuntimeError("synthetic unexpected bug")
    monkeypatch.setattr(sraf_deep_runtime_composition, "compose_deep_runtime", broken)
    with pytest.raises(RuntimeError, match="synthetic unexpected bug"):
        with TestClient(app):
            pytest.fail("unexpected bug silently swallowed")


def test_explicit_ordinary_only_disabled_deep_holds_existing_queue(tmp_path, monkeypatch):
    from api.services.report_job_store import ReportJobStore
    from test_sraf_adaptive_job_runtime import _submit
    app, headers = prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("SRAF_DEEP_STARTUP_FAILURE_POLICY", "ordinary_only")
    monkeypatch.setenv("SRAF_DEEP_REPORT_ENABLED", "0")
    store = ReportJobStore(tmp_path / "lifespan.sqlite")
    store.initialize()
    deep, _ = _submit(store)
    ordinary, _ = store.create(job_id="ordinary-disabled-fixture", prompt="ordinary",
        filename="ordinary.docx", session_id="ordinary-session", model="ordinary-model",
        options={}, metadata={}, idempotency_key="ordinary-key", request_hash="ordinary-hash")
    executed = Event()
    observed = []
    def execute(worker, job):
        observed.append(job.job_id)
        worker.store.fail(job.job_id, "synthetic", "synthetic")
        executed.set()
    monkeypatch.setattr(ReportJobWorker, "execute", execute)
    with TestClient(app) as c:
        assert app.state.deep_startup_status == "DISABLED"
        assert c.post("/v1/report/jobs/deep", headers=headers,
                      json={"prompt": QUESTION}).status_code == 503
        assert executed.wait(5)
        assert observed == [ordinary.job_id]
        assert store.get(deep.job_id).status == "queued"
