"""Actual user authentication + SQLite admission and Worker policy rechecks."""
from dataclasses import replace
import json

import pytest

import api.services.auth_store as auth_store_module
from api.services.auth_support import AuthUser
from api.services.auth_tokens import create_token
from api.security.principal import optional_principal
from api.security.models import AuthPrincipal
from api.security.scopes import REGISTERED_SCOPES
from api.services.report_job_store import ReportJobStore, IdempotencyConflict
from api.services.sraf_adaptive_job_runtime import AdaptiveJobIntent, ADAPTIVE_OWNER_BINDING
from api.services.sraf_deep_scope_policy import (
    DeepOwnerGrant, DeepScopePolicy, DeepScopeDenied, DeepQuestionUnsupported,
    compile_explicit_deep_question,
)
from api.routers.report_jobs import _view
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore


QUESTION = "主題詞：聯合國、外交、合作\n事件期間：2023-08-01~2023-08-31\n分析面向：外交回應、合作進展"


def setup(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    bootstrap = tmp_path / "bootstrap.json"
    bootstrap.write_text(json.dumps({"superusers": [
        {"username": "owner", "password": "SyntheticOwnerPassword!2026"}]}), encoding="utf-8")
    monkeypatch.setenv("SRA_AUTH_USERS_FILE", str(users))
    monkeypatch.setenv("SRA_BOOTSTRAP_SUPERUSERS_FILE", str(bootstrap))
    monkeypatch.setenv("SRA_AUTH_SECRET", "synthetic-auth-key-" + "z" * 48)
    monkeypatch.setenv("SRA_EDITOR_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    auth = auth_store_module.AuthStore()
    monkeypatch.setattr(auth_store_module, "AUTH_STORE", auth)
    auth.register("other", "SyntheticOtherPassword!2026")
    auth.approve_user("other", "data_reader", approved_by="owner")
    def principal(name):
        row = auth.get_user(name)
        tok = create_token(AuthUser(name, row["role"], "active"), auth.get_user)
        return optional_principal("Bearer " + tok)
    owner = principal("owner")
    other = principal("other")
    policy = DeepScopePolicy((DeepOwnerGrant("owner", auth.get_user("owner")["created_at"],
                                            ("news_test",)),), 2)
    store = ReportJobStore(tmp_path / "jobs.db")
    store.initialize()
    return auth, store, policy, owner, other


def test_actual_authenticated_admission_immutable_scope_and_replay(tmp_path, monkeypatch):
    auth, store, policy, owner, other = setup(tmp_path, monkeypatch)
    prompt = " \n" + QUESTION + "\n "
    job, created = policy.admit(store, principal=owner, prompt=prompt, idempotency_key="a")
    assert created and job.prompt == prompt and job.owner_id == "owner"
    assert NroundCheckpointStore(store.db_path).get_public(job.job_id)["state"] == "QUEUED"
    assert ADAPTIVE_OWNER_BINDING in job.metadata
    view = _view(job)
    assert view["options"] == {} and view["metadata"] == {}
    assert "news_test" not in json.dumps(view)
    replay, created = policy.admit(store, principal=owner, prompt=prompt, idempotency_key="a")
    assert not created and replay.job_id == job.job_id
    with pytest.raises(IdempotencyConflict):
        policy.admit(store, principal=owner, prompt=QUESTION, idempotency_key="a")
    claim = store.claim_next()
    c = AdaptiveJobIntent.from_options(claim.options, claim.prompt).constraints
    assert policy.check_owner_index(claim, "news_test")
    assert not policy.check_owner_index(claim, "secret_index")
    assert policy.check_question_branches(claim, c, ("CANONICAL_MAIN",))
    assert not policy.check_question_branches(claim, c, ("CANONICAL_MAIN", "OTHER"))
    assert not policy.check_question_branches(claim, replace(c, allowed_indexes=("secret_index",)), ("CANONICAL_MAIN",))
    assert not policy.check_owner_index(replace(claim, metadata={}), "news_test")
    assert not policy.check_question_branches(replace(claim, prompt=QUESTION), c, ("CANONICAL_MAIN",))
    auth.reject_user("owner", rejected_by="operator")
    assert not policy.check_owner_index(claim, "news_test")
    assert not policy.check_question_branches(claim, c, ("CANONICAL_MAIN",))


def test_ungranted_service_and_unsupported_question_never_queue(tmp_path, monkeypatch):
    _, store, policy, owner, other = setup(tmp_path, monkeypatch)
    service = AuthPrincipal("service", "owner", None, REGISTERED_SCOPES, "key")
    for denied in (other, service):
        with pytest.raises(DeepScopeDenied):
            policy.admit(store, principal=denied, prompt=QUESTION, idempotency_key="a")
    for bad in (QUESTION + "\n額外指定欄位：SECRET", "分析美國經濟",
                QUESTION.replace("2023-08-01", "昨天"), QUESTION.replace("2023-08-31", "2023-02-30"),
                QUESTION.replace("聯合國", "排除聯合國"), QUESTION.replace("外交、合作", "外交、外交")):
        with pytest.raises(DeepQuestionUnsupported):
            policy.admit(store, principal=owner, prompt=bad, idempotency_key="a")
    assert store.list_owned_summaries(owner_kind="user", owner_id="owner") == []


def test_recreated_account_cannot_use_prior_grant(tmp_path, monkeypatch):
    auth, store, policy, owner, _ = setup(tmp_path, monkeypatch)
    job, _ = policy.admit(store, principal=owner, prompt=QUESTION, idempotency_key="a")
    original = auth.get_user("owner")
    real_get = auth.get_user
    def recreated(name):
        if name == "owner":
            return {**original, "created_at": "2099-01-01T00:00:00+00:00"}
        return real_get(name)
    monkeypatch.setattr(auth, "get_user", recreated)
    assert not policy.check_owner_index(job, "news_test")
    with pytest.raises(DeepScopeDenied):
        policy.admit(store, principal=owner, prompt=QUESTION, idempotency_key="b")
    replacement = DeepScopePolicy((DeepOwnerGrant("owner", recreated("owner")["created_at"],
                                                  ("news_test",)),), 2)
    assert not replacement.check_owner_index(job, "news_test")


def test_exact_literal_contract_and_unbounded_date():
    i = compile_explicit_deep_question(QUESTION.replace("2023-08-01~2023-08-31", "不限"), ("news_test",))
    assert i.constraints.event_date.source == "none"
    assert i.constraints.original_core_terms == ("聯合國", "外交", "合作")
    assert i.target_aspects == ("外交回應", "合作進展")
    with pytest.raises(DeepScopeDenied):
        DeepOwnerGrant("owner", "stamp", ("news*",))
