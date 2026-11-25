"""Standalone sender diagnostics, actual read-only HTTP/TLS; no provider or DB."""
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import ssl
import subprocess
from threading import Thread

import pytest

from test_sraf_handoff_assertion import KEY
from test_sraf_openwebui_backend_pipe import bundle


@contextmanager
def endpoint(status=405, allow="POST", tls=None):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, dict(self.headers)))
            self.send_response(status)
            if allow:
                self.send_header("Allow", allow)
            if status == 302:
                self.send_header("Location", "http://127.0.0.1:1/other")
            self.end_headers()
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def configure(tmp_path, monkeypatch, origin, ca=None):
    secret = tmp_path / "issuer.key"
    secret.write_bytes(base64.urlsafe_b64encode(KEY.secret).rstrip(b"="))
    secret.chmod(0o600)
    transport = {"mode": "verified_https" if origin.startswith("https:") else "local_http",
                 "origin": origin, "timeout_seconds": 300}
    if ca:
        transport["ca_file"] = ca.name
    config = tmp_path / "sender.json"
    config.write_text(json.dumps({
        "schema": "sraf_openwebui_sender_v1", "issuer": "webui-installation",
        "audience": "sraf-installation", "key_id": "current", "secret_file": secret.name,
        "transport": transport,
    }), encoding="utf-8")
    monkeypatch.setenv("SRAF_OPENWEBUI_HANDOFF_CONFIG_FILE", str(config))


def output(bundle, capsys, args, code):
    assert bundle.sender_preflight(args) == code
    raw = capsys.readouterr().out
    for private in ("127.0.0.1", "issuer.key", "webui-installation", "AAAA"):
        assert private not in raw
    result = json.loads(raw)
    assert result["signed_request_sent"] is False and result["job_created"] is False
    assert result["account_mapping"] == result["live_report"] == "NOT_TESTED"
    return result


def test_local_config_only_does_not_contact_listener(bundle, tmp_path, monkeypatch, capsys):
    with endpoint() as (port, seen):
        configure(tmp_path, monkeypatch, f"http://127.0.0.1:{port}")
        assert output(bundle, capsys, [], 2)["status"] == "NOT_TESTED"
        result = output(bundle, capsys, ["--check-config"], 2)
        assert result["status"] == "PASS_PARTIAL" and result["transport"] == "NOT_TESTED"
        assert not seen
        result = output(bundle, capsys, ["--probe-transport"], 2)
        assert result["status"] == "PASS_PARTIAL"
        assert result["route_observation"] == "GET_405_ALLOW_POST"
        assert result["transport"] == "LITERAL_LOOPBACK_HTTP"
        assert len(seen) == 1 and seen[0][0] == "/v1/chat/completions"
        headers = {key.lower() for key in seen[0][1]}
        assert not headers & {"authorization", "cookie", "x-sraf-backend-assertion"}


@pytest.mark.parametrize("status,allow", [(200, "POST"), (302, "POST"), (405, "GET"), (404, None)])
def test_wrong_route_or_redirect_not_pass(bundle, tmp_path, monkeypatch, capsys, status, allow):
    with endpoint(status, allow) as (port, seen):
        configure(tmp_path, monkeypatch, f"http://127.0.0.1:{port}")
        assert output(bundle, capsys, ["--probe-transport"], 1)["status"] == "FAIL"
        assert len(seen) == 1


def test_tls_probe_must_verify_ca_and_san(bundle, tmp_path, monkeypatch, capsys):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl required for temporary TLS fixture")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-days", "1", "-subj", "/CN=fixture.invalid",
                    "-addext", "subjectAltName=IP:127.0.0.1",
                    "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True, timeout=30)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    with endpoint(tls=tls) as (port, seen):
        configure(tmp_path, monkeypatch, f"https://127.0.0.1:{port}")
        assert output(bundle, capsys, ["--probe-transport"], 1)["status"] == "FAIL"
        configure(tmp_path, monkeypatch, f"https://localhost:{port}", cert)
        assert output(bundle, capsys, ["--probe-transport"], 1)["status"] == "FAIL"
        assert not seen
        configure(tmp_path, monkeypatch, f"https://127.0.0.1:{port}", cert)
        result = output(bundle, capsys, ["--probe-transport"], 2)
        assert result["transport"] == "TLS_CA_HOST_VERIFIED"
        assert len(seen) == 1
