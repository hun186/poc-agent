"""Generated Pipe runs independently; synthetic upstream rows + real signature/socket.

This is a compatibility fixture for inspected v0.13.4 APIs, not installed
OpenWebUI/LLM/ES acceptance.
"""
import asyncio
import os
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
from threading import Thread
from types import ModuleType, SimpleNamespace

import pytest

from api.security.sraf_handoff_assertion import verify_chat_assertion
from test_sraf_handoff_assertion import KEY, trust
from tools.build_sraf_openwebui_backend_pipe import build


@pytest.fixture
def bundle(monkeypatch):
    module = ModuleType("sraf_pipe_bundle_test")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    source = build()
    assert "from api.security." not in source
    exec(compile(source, "bundle.py", "exec"), module.__dict__)
    return module


@pytest.fixture
def backend(monkeypatch):
    chat, mid, uid, user = "chat-123", "message-456", "root-user", "external-123"
    rows = {
        "user": SimpleNamespace(id=user, role="user"),
        "chat": SimpleNamespace(id=chat, user_id=user),
        "first": SimpleNamespace(id=f"{chat}-{uid}", chat_id=chat, user_id=user,
             role="user", parent_id=None, content="fixture", files=None, sources=None,
             embeds=None, output=None),
        "reply": SimpleNamespace(id=f"{chat}-{mid}", chat_id=chat, user_id=user,
             role="assistant", parent_id=uid, model_id="sraf-pipe", done=False,
             content="", output=None, files=None, sources=None, embeds=None, error=None),
    }
    async def get_user(id):
        return rows["user"]
    async def get_chat(id, user_id):
        return rows["chat"]
    async def get_message(id):
        return rows["first"] if id.endswith("-"+uid) else rows["reply"]
    for name, values in {
        "open_webui.env": {"VERSION": "0.13.4"},
        "open_webui.models.users": {"Users": SimpleNamespace(get_user_by_id=get_user)},
        "open_webui.models.chats": {"Chats": SimpleNamespace(get_chat_by_id_and_user_id=get_chat)},
        "open_webui.models.chat_messages": {"ChatMessages": SimpleNamespace(get_message_by_id=get_message)},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    args = {"body": {"model": "sraf-pipe", "messages": [{"role": "user", "content": "fixture"}],
                     "stream": True},
            "__user__": {"id": user}, "__chat_id__": chat, "__message_id__": mid,
            "__metadata__": {"user_id": user, "chat_id": chat, "message_id": mid,
                 "user_message_id": uid, "model_id": "sraf-pipe", "internal": False}}
    return rows, args


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            assertion = verify_chat_assertion(trust(), self.headers["X-SRAF-Backend-Assertion"],
                        body=raw, method=self.command, path=self.path)
            requests.append((assertion, json.loads(raw)))
            result = {"object": "chat.completion", "choices": [{"message": {
                "role": "assistant", "content": "fixture response"}}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        key = tmp_path / "issuer.key"
        key.write_bytes(base64.urlsafe_b64encode(KEY.secret).rstrip(b"="))
        key.chmod(0o600)
        config = tmp_path / "sender.json"
        config.write_text(json.dumps({
            "schema": "sraf_openwebui_sender_v1", "issuer": "webui-installation",
            "audience": "sraf-installation", "key_id": "current", "secret_file": "issuer.key",
            "transport": {"mode": "local_http", "origin": f"http://127.0.0.1:{server.server_port}",
                          "timeout_seconds": 10}}), encoding="utf-8")
        monkeypatch.setenv("SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE", str(config))
        monkeypatch.delenv("WEBUI_SECRET_KEY", raising=False)
        monkeypatch.delenv("ENABLE_VALVE_ENCRYPTION", raising=False)
        yield requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_generated_bundle_real_signed_request_without_personal_valves(bundle, backend, endpoint):
    _, args = backend
    pipe = bundle.Pipe()
    assert not hasattr(pipe, "UserValves")
    with pytest.raises(bundle.PipeError):
        asyncio.run(pipe.pipe(**args))
    pipe.valves.ENABLED = True
    assert asyncio.run(pipe.pipe(**args)) == "fixture response"
    assert len(endpoint) == 1
    proof, payload = endpoint[0]
    assert (proof.external_subject, proof.chat_id, proof.message_id) == (
        "external-123", "chat-123", "message-456")
    assert payload["messages"] == [{"role": "user", "content": "fixture"}]
    assert payload["stream"] is False
    args["body"]["stream"] = False
    assert asyncio.run(pipe.pipe(**args))["object"] == "chat.completion"
    assert endpoint[1][0].nonce != proof.nonce


@pytest.mark.parametrize("bad", ["foreign_chat", "foreign_message", "wrong_parent", "wrong_text",
    "history", "system", "task", "tools", "different_metadata", "done", "pending_user", "version"])
def test_rejects_unverified_context_before_transport(bundle, backend, endpoint, bad, monkeypatch):
    rows, args = backend
    if bad == "foreign_chat":
        rows["chat"].user_id = "other"
    elif bad == "foreign_message":
        rows["reply"].chat_id = "other"
    elif bad == "wrong_parent":
        rows["reply"].parent_id = "another"
    elif bad == "wrong_text":
        rows["first"].content = "other"
    elif bad == "history":
        args["body"]["messages"].append({"role": "user", "content": "next"})
    elif bad == "system":
        args["body"]["messages"].insert(0, {"role": "system", "content": "context"})
    elif bad == "task":
        args["__task__"] = "title_generation"
    elif bad == "tools":
        args["__tools__"] = {"tool": "fixture"}
    elif bad == "different_metadata":
        args["__metadata__"]["user_id"] = "other"
    elif bad == "done":
        rows["reply"].done = True
    elif bad == "pending_user":
        rows["user"].role = "pending"
    else:
        monkeypatch.setattr(sys.modules["open_webui.env"], "VERSION", "0.13.5")
    pipe = bundle.Pipe()
    pipe.valves.ENABLED = True
    with pytest.raises(bundle.PipeError):
        asyncio.run(pipe.pipe(**args))
    assert endpoint == []


def test_admin_file_path_works_without_container_env_change(bundle, backend, endpoint, monkeypatch):
    _, args = backend
    path = os.environ["SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE"]
    monkeypatch.delenv("SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE")
    pipe = bundle.Pipe()
    pipe.valves.ENABLED = True
    pipe.valves.CONFIG_FILE = path
    assert not hasattr(pipe, "UserValves")
    assert asyncio.run(pipe.pipe(**args)) == "fixture response"
    assert len(endpoint) == 1


def test_admin_file_conflict_and_relative_path_denied(bundle, backend, endpoint, tmp_path):
    _, args = backend
    pipe = bundle.Pipe()
    pipe.valves.ENABLED = True
    original = os.environ["SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE"]
    other = tmp_path / "other.json"
    other.write_text("{}", encoding="utf-8")
    for path in (str(other), "sender.json", " " + original):
        pipe.valves.CONFIG_FILE = path
        with pytest.raises(bundle.PipeError):
            asyncio.run(pipe.pipe(**args))
    assert endpoint == []
    pipe.valves.CONFIG_FILE = original
    assert asyncio.run(pipe.pipe(**args)) == "fixture response"
    assert len(endpoint) == 1
