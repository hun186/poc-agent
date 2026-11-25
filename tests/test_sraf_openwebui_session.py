"""Scoped session boundary with real account binding, HTTP and synthetic reports."""
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import chat, export, report_jobs
from api.security.models import AuthPrincipal
from api.security.principal import current_principal, optional_principal
from api.security.scopes import REGISTERED_SCOPES
from api.security.signed_urls import sign_resource
from api.services.sraf_session_namespace import (
    bind_openwebui_session, scoped_session_owned, is_reserved_session,
)
from api.services import turn_execution
from test_sraf_chat_deep_turn import configured
from test_sraf_chat_deep_dispatch import http


def test_scope_uses_actual_account_generation_and_safe_file_name(tmp_path, monkeypatch):
    auth, state, owner, other = configured(tmp_path, monkeypatch)
    from agent.session_store import _safe_session_id
    first = bind_openwebui_session(owner, ("chat-one",))
    assert first == bind_openwebui_session(owner, ("chat-one",))
    assert first != bind_openwebui_session(other, ("chat-one",))
    assert first != bind_openwebui_session(owner, ("chat-two",))
    assert _safe_session_id(first.key) == first.key and len(first.key) <= 120
    assert scoped_session_owned(first.key, owner)
    assert not scoped_session_owned(first.key, other)
    auth.delete_user("owner")
    auth.register("owner", "SyntheticReplacementPassword!2026")
    auth.approve_user("owner", "superuser", approved_by="operator")
    assert first != bind_openwebui_session(owner, ("chat-one",))
    assert not scoped_session_owned(first.key, owner)


@pytest.mark.parametrize("ids", [(), ("",), ("a","a"), ("a","b"), ("../bad",), ("x"*129,)])
def test_invalid_adapter_id(tmp_path, monkeypatch, ids):
    _, _, owner, _ = configured(tmp_path, monkeypatch)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        bind_openwebui_session(owner, ids)
    assert err.value.status_code == 400


def test_reserved_session_cannot_enter_legacy_turn_execution(tmp_path, monkeypatch):
    _, _, owner, _ = configured(tmp_path, monkeypatch)
    from fastapi import HTTPException
    from starlette.requests import Request
    key = bind_openwebui_session(owner, ("chat-one",)).key
    payload = SimpleNamespace(messages=[])
    for alias in (key, key.upper(), " "+key+" "):
        with pytest.raises(HTTPException) as err:
            turn_execution._resolve_session_id(payload, None, alias)
        assert err.value.status_code == 400
    request = Request({"type":"http","headers":[(b"x-sraf-openwebui-chat-id",b"chat-one")]})
    with pytest.raises(HTTPException):
        turn_execution._resolve_session_id(payload, request, None)


def test_scoped_session_bearer_export_and_legacy_job_fence(tmp_path, monkeypatch):
    _, state, owner, other = configured(tmp_path, monkeypatch)
    service = AuthPrincipal("service","owner",None,REGISTERED_SCOPES,"synthetic")
    key = bind_openwebui_session(owner, ("chat-one",)).key
    app = FastAPI()
    app.include_router(export.router)
    app.include_router(report_jobs.router)
    app.state.report_job_store = state.report_job_store
    selected = {"principal": owner}
    # Grant legacy download scope to the foreign principal so the owner gate,
    # rather than an unrelated missing scope, must deny.
    from dataclasses import replace
    foreign = replace(other, scopes=REGISTERED_SCOPES)
    app.dependency_overrides[current_principal] = lambda: selected["principal"]
    app.dependency_overrides[optional_principal] = lambda: selected["principal"]
    monkeypatch.setattr(export.API_STORE,"read_raw",lambda: {"structured_history":{key:{"turn":{"answer":"fixture"}}}})
    monkeypatch.setattr(export.ExportWordService,"build_docx_bytes",lambda *a,**k:(b"fixture","fixture.docx"))
    c = TestClient(app)
    url = "/v1/export/word"
    query = {"session_id":key,"turn_id":"turn"}
    assert c.get(url,params=query).status_code == 200
    for principal in (foreign, service):
        selected["principal"] = principal
        assert c.get(url,params=query).status_code == 404
    selected["principal"] = None
    assert c.get(url,params=query).status_code == 401
    query["sig"] = sign_resource("legacy_word", session_id=key, turn_id="turn")
    assert c.get(url,params=query).status_code == 200
    selected["principal"] = owner
    assert c.post("/v1/report/jobs",json={"prompt":"ordinary","session_id":key}).status_code == 400
    assert c.post("/v1/report/jobs",json={"prompt":"ordinary","session_id":"ordinary-1"}).status_code == 202


def test_actual_chat_header_resolves_scoped_context(http, monkeypatch):
    from test_sraf_chat_deep_dispatch import PROMPT, URL
    client, app, identity, events, auth = http
    seen = []
    actual = chat.execute_agent_turn
    def execute(**kw):
        scoped = kw.get("scoped_chat_session")
        seen.append(scoped.key if scoped is not None else None)
        result = actual(**kw)
        if scoped is not None:
            from dataclasses import replace
            result = replace(result, session_id=scoped.key)
        return result
    monkeypatch.setattr(chat,"execute_agent_turn",execute)
    body={"messages":[{"role":"user","content":PROMPT}]}
    result=client.post(URL,json=body,headers={"X-SRAF-OpenWebUI-Chat-Id":"chat-one"})
    assert result.status_code == 200 and is_reserved_session(seen[-1])
    assert result.json()["choices"][0]["message"]["context"]["word_export"]["session_id"] == seen[-1]
    key=seen[-1]
    monkeypatch.setattr(chat,"resolve_session_key",lambda *a:key)
    assert client.post(URL,json=body).status_code == 400
    identity["principal"]=AuthPrincipal("service","owner",None,REGISTERED_SCOPES,"synthetic")
    assert client.post(URL,json=body,headers={"X-SRAF-OpenWebUI-Chat-Id":"chat-one"}).status_code == 403
