"""OFF-1B configured API HTTP health is bounded, redacted and not acceptance."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading

import pytest

from tools import sraf_airgap_off1b_api_http as api
from tools.sraf_airgap_off1_probes import Observation


def _observation(status: str, reason: str, http_status: int | None = None) -> Observation:
    evidence = {"http_status": http_status} if http_status is not None else {}
    return Observation("API-01", "api-health", "healthz_http_only",
                       status, reason, True, evidence)


def test_api_http_uses_launcher_port_and_never_public_base(monkeypatch):
    ports: list[int] = []
    def fake(port: int) -> Observation:
        ports.append(port)
        return _observation("PASS", "healthz_http_200", 200)
    monkeypatch.setattr(api, "probe_api_health", fake)
    obs = api._observe({
        "_OFF1B_LAUNCHER_PORT": "9102",
        "PUBLIC_API_BASE": "https://10.12.13.14:4444",
        "ES_PASSWORD": "TOP_SECRET",
    }, no_network=False)
    assert ports == [9102]
    assert obs["config_key"] == "PORT"
    assert obs["http_status"] == 200
    assert obs["http_probe"] == "PASS"
    assert obs["service_identity"] == "NOT_TESTED"
    assert obs["worker_readiness"] == "NOT_TESTED"
    assert obs["feature_acceptance"] == "NOT_TESTED"
    encoded = json.dumps(obs)
    for sensitive in ("10.12.13.14", "4444", "TOP_SECRET"):
        assert sensitive not in encoded


@pytest.mark.parametrize("port", ("0", "-1", "abc", "65536", "9002;curl"))
def test_bad_shell_port_never_opens_network(monkeypatch, port):
    monkeypatch.setattr(api, "probe_api_health",
                        lambda *_: pytest.fail("bad bind port must not connect"))
    obs = api._observe({"_OFF1B_LAUNCHER_PORT": port}, no_network=False)
    assert obs["configuration"] == "INVALID"
    assert obs["http_probe"] == "SKIP"
    assert obs["http_status"] is None


def test_no_network_never_contacts_host(monkeypatch):
    monkeypatch.setattr(api, "probe_api_health",
                        lambda *_: pytest.fail("no-network must not contact host"))
    obs = api._observe({
        "_OFF1B_LAUNCHER_PORT": "9002",
        "PUBLIC_API_BASE": "http://192.168.0.134:9002",
    }, no_network=True)
    assert obs["http_probe"] == "SKIP"
    assert obs["reason"] == "network_disabled"
    assert obs["configuration"] == "RESOLVED"


@pytest.mark.parametrize(("status", "reason", "code"), [
    ("FAIL", "api_transport_unavailable", None),
    ("FAIL", "healthz_http_not_200", 503),
    ("FAIL", "healthz_http_not_200", 302),
])
def test_api_http_no_false_positive(monkeypatch, status, reason, code):
    monkeypatch.setattr(api, "probe_api_health",
                        lambda port: _observation(status, reason, code))
    obs = api._observe({}, no_network=False)
    assert obs["port"] == 9002
    assert obs["http_probe"] == "FAIL"
    assert obs["reason"] == reason
    assert obs["http_status"] == code
    assert obs["service_identity"] == "NOT_TESTED"


def test_api_http_sanitizes_unexpected_engine_exception(monkeypatch):
    def broken(_port):
        raise RuntimeError("SECRET origin=https://10.0.0.1:9999")
    monkeypatch.setattr(api, "probe_api_health", broken)
    obs = api._observe({}, no_network=False)
    assert obs["http_probe"] == "FAIL"
    assert obs["reason"] == "http_probe_internal_failure"
    assert "SECRET" not in json.dumps(obs)


def test_actual_bounded_get_against_ephemeral_loopback_health():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/healthz"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "11")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        obs = api._observe({
            "_OFF1B_LAUNCHER_PORT": str(server.server_port),
            "PUBLIC_API_BASE": "http://10.0.0.9:9999",
        }, no_network=False)
        thread.join(timeout=4)
    assert obs["http_probe"] == "PASS"
    assert obs["reason"] == "healthz_http_200"
    assert obs["http_status"] == 200
    assert obs["service_identity"] == "NOT_TESTED"


def test_cli_no_network_returns_incomplete_with_redacted_results(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "_effective_runtime_config",
                        lambda _: {"_OFF1B_LAUNCHER_PORT": "9002",
                                   "PUBLIC_API_BASE": "http://192.168.0.134:9002"})
    assert api.main(["--no-network"]) == 2
    output = capsys.readouterr().out
    doc = json.loads(output)
    assert doc["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert doc["results"][0]["http_probe"] == "SKIP"
    assert doc["network_mode"] == "CONFIG_ONLY"
    assert "192.168.0.134" not in output


def test_cli_completed_health_is_only_partial(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "_effective_runtime_config",
                        lambda _: {"_OFF1B_LAUNCHER_PORT": "9002"})
    monkeypatch.setattr(api, "probe_api_health",
                        lambda _: _observation("PASS", "healthz_http_200", 200))
    assert api.main([]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert doc["results"][0]["http_probe"] == "PASS"
    assert doc["results"][0]["worker_readiness"] == "NOT_TESTED"


def test_cli_requires_repository_root(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    assert api.main([]) == 2
    assert "run_from_repository_root" in capsys.readouterr().out


def test_cli_bootstrap_failure_is_redacted(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    def broken(_):
        raise RuntimeError("SECRET_PATH:/internal/deployment")
    monkeypatch.setattr(api, "_effective_runtime_config", broken)
    assert api.main(["--no-network"]) == 2
    output = capsys.readouterr().out
    assert "runtime_configuration_unavailable" in output
    assert "SECRET_PATH" not in output
