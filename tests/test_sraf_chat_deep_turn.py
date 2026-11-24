"""Real authenticated account and SQLite replay, no live ES or model."""
from dataclasses import replace
from types import SimpleNamespace
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.security.models import AuthPrincipal
from api.security.scopes import REGISTERED_SCOPES
from api.routers import report_jobs
from api.security.principal import current_principal
from api.services.report_job_store import CHAT_DEEP_KEY_PREFIX, IdempotencyConflict
from api.services.report_job_worker import ReportJobWorker
from api.services.sraf_adaptive_job_runtime import AdaptiveJobRuntime, create_adaptive_job
from api.services.sraf_deep_scope_policy import DeepScopeDenied, compile_explicit_deep_question
from api.services.sraf_chat_deep_turn import (
    prepare_chat_deep_turn, replay_chat_deep_turn, DeepRuntimeUnavailable,
)
from test_sraf_deep_scope_policy import setup, QUESTION


def configured(tmp_path, monkeypatch):
    auth, store, policy, owner, other = setup(tmp_path, monkeypatch)
    def forbidden(*a, **k):
        raise AssertionError("No provider calls in replay")
    runtime = AdaptiveJobRuntime(forbidden, forbidden, forbidden,
                                 policy.check_owner_index, policy.check_question_branches, forbidden)
    worker = ReportJobWorker(store, tmp_path, adaptive_runtime=runtime)
    state = SimpleNamespace(deep_scope_policy=policy, report_job_store=store, report_job_worker=worker)
    return auth, state, owner, other


def persist(state, turn):
    return create_adaptive_job(state.report_job_store,
        intent=compile_explicit_deep_question(QUESTION, ("news_test",)),
        owner_id=turn.principal.subject, owner_binding=turn.account_binding,
        idempotency_key=turn.key, max_active_jobs=2)


def test_exact_chat_retry_returns_same_durable_job(tmp_path, monkeypatch):
    auth, state, owner, other = configured(tmp_path, monkeypatch)
    turn = prepare_chat_deep_turn(state, owner, turn_tokens=("message-1",))
    assert replay_chat_deep_turn(state, turn, prompt=QUESTION) is None
    assert turn.key.startswith(CHAT_DEEP_KEY_PREFIX)
    job, created = persist(state, turn)
    assert created
    assert replay_chat_deep_turn(state, turn, prompt=QUESTION).job_id == job.job_id
    assert persist(state, turn)[0].job_id == job.job_id
    assert not persist(state, turn)[1]
    with pytest.raises(IdempotencyConflict):
        replay_chat_deep_turn(state, turn, prompt=QUESTION + " ")
    second = prepare_chat_deep_turn(state, owner, turn_tokens=("message-2",))
    assert second.key != turn.key
    assert replay_chat_deep_turn(state, second, prompt=QUESTION) is None
    assert persist(state, second)[0].job_id != job.job_id
    # Full queue does not prevent replay.
    assert replay_chat_deep_turn(state, turn, prompt=QUESTION).job_id == job.job_id
    assert persist(state, turn)[1] is False
    auth.reject_user("owner", rejected_by="operator")
    with pytest.raises(DeepScopeDenied):
        replay_chat_deep_turn(state, turn, prompt=QUESTION)


@pytest.mark.parametrize("tokens", [(), ("",), ("a", "a"), ("a", "b"), ("a b",), ("x"*129,), ("中文",)])
def test_invalid_turn_keys_do_not_admit(tmp_path, monkeypatch, tokens):
    _, state, owner, _ = configured(tmp_path, monkeypatch)
    with pytest.raises(DeepScopeDenied):
        prepare_chat_deep_turn(state, owner, turn_tokens=tokens)
    assert state.report_job_store.list_owned_summaries(owner_kind="user", owner_id="owner") == []


def test_service_ungranted_and_recomposed_runtime_denied(tmp_path, monkeypatch):
    _, state, owner, other = configured(tmp_path, monkeypatch)
    service = AuthPrincipal("service", "owner", None, REGISTERED_SCOPES, "synthetic-key")
    for p in (service, other):
        with pytest.raises(DeepScopeDenied):
            prepare_chat_deep_turn(state, p, turn_tokens=("message-1",))
    turn = prepare_chat_deep_turn(state, owner, turn_tokens=("message-1",))
    persist(state, turn)
    state.deep_scope_policy = replace(state.deep_scope_policy, max_active_jobs=1)
    with pytest.raises(DeepRuntimeUnavailable):
        replay_chat_deep_turn(state, turn, prompt=QUESTION)


def test_corrupt_hash_or_missing_checkpoint_never_replayed(tmp_path, monkeypatch):
    _, state, owner, _ = configured(tmp_path, monkeypatch)
    turn = prepare_chat_deep_turn(state, owner, turn_tokens=("message-1",))
    job, _ = persist(state, turn)
    db = state.report_job_store.db_path
    with sqlite3.connect(db) as con:
        con.execute("UPDATE report_jobs SET request_hash='corrupt' WHERE job_id=?", (job.job_id,))
    with pytest.raises(DeepScopeDenied):
        replay_chat_deep_turn(state, turn, prompt=QUESTION)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE report_jobs SET request_hash=? WHERE job_id=?", (job.request_hash, job.job_id))
        con.execute("DELETE FROM sraf_nround_checkpoints WHERE job_id=?", (job.job_id,))
    with pytest.raises(DeepScopeDenied):
        replay_chat_deep_turn(state, turn, prompt=QUESTION)


def test_ordinary_public_api_cannot_reserve_chat_key(tmp_path, monkeypatch):
    _, state, owner, _ = configured(tmp_path, monkeypatch)
    turn = prepare_chat_deep_turn(state, owner, turn_tokens=("message-1",))
    app = FastAPI()
    app.include_router(report_jobs.router)
    app.state.report_job_store = state.report_job_store
    app.dependency_overrides[current_principal] = lambda: owner
    client = TestClient(app)
    denied = client.post("/v1/report/jobs", json={"prompt":"ordinary"},
                         headers={"Idempotency-Key":turn.key})
    assert denied.status_code == 400
    assert replay_chat_deep_turn(state, turn, prompt=QUESTION) is None
    assert client.post("/v1/report/jobs", json={"prompt":"ordinary"},
                       headers={"Idempotency-Key":"ordinary-1"}).status_code == 202
    assert persist(state, turn)[1]
