"""Actual private ASGI route and Chat/SQLite path with synthetic ordinary Agent."""
import asyncio
from dataclasses import replace
import json
import time

import httpx
import pytest

from api.core import url_utils
from api.routers import chat
from api.security.sraf_handoff_assertion import HandoffDenied
from api.security.sraf_handoff_ingress import HandoffListener, build_private_ingress
from api.security.sraf_handoff_mapping import ExternalAccountBinding, HandoffSubjectMap
from api.security.sraf_handoff_replay import HandoffReplayStore
from test_sraf_handoff_assertion import sign, trust
from test_sraf_chat_deep_dispatch import http, jobs, PROMPT, URL


@pytest.fixture
def ingress(http, tmp_path, monkeypatch):
    client, app, identity, events, auth = http
    monkeypatch.setattr(url_utils, "PUBLIC_API_BASE", "https://sraf.example.test")
    replay = HandoffReplayStore(tmp_path / "handoff-ingress.db")
    replay.initialize()
    mapping = HandoffSubjectMap(tuple(
        ExternalAccountBinding("webui-installation", "sraf-installation", external, owner,
                               auth.get_user(owner)["created_at"])
        for external, owner in (("external-123", "owner"), ("external-456", "other"))))
    config = build_private_ingress(app, HandoffListener("local_http", "127.0.0.1", 19002),
                                   trust(), mapping, replay)
    actual = chat.execute_agent_turn
    scopes = []
    def execute(**kw):
        scoped = kw["scoped_chat_session"]
        scopes.append(scoped.key)
        return replace(actual(**kw), session_id=scoped.key)
    monkeypatch.setattr(chat, "execute_agent_turn", execute)
    return config, app, identity, events, auth, client, scopes


def request(ingress, body, *, token=None, headers=(), path=URL, method="POST",
            peer="127.0.0.1", base="http://127.0.0.1:19002"):
    async def run():
        transport = httpx.ASGITransport(app=ingress[0].app, client=(peer, 1234))
        async with httpx.AsyncClient(transport=transport, base_url=base) as client:
            args = [("content-type", "application/json"), *headers]
            if token is not None:
                args.append(("x-sraf-backend-assertion", token))
            return await client.request(method, path, content=body, headers=args)
    return asyncio.run(run())


def payload(text=PROMPT):
    return json.dumps({"messages": [{"role": "user", "content": text}]},
                      ensure_ascii=False).encode()


def assertion(body, **kw):
    return sign(body=body, now=int(time.time()), **kw)


def test_private_route_actual_chat_ordinary_and_deep_retry(ingress):
    config, app, identity, events, auth, public, scopes = ingress
    assert config.host == "127.0.0.1" and not config.proxy_headers
    assert config.lifespan == "off" and not config.access_log
    assert config.app.state is app.state
    raw = payload()
    token = assertion(raw)
    response = request(ingress, raw, token=token)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    msg = response.json()["choices"][0]["message"]
    deep = msg["context"]["deep_report"]
    assert msg["context"]["word_export"]["session_id"] == scopes[-1]
    assert msg["context"]["word_export"]["url"].startswith("https://sraf.example.test/")
    assert deep["browser_status_url"].startswith("https://sraf.example.test/")
    assert len(jobs(app)) == 1 and events[:4] == ["ordinary", "session", "state", "trace"]
    assert request(ingress, raw, token=token).status_code == 401
    identity["receipt"] = None
    retry = request(ingress, raw, token=assertion(raw))
    assert retry.status_code == 200
    assert retry.json()["choices"][0]["message"]["context"]["deep_report"]["job_id"] == deep["job_id"]
    assert len(jobs(app)) == 1 and scopes[0] == scopes[1]
    # Existing public route does not accept the assertion even with its
    # ordinary auth dependency overridden to a valid user.
    assert public.post(URL, content=raw, headers={
        "content-type": "application/json", "x-sraf-backend-assertion": assertion(raw)
    }).status_code == 400


def test_private_route_denies_forged_channel_and_mixed_credentials(ingress):
    raw = payload()
    token = assertion(raw)
    assert request(ingress, raw, token=token, peer="192.168.1.3").status_code == 403
    assert request(ingress, raw, token=token, base="https://127.0.0.1:19002").status_code == 403
    assert request(ingress, raw, token=token, headers=[("x-forwarded-proto", "https")]).status_code == 403
    assert request(ingress, raw, token=token, headers=[("authorization", "Bearer fake")]).status_code == 401
    assert request(ingress, raw, token=token, headers=[("idempotency-key", "forged")]).status_code == 401
    assert request(ingress, raw, token=None).status_code == 401
    assert request(ingress, raw, token=token, path=URL+"?user=owner").status_code == 403
    assert request(ingress, raw, token=token, path="/v1/report/jobs").status_code == 404
    assert request(ingress, raw, token=token, path=URL, method="GET").status_code == 405
    assert not ingress[3] and not jobs(ingress[1])
    assert request(ingress, raw, token=token).status_code == 200


@pytest.mark.parametrize("raw", [
    b'{"messages":[{"role":"system","content":"x"},{"role":"user","content":"y"}]}',
    b'{"messages":[{"role":"user","content":"x"}],"stream":true}',
    b'{"messages":[{"role":"user","content":"x"}],"user":"owner"}',
    b'{"messages":[{"role":"user","content":"x","role":"assistant"}]}',
    b'{"messages":[{"role":"user","content":[{"type":"text","text":"x"}]}]}',
])
def test_private_route_rejects_unsupported_payload_without_agent(ingress, raw):
    result = request(ingress, raw, token=assertion(raw))
    assert result.status_code == 400
    assert not ingress[3]


def test_listener_rejects_unprotected_wildcard_and_invalid_tls():
    for args in (("local_http", "0.0.0.0", 19002),
                 ("local_http", "192.168.1.3", 19002),
                 ("local_http", "localhost", 19002),
                 ("verified_https", "0.0.0.0", 19002)):
        with pytest.raises(HandoffDenied):
            HandoffListener(*args)
