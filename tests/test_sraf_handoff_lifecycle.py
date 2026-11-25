"""Real API lifespan + optional socket listener; no real Agent/provider calls."""
import http.client
import json
import socket

import pytest
from fastapi.testclient import TestClient

from api.core import url_utils
from test_sraf_deep_lifespan import prepare
from test_sraf_handoff_config import fixture, load


def configure(tmp_path, monkeypatch, port, *, public_port=9002):
    app, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setenv("SRAF_DEEP_REPORT_ENABLED", "0")
    env, obj, path = fixture(tmp_path / "handoff")
    obj["listener"]["port"] = port
    path.write_text(json.dumps(obj), encoding="utf-8")
    load(env, tmp_path, require_replay=False).replay.initialize_new()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(url_utils, "PUBLIC_API_BASE", env["PUBLIC_API_BASE"])
    app.state.handoff_public_listener_port = public_port
    @app.get("/ordinary")
    def ordinary():
        return {"ok": True}
    return app


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def private_request(port, path="/v1/chat/completions", method="POST"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, b'{"messages":[{"role":"user","content":"fixture"}]}',
                     {"Content-Type": "application/json"})
        response = conn.getresponse()
        response.read()
        return response.status
    finally:
        conn.close()


def test_actual_listener_starts_stops_and_keeps_ordinary_api(tmp_path, monkeypatch):
    port = free_port()
    app = configure(tmp_path, monkeypatch, port)
    with TestClient(app) as client:
        runtime = app.state.handoff_listener_runtime
        assert app.state.handoff_listener_status == "RUNNING"
        assert runtime.accepting and runtime.server.started
        assert client.get("/ordinary").json() == {"ok": True}
        assert private_request(port) == 401
        assert private_request(port, "/ordinary", "GET") == 404
    assert app.state.handoff_listener_status == "STOPPED"
    assert runtime.task.done() and not runtime.accepting
    with pytest.raises(OSError):
        private_request(port)
    monkeypatch.setenv("SRAF_HANDOFF_ENABLED", "0")
    with TestClient(app) as client:
        assert app.state.handoff_listener_status == "DISABLED"
        assert app.state.handoff_listener_runtime is None
        assert client.get("/ordinary").status_code == 200


def test_occupied_port_isolated_from_ordinary_api(tmp_path, monkeypatch):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        app = configure(tmp_path, monkeypatch, port)
        with TestClient(app) as client:
            assert app.state.handoff_listener_status == "FAILED_CONFIG_OR_BIND"
            assert app.state.handoff_listener_runtime is None
            assert client.get("/ordinary").status_code == 200


@pytest.mark.parametrize("bad,expected", [
    ("same_port", "FAILED_CONFIG_OR_BIND"),
    ("unknown_launcher", "DISABLED_UNSUPPORTED_LAUNCHER"),
    ("missing_config", "FAILED_CONFIG_OR_BIND"),
])
def test_migration_errors_leave_public_api_usable(tmp_path, monkeypatch, bad, expected):
    port = free_port()
    app = configure(tmp_path, monkeypatch, port,
                    public_port=port if bad == "same_port" else 9002)
    if bad == "unknown_launcher":
        del app.state.handoff_public_listener_port
    elif bad == "missing_config":
        monkeypatch.setenv("SRAF_HANDOFF_CONFIG_FILE", str(tmp_path / "missing"))
    with TestClient(app) as client:
        assert app.state.handoff_listener_status == expected
        assert app.state.handoff_listener_runtime is None
        assert client.get("/ordinary").status_code == 200
    with pytest.raises(OSError):
        private_request(port)
