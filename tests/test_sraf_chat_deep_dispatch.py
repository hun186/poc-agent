"""Actual Chat HTTP, auth and durable admission, synthetic ordinary model boundary."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.es.ordinary_scope_receipt import OrdinaryScopeReceipt
from api.routers import chat
from api.security.models import AuthPrincipal
from api.security.scopes import REGISTERED_SCOPES
from api.security.principal import current_principal
from api.services.turn_execution import AgentTurnResult
from api.services.sraf_deep_startup_config import load_deep_startup_config, DeepStartupConfigError
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from test_sraf_chat_deep_turn import configured
from test_sraf_deep_startup_config import valid


PROMPT = "請分析2023年8月期間，聯合國的外交回應、合作進展。"
RECEIPT = OrdinaryScopeReceipt(("news_test",), "2023-08-01", "2023-08-31", ("聯合國",))
URL = "/v1/chat/completions"


@pytest.fixture
def http(tmp_path, monkeypatch):
    auth, state, owner, other = configured(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(chat.router)
    for k, v in vars(state).items():
        setattr(app.state, k, v)
    app.state.deep_chat_auto_base_url = "https://sraf.example.test"
    identity = {"principal": owner, "receipt": RECEIPT, "mode": "SRA_REPORT", "fail": False}
    events = []
    app.dependency_overrides[current_principal] = lambda: identity["principal"]
    monkeypatch.setattr(chat, "get_sessions", lambda: {})
    monkeypatch.setattr(chat, "get_last_structured", lambda: {})
    monkeypatch.setattr(chat, "get_memory", lambda: {})
    monkeypatch.setattr(chat, "get_structured_history", lambda: {})
    monkeypatch.setattr(chat, "resolve_session_key", lambda *a: "synthetic-session")
    monkeypatch.setattr(chat, "extract_user_and_history",
        lambda payload, *a: (payload.messages[-1].content, payload.messages[-1].content, [], []))
    monkeypatch.setattr(chat, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(chat, "save_trace", lambda *a, **k: events.append("trace"))
    monkeypatch.setattr(chat, "new_trace", lambda **k: {"timing": {}})
    monkeypatch.setattr(chat, "build_citations", lambda *a: [])
    monkeypatch.setattr(chat, "render_markdown", lambda *a: "一般版正文\n[⬇ 下載為 Word](https://sraf.example.test/ordinary)")
    monkeypatch.setattr(chat, "save_session_and_memory", lambda **k: events.append("session"))
    def save(**k):
        if identity["fail"]:
            raise RuntimeError("synthetic ordinary persistence failure")
        events.append("state")
    monkeypatch.setattr(chat.API_STORE, "save_all_throttled", save)
    def execute(**kw):
        events.append("ordinary")
        prompt = kw["payload"].messages[-1].content
        return AgentTurnResult("synthetic-session", "synthetic-turn", "synthetic-request",
            prompt, {"mode":identity["mode"],"answer":"ordinary"}, {},
            identity["receipt"] if kw.get("capture_ordinary_scope") else None)
    monkeypatch.setattr(chat, "execute_agent_turn", execute)
    monkeypatch.setattr(chat, "sign_resource", lambda *a, **k: "synthetic-word-signature")
    return TestClient(app), app, identity, events, auth


def post(client, key="turn-a", prompt=PROMPT, fmt="markdown"):
    headers = {} if key is None else {"Idempotency-Key":key}
    return client.post(URL, json={"messages":[{"role":"user","content":prompt}],"format":fmt},headers=headers)


def message(result):
    assert result.status_code == 200, result.text
    return result.json()["choices"][0]["message"]


def jobs(app):
    return app.state.report_job_store.list_owned_summaries(owner_kind="user", owner_id="owner")


def test_actual_chat_persists_then_admits_and_replays(http, monkeypatch):
    client, app, identity, events, _ = http
    from api.services import sraf_chat_deep_dispatch as dispatch
    real = dispatch.create_adaptive_job
    def checked(*a, **k):
        assert events[-4:] == ["ordinary","session","state","trace"]
        events.append("deep")
        return real(*a, **k)
    monkeypatch.setattr(dispatch, "create_adaptive_job", checked)
    m = message(post(client))
    deep = m["context"]["deep_report"]
    assert deep["status"] == "queued"
    assert deep["browser_status_url"] == "https://sraf.example.test/report-jobs#job=" + deep["job_id"]
    assert "一般版正文" in m["content"] and "下載為 Word" in m["content"]
    assert "排隊中" in m["content"] and deep["browser_status_url"] in m["content"]
    assert "synthetic-word-signature" in m["context"]["word_export"]["url"]
    assert "news_test" not in str(m) and "adaptive_owner_binding" not in str(m)
    assert NroundCheckpointStore(app.state.report_job_store.db_path).get_public(deep["job_id"])["state"] == "QUEUED"
    # Retry after ordinary session context exists: no new receipt or job.
    identity["receipt"] = None
    m2 = message(post(client))
    assert m2["context"]["deep_report"]["job_id"] == deep["job_id"]
    assert "沿用" in m2["content"] and len(jobs(app)) == 1
    changed = message(post(client,prompt=PROMPT+" "))
    assert "deep_report" not in changed["context"] and len(jobs(app)) == 1


@pytest.mark.parametrize("bad", ["missing","index","dates","terms","service","no_key","disabled","json","pure","unsupported","untrusted_base"])
def test_ordinary_unchanged_when_deep_not_admitted(http, bad):
    client, app, identity, events, _ = http
    key, prompt, fmt = "turn-a", PROMPT, "markdown"
    if bad == "missing":
        identity["receipt"] = None
    elif bad == "index":
        identity["receipt"] = replace(RECEIPT, indexes=("other_index",))
    elif bad == "dates":
        identity["receipt"] = replace(RECEIPT, date_to="2023-09-01")
    elif bad == "terms":
        identity["receipt"] = replace(RECEIPT, core_terms=("聯合國","北約"))
    elif bad == "service":
        identity["principal"] = AuthPrincipal("service","owner",None,REGISTERED_SCOPES,"synthetic")
    elif bad == "no_key":
        key = None
    elif bad == "disabled":
        app.state.deep_chat_auto_base_url = None
    elif bad == "json":
        fmt = "json"
    elif bad == "pure":
        identity["mode"] = "PURE_LLM"
    elif bad == "unsupported":
        prompt = "任意未核對問句"
    elif bad == "untrusted_base":
        app.state.deep_chat_auto_base_url = "https://example.test@evil.test"
    m = message(post(client,key=key,prompt=prompt,fmt=fmt))
    assert "deep_report" not in m["context"]
    assert "word_export" in m["context"] and not jobs(app)
    assert "report-jobs#job=" not in m["content"]


def test_queue_full_or_ordinary_failure_does_not_fake_deep_link(http):
    client, app, identity, events, _ = http
    for key in ("a","b"):
        assert "deep_report" in message(post(client,key=key))["context"]
    m = message(post(client,key="c"))
    assert "deep_report" not in m["context"] and "一般版正文" in m["content"]
    assert len(jobs(app)) == 2
    identity["fail"] = True
    assert post(client,key="d").status_code == 500
    assert len(jobs(app)) == 2


@pytest.mark.parametrize("base", [None,"javascript:alert(1)","https://x.test@evil.test","https://x.test/?token=secret",
    "https://x.test/#frag","https://x.test/../api","https://x.test/evil)","https://x.test:0"])
def test_auto_opt_in_requires_safe_explicit_public_base(base):
    env = valid()
    env["SRAF_DEEP_CHAT_AUTO_ENABLED"] = "1"
    if base is not None:
        env["PUBLIC_API_BASE"] = base
    with pytest.raises(DeepStartupConfigError):
        load_deep_startup_config(env)


def test_auto_disabled_by_default_and_safe_base_frozen():
    env = valid()
    assert load_deep_startup_config(env).chat_auto_base_url is None
    env.update(SRAF_DEEP_CHAT_AUTO_ENABLED="1", PUBLIC_API_BASE="http://127.0.0.1:9002/sraf/")
    assert load_deep_startup_config(env).chat_auto_base_url == "http://127.0.0.1:9002/sraf"
    env["PUBLIC_API_BASE"] = "http://[::1]:9002/"
    assert load_deep_startup_config(env).chat_auto_base_url == "http://[::1]:9002"
