"""Import the actual standalone Pipe; synthetic transport, no private network."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import chat
from api.security.models import AuthPrincipal
from api.security.scopes import REGISTERED_SCOPES
from api.security.principal import current_principal
from test_sraf_chat_deep_turn import configured

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sraf_openwebui_pipe_fixture", ROOT / "integrations/openwebui/sraf_pipe.py")
pipe_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pipe_module
spec.loader.exec_module(pipe_module)
TOKEN = "syntheticPayload.syntheticSignature"
BASE = "https://sraf.example.test"
PROMPT = "請分析2023年8月期間，聯合國的外交回應、合作進展。"
ANSWER = {"object":"chat.completion","choices":[{"message":{"role":"assistant",
          "content":"一般 Word\n深度版進度", "context":{"deep_report":{"job_id":"synthetic"}}}}]}


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setenv("ENABLE_VALVE_ENCRYPTION","true")
    monkeypatch.setenv("WEBUI_SECRET_KEY","synthetic" * 5)
    pipe = pipe_module.Pipe()
    pipe.valves = pipe.Valves(ENABLED=True,SRAF_API_ROOT=BASE)
    user = {"valves":pipe.UserValves(SRAF_ACCESS_TOKEN=TOKEN)}
    return pipe,user


def install(monkeypatch, calls, *, protocol=True, status=200):
    real = httpx.AsyncClient
    def handle(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200 if protocol else 404,
                   json={"protocol":"sraf-openwebui-scoped-chat-v1"})
        return httpx.Response(status,json=ANSWER if status==200 else {"error":"private-body-"+TOKEN})
    def factory(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["verify"].check_hostname
        return real(transport=httpx.MockTransport(handle),**kwargs)
    monkeypatch.setattr(pipe_module.httpx,"AsyncClient",factory)


def invoke(pipe,user,*,message="msg-one",task=None,body=None,chat_id="chat-one",metadata=None):
    if body is None:
        body={"messages":[{"role":"user","content":PROMPT}],"stream":False}
    return asyncio.run(pipe.pipe(body,__user__=user,__chat_id__=chat_id,
                                __message_id__=message,__task__=task,__metadata__=metadata))


def test_exact_authorized_requests_and_retry(fixture,monkeypatch):
    pipe,user=fixture
    calls=[]
    install(monkeypatch,calls)
    assert invoke(pipe,user)==ANSWER
    assert [x.method for x in calls]==["GET","POST"]
    assert calls[0].url.path=="/v1/sraf/openwebui/capabilities"
    assert calls[1].url.path=="/v1/chat/completions"
    assert calls[1].headers["authorization"]=="Bearer "+TOKEN
    assert calls[1].headers["x-sraf-openwebui-chat-id"]=="chat-one"
    assert json.loads(calls[1].content)=={"model":"SRA-Structured Retrieval Agent",
        "messages":[{"role":"user","content":PROMPT}],"stream":False,"format":"markdown"}
    key=calls[1].headers["idempotency-key"]
    assert invoke(pipe,user)==ANSWER
    assert calls[-1].headers["idempotency-key"]==key
    invoke(pipe,user,message="msg-two")
    assert calls[-1].headers["idempotency-key"]!=key
    invoke(pipe,user,chat_id="chat-two")
    assert calls[-1].headers["idempotency-key"]!=key
    invoke(pipe,user,task="title_generation")
    assert "idempotency-key" not in calls[-1].headers
    invoke(pipe,user,message=None)
    assert "idempotency-key" not in calls[-1].headers
    body={"messages":[{"role":"system","content":"constraint"},{"role":"user","content":PROMPT}],"stream":True}
    assert invoke(pipe,user,body=body)==ANSWER["choices"][0]["message"]["content"]
    assert "idempotency-key" not in calls[-1].headers
    assert json.loads(calls[-1].content)["messages"]==body["messages"]


@pytest.mark.parametrize("kind",["disabled","encryption","secret","shared_key","url","no_chat","file","tool","multimodal"])
def test_invalid_inputs_do_not_contact_provider(fixture,monkeypatch,kind):
    pipe,user=fixture
    calls=[]
    install(monkeypatch,calls)
    kw={}
    if kind=="disabled": pipe.valves.ENABLED=False
    elif kind=="encryption": monkeypatch.setenv("ENABLE_VALVE_ENCRYPTION","false")
    elif kind=="secret": monkeypatch.delenv("WEBUI_SECRET_KEY")
    elif kind=="shared_key": user={"valves":{"SRAF_ACCESS_TOKEN":"sra_sk_synthetic"}}
    elif kind=="url": pipe.valves.SRAF_API_ROOT="http://example.test"
    elif kind=="no_chat": kw["chat_id"]=None
    elif kind=="file": kw["metadata"]={"files":[{"name":"fixture"}]}
    elif kind=="tool": kw["body"]={"messages":[{"role":"tool","content":"fixture"}]}
    else: kw["body"]={"messages":[{"role":"user","content":[{"type":"image_url"}]}]}
    with pytest.raises(pipe_module.AdapterError) as e:
        invoke(pipe,user,**kw)
    assert not calls and TOKEN not in str(e.value)


def test_old_backend_or_upstream_error_never_retries_or_leaks(fixture,monkeypatch):
    pipe,user=fixture
    calls=[]
    with monkeypatch.context() as patch:
        install(patch,calls,protocol=False)
        with pytest.raises(pipe_module.AdapterError):
            invoke(pipe,user)
    assert [x.method for x in calls]==["GET"]
    calls.clear()
    install(monkeypatch,calls,status=403)
    with pytest.raises(pipe_module.AdapterError) as e:
        invoke(pipe,user)
    assert [x.method for x in calls]==["GET","POST"]
    assert TOKEN not in str(e.value) and "private-body" not in str(e.value)


def test_capability_route_requires_individual_principal(tmp_path,monkeypatch):
    _,_,owner,other=configured(tmp_path,monkeypatch)
    app=FastAPI()
    app.include_router(chat.router)
    selected={"principal":owner}
    app.dependency_overrides[current_principal]=lambda:selected["principal"]
    c=TestClient(app)
    url="/v1/sraf/openwebui/capabilities"
    assert c.get(url).json()=={"protocol":"sraf-openwebui-scoped-chat-v1"}
    selected["principal"]=AuthPrincipal("service","owner",None,REGISTERED_SCOPES,"synthetic")
    assert c.get(url).status_code==403
