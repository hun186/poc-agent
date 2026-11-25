"""Actual loopback HTTP/TLS sockets, no production provider or OpenWebUI calls."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import ssl
import subprocess
from threading import Thread

import pytest

from api.security.sraf_handoff_assertion import HandoffDenied, verify_chat_assertion
from api.security.sraf_handoff_transport import HandoffTransport, send_signed_chat
from test_sraf_handoff_assertion import BODY, trust


@pytest.mark.parametrize("mode,origin", [
    ("local_http", "http://192.168.1.4:9002"), ("local_http", "http://localhost:9002"),
    ("local_http", "http://127.0.0.2:9002"), ("local_http", "http://[::ffff:127.0.0.1]:9002"),
    ("local_http", "https://127.0.0.1:9002"), ("verified_https", "http://127.0.0.1:9002"),
    ("verified_https", "https://user:secret@es.example.test:9002"),
    ("verified_https", "https://example.test/api"), ("verified_https", "https://example.test?"),
    ("verified_https", "https://example.test:0"), ("verified_https", "https://example.test:"),
    ("verified_https", "https://example.test#x"), ("verified_https", "https://example.test\\x"),
    ("verified_https", "https://%31.example.test"), ("unknown", "https://example.test"),
])
def test_ambiguous_or_unprotected_origin_rejected(mode, origin):
    with pytest.raises(HandoffDenied, match="handoff_transport_invalid"):
        HandoffTransport(mode, origin)


@pytest.mark.parametrize("mode,origin,canonical", [
    ("local_http", "http://127.0.0.1:9002/", "http://127.0.0.1:9002"),
    ("local_http", "http://[::1]:9002", "http://[::1]:9002"),
    ("verified_https", "https://sraf.example.test/", "https://sraf.example.test:443"),
    ("verified_https", "https://192.168.30.1:9443", "https://192.168.30.1:9443"),
])
def test_operator_can_change_origin_without_changing_identity(mode, origin, canonical):
    assert HandoffTransport(mode, origin).origin == canonical


@contextmanager
def listener(*, status=200, tls=None):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            verified = verify_chat_assertion(trust(), self.headers["X-SRAF-Backend-Assertion"],
                body=body, method=self.command, path=self.path)
            received.append((body, verified.external_subject, verified.chat_id, verified.message_id))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if status == 302:
                self.send_header("Location", "http://127.0.0.1:1/redirect")
            self.end_headers()
            self.wfile.write(b'{"synthetic":true}')
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def send(transport):
    return send_signed_chat(transport, trust(), key_id="current",
                            external_subject="external-123", chat_id="chat-123",
                            message_id="message-456", body=BODY)


def test_real_loopback_sender_exact_bytes_and_no_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with listener() as (port, received):
        assert send(HandoffTransport("local_http", f"http://127.0.0.1:{port}")) == b'{"synthetic":true}'
        assert received == [(BODY, "external-123", "chat-123", "message-456")]


def test_redirect_denied_without_resending_assertion():
    with listener(status=302) as (port, received):
        with pytest.raises(HandoffDenied, match="handoff_transport_rejected"):
            send(HandoffTransport("local_http", f"http://127.0.0.1:{port}"))
        assert len(received) == 1


def test_real_https_requires_trusted_ca_and_matching_san(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl CLI required for temporary TLS fixture")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-days", "1", "-subj", "/CN=fixture.invalid", "-addext",
        "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True, timeout=30)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    with listener(tls=tls) as (port, received):
        with pytest.raises(HandoffDenied, match="handoff_transport_unavailable"):
            send(HandoffTransport("verified_https", f"https://127.0.0.1:{port}"))
        with pytest.raises(HandoffDenied, match="handoff_transport_unavailable"):
            send(HandoffTransport("verified_https", f"https://localhost:{port}", ca_file=cert))
        assert received == []
        assert send(HandoffTransport("verified_https", f"https://127.0.0.1:{port}",
                                     ca_file=cert)) == b'{"synthetic":true}'
        assert len(received) == 1
