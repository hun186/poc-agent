"""OFF-1 narrow real observations: fail-closed, bounded and no writes."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools import sraf_airgap_off1_probes as probes
from tools.validate_sraf_airgap_off0_contract import ContractError, make_report_record


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def http_site():
    routes: dict[str, tuple[int, bytes, dict[str, str]]] = {}
    requests: list[tuple[str, str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/slow-headers":
                # Continuously deliver response-header bytes more frequently
                # than the socket inactivity timeout, without finishing them.
                try:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    self.wfile.flush()
                    for _ in range(55):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.12)
                    self.wfile.write(b"\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if self.path == "/slow-body":
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                try:
                    for _ in range(60):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.12)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            status, body, headers = routes.get(self.path, (404, b"", {}))
            if "_chunked" in headers:
                coding = headers["_chunked"]
                raw_header = (
                    (headers.get("_status_version",
                                 "HTTP/1.0" if headers.get("_http10") else "HTTP/1.1") +
                     " " + str(status) + " OK\r\n" +
                     "Content-Type: application/json\r\n" +
                     "Transfer-Encoding: " + coding + "\r\n" +
                     ("Content-Length: " + str(len(body)) + "\r\n"
                      if headers.get("_with_length") else "") +
                     ("Transfer-Encoding: chunked\r\n"
                      if headers.get("_duplicate_coding") else "") +
                     "\r\n").encode("ascii")
                )
                # Raw malformed wire framing is not representable through
                # BaseHTTPRequestHandler.send_header(). Exercise the exact
                # bytes before http.client and email parsers normalize them.
                if headers.get("_lf_headers"):
                    raw_header = raw_header.replace(b"\r\n", b"\n")
                elif headers.get("_lf_status"):
                    raw_header = raw_header.replace(b"\r\n", b"\n", 1)
                elif headers.get("_lf_transfer"):
                    raw_header = raw_header.replace(
                        ("Transfer-Encoding: " + coding + "\r\n").encode("ascii"),
                        ("Transfer-Encoding: " + coding + "\n").encode("ascii"),
                        1,
                    )
                elif headers.get("_lf_terminator"):
                    raw_header = raw_header[:-2] + b"\n"
                middle = max(1, len(body) // 2)
                chunks = [body[:middle], body[middle:]]
                raw_body = b"".join(
                    ("%x\r\n" % len(chunk)).encode("ascii") + chunk +
                    (b"XX" if headers.get("_bad_delimiter") else b"\r\n")
                    for chunk in chunks if chunk
                )
                if headers.get("_omit_trailer_terminator"):
                    raw_body += b"0\r\n"
                elif not headers.get("_omit_terminal"):
                    if headers.get("_valid_trailer"):
                        raw_body += b"0\r\nX-Check: verified\r\n\r\n"
                    elif headers.get("_bad_trailer"):
                        raw_body += b"0\r\nX-Check : invalid\r\n\r\n"
                    else:
                        raw_body += b"0\r\n\r\n"
                try:
                    self.wfile.write(raw_header + raw_body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True
                return
            if ("_raw_extra_header" in headers or
                    "_interim_raw_header" in headers or
                    "_unframed_status_version" in headers or
                    "_raw_status_line" in headers or
                    "_interim_status_line" in headers):
                # Preserve intentionally invalid raw header bytes, including
                # NUL and malformed interim 100 Continue blocks. Normal
                # send_header() refuses/normalizes these cases.
                raw_status_version = headers.get("_unframed_status_version", "HTTP/1.1")
                status_line = headers.get(
                    "_raw_status_line", raw_status_version + " " +
                    str(status) + " OK",
                ).encode("latin-1")
                final = (
                    status_line + b"\r\n" +
                    b"Content-Type: application/json\r\n" +
                    ("Content-Length: " + str(len(body)) + "\r\n").encode("ascii")
                )
                if "_raw_extra_header" in headers:
                    final += headers["_raw_extra_header"].encode("latin-1") + b"\r\n"
                final += b"\r\n"
                interim = b""
                if "_interim_raw_header" in headers:
                    interim = (
                        headers.get("_interim_status_line",
                                    "HTTP/1.1 100 Continue").encode("latin-1") +
                        b"\r\n" +
                        headers["_interim_raw_header"].encode("latin-1") +
                        b"\r\n\r\n"
                    )
                try:
                    self.wfile.write(interim + final + body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True
                return
            if headers.get("_lf_unframed"):
                # Valid JSON with malformed bare-LF status/headers and a
                # syntactically valid Content-Length remains a transport error.
                raw_header = (
                    ("HTTP/1.1 " + str(status) + " OK\n" +
                     "Content-Type: application/json\n" +
                     "Content-Length: " + str(len(body)) + "\n\n").encode("ascii")
                )
                try:
                    self.wfile.write(raw_header + body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True
                return
            malformed = headers.get("_raw_malformed_header")
            if malformed is not None:
                # Emit raw response bytes: BaseHTTPRequestHandler.send_header
                # normalizes good headers and cannot model parser defects.
                self.wfile.write(
                    ("HTTP/1.1 " + str(status) + " OK\r\n" +
                     "Content-Type: application/json\r\n" +
                     malformed + "\r\n\r\n").encode("ascii") + body
                )
                self.wfile.flush()
                self.close_connection = True
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", headers.get("_declared_length", str(len(body))))
            for name, value in headers.items():
                if not name.startswith("_"):
                    self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def do_POST(self):
            requests.append(("POST", self.path, self.headers.get("Authorization")))
            self.send_error(405)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, routes, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def _json(payload):
    return json.dumps(payload).encode("utf-8")


def test_real_local_health_get_sends_no_auth_and_no_post(http_site):
    port, routes, requests = http_site
    routes["/healthz"] = (200, b'{"status":"ok"}', {})
    got = probes.probe_api_health(port)
    assert got.check_id == "API-01"
    assert got.aspect == "healthz_http_only"
    assert got.status == "PASS"
    assert got.executed is True
    assert got.evidence == {"http_status": 200}
    assert requests == [("GET", "/healthz", None)]
    assert got.serialize()["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


def test_health_rejects_500_and_does_not_echo_body(http_site):
    port, routes, _ = http_site
    routes["/healthz"] = (500, b"password=hunter2; secret=/etc/sra.conf", {})
    report = probes.probe_api_health(port)
    assert report.status == "FAIL"
    assert "hunter2" not in json.dumps(report.serialize())
    assert "/etc/" not in json.dumps(report.serialize())


def test_no_redirect_following_even_with_external_location(http_site):
    port, routes, requests = http_site
    routes["/healthz"] = (302, b"", {"Location": "http://example.invalid/steal"})
    got = probes.probe_api_health(port)
    assert got.status == "FAIL"
    assert got.evidence == {"http_status": 302}
    assert requests == [("GET", "/healthz", None)]


def test_response_body_is_bounded(http_site):
    port, routes, _ = http_site
    routes["/healthz"] = (200, b"x" * (probes.MAX_HTTP_BYTES + 100), {})
    got = probes.probe_api_health(port)
    assert got.status == "FAIL"
    assert got.reason == "api_response_oversized"


def test_es_anonymous_identity_really_checked(http_site):
    port, routes, requests = http_site
    routes["/"] = (200, _json({"cluster_name": "local", "version": {"number": "8.13.0"}}), {})
    got = probes.probe_es_transport(port)
    assert got.status == "PASS"
    assert got.aspect == "anonymous_http_reachability_only"
    assert got.evidence == {"http_status": 200}
    assert requests == [("GET", "/", None)]


@pytest.mark.parametrize("body", [
    b"<html>proxy splash</html>",
    b'{"ok":true}',
    b'{"cluster_name":"local","version":{"number":23}}',
    b"[" * 2500 + b"]" * 2500,
])
def test_es_not_fooled_by_http_200_without_identity(http_site, body):
    port, routes, _ = http_site
    routes["/"] = (200, body, {})
    got = probes.probe_es_transport(port)
    assert got.status == "FAIL"
    assert got.reason == "es_identity_unverified"


@pytest.mark.parametrize("code", [401, 403])
def test_es_auth_boundary_yields_incomplete_not_pass(http_site, code):
    port, routes, requests = http_site
    routes["/"] = (code, b"password=hunter2", {})
    got = probes.probe_es_transport(port)
    assert got.status == "SKIP"
    assert got.reason == "es_credentials_not_probed"
    assert requests == [("GET", "/", None)]
    assert "hunter2" not in json.dumps(got.serialize())


def test_es_does_not_follow_redirect(http_site):
    port, routes, requests = http_site
    routes["/"] = (302, b"", {"Location": "https://example.invalid"})
    assert probes.probe_es_transport(port).status == "FAIL"
    assert requests == [("GET", "/", None)]


def test_llm_model_inventory_ollama_real_get_no_generation(http_site):
    port, routes, requests = http_site
    routes["/api/tags"] = (200, _json({"models": [
        {"name": "qwen3:8b"}, {"name": "other:latest"}]}), {})
    got = probes.probe_llm_inventory(port, "qwen3:8b")
    assert got.status == "PASS"
    assert got.evidence == {"model_available": True, "item_count": 2, "http_status": 200}
    assert requests == [("GET", "/api/tags", None)]
    assert "qwen3:8b" not in json.dumps(got.serialize())


def test_llm_openai_model_list_and_exact_match(http_site):
    port, routes, requests = http_site
    routes["/v1/models"] = (200, _json({"data": [{"id": "model-a"}]}), {})
    assert probes.probe_llm_inventory(port, "model-a", "openai").status == "PASS"
    missing = probes.probe_llm_inventory(port, "model", "openai")
    assert missing.status == "FAIL"
    assert missing.reason == "configured_model_not_listed"
    assert requests == [("GET", "/v1/models", None)] * 2


@pytest.mark.parametrize("value", [
    b"<html/>", b'{"models":"bad"}', b'{"models":[null]}',
    _json({"models": [{"name": "one"}] * 1001}),
    b"[" * 2500 + b"]" * 2500,
])
def test_llm_invalid_inventory_never_passes(http_site, value):
    port, routes, _ = http_site
    routes["/api/tags"] = (200, value, {})
    got = probes.probe_llm_inventory(port, "target")
    assert got.status == "FAIL"
    assert got.reason == "model_inventory_invalid"


def test_llm_unconfigured_model_makes_no_request(http_site):
    port, _, requests = http_site
    got = probes.probe_llm_inventory(port, None)
    assert got.status == "SKIP"
    assert got.executed is False
    assert requests == []


def test_llm_auth_needed_is_not_success(http_site):
    port, routes, _ = http_site
    routes["/v1/models"] = (401, b"token=secret", {})
    got = probes.probe_llm_inventory(port, "some-model", "openai")
    assert got.status == "SKIP"
    assert "secret" not in json.dumps(got.serialize())


def test_llm_large_payload_is_bounded(http_site):
    port, routes, _ = http_site
    routes["/api/tags"] = (200, b" " * (probes.MAX_HTTP_BYTES + 1), {})
    got = probes.probe_llm_inventory(port, "model")
    assert got.reason == "model_inventory_oversized"


def test_host_disk_only_not_full_host_acceptance(monkeypatch):
    monkeypatch.setattr(probes.shutil, "disk_usage", lambda p: (10**10, 0, 1024**3))
    monkeypatch.setattr(probes.os, "cpu_count", lambda: 8)
    got = probes.probe_disk()
    assert got.status == "PASS"
    assert got.aspect == "disk_free_only"
    assert got.evidence == {"free_mib": 1024, "cpu_count": 8}


def test_host_disk_warn_on_low_space(monkeypatch):
    monkeypatch.setattr(probes.shutil, "disk_usage", lambda p: (10**9, 0, 100 * 1024**2))
    monkeypatch.setattr(probes.os, "cpu_count", lambda: 8)
    assert probes.probe_disk().status == "WARN"


def test_odbc_fixed_file_probe_does_not_emit_library_path(monkeypatch):
    monkeypatch.setattr(probes, "_odbc_platform_supported", lambda: True)
    observed = []
    def file_exists(path):
        observed.append(path)
        return path == probes.ODBC_LIBRARY_CANDIDATES[0]
    monkeypatch.setattr(probes, "_odbc_library_file_exists", file_exists)
    got = probes.probe_odbc_library()
    assert got.aspect == "native_odbc_library_discovery_only"
    assert got.status == "PASS"
    assert observed == [probes.ODBC_LIBRARY_CANDIDATES[0]]
    assert "usr/lib" not in json.dumps(got.serialize())


def test_odbc_missing_is_not_claimed_driver_present(monkeypatch):
    monkeypatch.setattr(probes, "_odbc_platform_supported", lambda: True)
    monkeypatch.setattr(probes, "_odbc_library_file_exists", lambda path: False)
    got = probes.probe_odbc_library()
    assert got.status == "WARN"
    assert got.evidence == {"odbc_library_found": False}


def test_odbc_discovery_checks_only_fixed_candidates_no_subprocess(monkeypatch):
    monkeypatch.setattr(probes, "_odbc_platform_supported", lambda: True)
    seen = []
    def check(path):
        seen.append(path)
        return False
    monkeypatch.setattr(probes, "_odbc_library_file_exists", check)
    got = probes.probe_odbc_library()
    assert got.status == "WARN"
    assert seen == list(probes.ODBC_LIBRARY_CANDIDATES)
    assert all(path.startswith(("/usr/", "/lib/", "/opt/homebrew/"))
               for path in seen)


def test_odbc_file_probe_unsupported_platform_skips_not_passes(monkeypatch):
    monkeypatch.setattr(probes, "_odbc_platform_supported", lambda: False)
    monkeypatch.setattr(probes, "_odbc_library_file_exists",
                        lambda path: pytest.fail("no file checks on unsupported OS"))
    result = probes.probe_odbc_library()
    assert result.status == "SKIP"
    assert result.executed is False


def test_cli_requires_explicit_check_and_diagnose_mode(capsys, monkeypatch):
    monkeypatch.setattr(probes, "_http_get",
                        lambda port, path: pytest.fail("unexpected network"))
    assert probes.main(["--check", "llm-inventory"]) == 2
    got = json.loads(capsys.readouterr().out)
    assert got["reason"] == "diagnose_mode_required"
    assert got["executed"] is False


def test_cli_mode_gate_even_with_model_name(capsys, monkeypatch):
    monkeypatch.setattr(probes, "_http_get",
                        lambda port, path: pytest.fail("unexpected network"))
    assert probes.main(["--check", "llm-inventory", "--model-name", "secret"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "SKIP"


@pytest.mark.parametrize("bad", ["0", "-4", "65536", "xyz"])
def test_cli_rejects_invalid_ports(bad):
    with pytest.raises(SystemExit) as error:
        probes.main(["--check", "sys-disk", "--api-port", bad])
    assert error.value.code == 2


def test_cli_real_local_http_and_exit_code(http_site, capsys):
    port, routes, _ = http_site
    routes["/healthz"] = (200, b"{}", {})
    assert probes.main(["--check", "api-health", "--api-port", str(port)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["status"] == "PASS"
    assert got["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


def test_off0_safe_record_boundary_still_refuses_proofless_pass():
    registry = json.loads(
        (ROOT / "docs/operations/sraf_airgap_off0_checks.v1.json").read_text()
    )
    with pytest.raises(ContractError, match="report_pass_probe_not_implemented"):
        make_report_record(registry, "API-01", "PASS", evidence={"http_status": 200})


def test_standalone_cli_non_mutating_status_not_full_acceptance():
    finished = subprocess.run(
        [sys.executable, "tools/sraf_airgap_off1_probes.py",
         "--check", "llm-inventory"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=10,
    )
    assert finished.returncode == 2
    payload = json.loads(finished.stdout)
    assert payload["status"] == "SKIP"
    assert payload["executed"] is False
    assert payload["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert finished.stderr == ""


@pytest.mark.parametrize("path", ["/slow-headers", "/slow-body"])
def test_absolute_three_second_deadline_beats_continuous_byte_drip(http_site, path):
    port, _, requests = http_site
    started = time.monotonic()
    status, body = probes._http_get(port, path)
    duration = time.monotonic() - started
    assert (status, body) == (None, None)
    assert duration < probes.TIMEOUT_SECONDS + 1.5
    assert duration >= probes.TIMEOUT_SECONDS - 0.6
    assert requests == [("GET", path, None)]


def test_deadline_is_rechecked_between_socket_reads(monkeypatch):
    clock = {"now": 12.5}
    monkeypatch.setattr(probes.time, "monotonic", lambda: clock["now"])
    sock = probes._DeadlineSocket(deadline=13.0)
    try:
        sock._enforce_deadline()
        assert 0 < sock.gettimeout() <= 0.5
        clock["now"] = 13.001
        with pytest.raises(TimeoutError, match="probe_deadline_exceeded"):
            sock._enforce_deadline()
    finally:
        sock.close()


def test_http_connection_uses_deadline_socket_instead_of_default_factory(http_site):
    port, _, _ = http_site
    conn = probes._DeadlineHTTPConnection(port, deadline=time.monotonic() + 3)
    try:
        conn.connect()
        assert isinstance(conn.sock, probes._DeadlineSocket)
    finally:
        conn.close()


@pytest.mark.parametrize(("path", "kind"), [
    ("/", "es"), ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_truncated_declared_content_length_cannot_make_partial_probe_pass(
    http_site, path, kind,
):
    port, routes, _ = http_site
    body = (_json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_declared_length": str(len(body) + 7)})
    observation = (probes.probe_es_transport(port) if kind == "es" else
                   probes.probe_llm_inventory(port, "model-a",
                                              "ollama" if kind == "ollama" else "openai"))
    assert observation.status == "FAIL"
    assert observation.reason in ("es_transport_unavailable", "model_service_unavailable")
    assert observation.evidence == {}


@pytest.mark.parametrize("cluster,version", [
    ("", "8.13.0"), ("  ", "8.13.0"),
    ("local", ""), ("local", "\t"),
])
def test_es_identity_rejects_blank_names_or_versions(http_site, cluster, version):
    port, routes, _ = http_site
    routes["/"] = (200, _json({"cluster_name": cluster,
                               "version": {"number": version}}), {})
    got = probes.probe_es_transport(port)
    assert got.status == "FAIL"
    assert got.reason == "es_identity_unverified"


@pytest.mark.parametrize(("declared_length", "extra_headers"), [
    ("-1", {}),
    ("not-a-number", {}),
    ("+12", {}),
    ("12.0", {}),
    ("5, 5", {}),
    ("1e2", {}),
    ("9999999999999999999999999999999999", {}),
    ("0", {"Content-Length": "20"}),
    ("0", {"Transfer-Encoding": "chunked"}),
])
@pytest.mark.parametrize(("path", "kind"), [
    ("/", "es"),
    ("/api/tags", "ollama"),
    ("/v1/models", "openai"),
])
def test_invalid_or_duplicate_content_length_never_confirms_service(
    http_site, declared_length, extra_headers, path, kind,
):
    port, routes, requests = http_site
    body = (_json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_declared_length": declared_length, **extra_headers})
    observation = (probes.probe_es_transport(port) if kind == "es"
                   else probes.probe_llm_inventory(
                       port, "model-a", "ollama" if kind == "ollama" else "openai",
                   ))
    assert observation.status == "FAIL"
    assert observation.reason in ("es_transport_unavailable", "model_service_unavailable")
    assert observation.evidence == {}
    assert requests == [("GET", path, None)]


def test_valid_content_length_optional_ascii_whitespace_is_accepted(http_site):
    port, routes, _ = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_declared_length": "  " + str(len(body)) + " \t"})
    assert probes.probe_es_transport(port).status == "PASS"


@pytest.mark.parametrize("malformed_header", [
    "Content-Length : -1",
    "Content-Length : 999",
    "Transfer-Encoding : chunked",
    "NoColonHeader",
])
@pytest.mark.parametrize(("path", "kind"), [
    ("/", "es"),
    ("/api/tags", "ollama"),
    ("/v1/models", "openai"),
    ("/healthz", "health"),
])
def test_discarded_malformed_raw_headers_cannot_claim_probe_pass(
    http_site, malformed_header, path, kind,
):
    port, routes, requests = http_site
    body = (_json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}) if kind == "openai"
            else b'{"status":"ok"}')
    routes[path] = (200, body, {"_raw_malformed_header": malformed_header})
    observation = (probes.probe_es_transport(port) if kind == "es" else
                   probes.probe_llm_inventory(port, "model-a", "ollama")
                   if kind == "ollama" else
                   probes.probe_llm_inventory(port, "model-a", "openai")
                   if kind == "openai" else probes.probe_api_health(port))
    assert observation.status == "FAIL"
    assert observation.reason in (
        "es_transport_unavailable", "model_service_unavailable",
        "api_transport_unavailable",
    )
    assert observation.evidence == {}
    assert requests == [("GET", path, None)]


def test_well_formed_content_length_absent_http_response_can_be_observed(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_raw_malformed_header": "X-Valid: yes"})
    # Deliberate close-delimited HTTP/1.1: no Content-Length and no parser
    # defect. This remains legitimate; the negative tests above distinguish.
    result = probes.probe_es_transport(port)
    assert result.status == "PASS"
    assert requests == [("GET", "/", None)]


@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_valid_http11_chunked_get_probes_pass_with_bounded_decoding(
    http_site, path, kind,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama" else
            _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_chunked": "chunked"})
    result = (
        probes.probe_api_health(port) if kind == "api" else
        probes.probe_es_transport(port) if kind == "es" else
        probes.probe_llm_inventory(port, "model-a",
                                   "ollama" if kind == "ollama" else "openai")
    )
    assert result.status == "PASS"
    assert result.executed is True
    assert requests == [("GET", path, None)]
    assert "model-a" not in json.dumps(result.serialize())


@pytest.mark.parametrize("headers", [
    {"_chunked": "chunked", "_with_length": "yes"},
    {"_chunked": "chunked", "_duplicate_coding": "yes"},
    {"_chunked": "gzip"},
    {"_chunked": "gzip, chunked"},
    {"_chunked": "chunked;invalid"},
])
@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_ambiguous_unsupported_transfer_encoding_never_passes(
    http_site, headers, path, kind,
):
    port, routes, _ = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama" else
            _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, headers)
    result = (
        probes.probe_api_health(port) if kind == "api" else
        probes.probe_es_transport(port) if kind == "es" else
        probes.probe_llm_inventory(port, "model-a",
                                   "ollama" if kind == "ollama" else "openai")
    )
    assert result.status == "FAIL"
    assert result.evidence == {}


def test_truncated_chunked_response_does_not_pass_even_with_valid_json(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_chunked": "chunked", "_omit_terminal": "yes"})
    result = probes.probe_es_transport(port)
    assert result.status == "FAIL"
    assert result.reason == "es_transport_unavailable"
    assert requests == [("GET", "/", None)]


def test_legitimate_uppercase_chunked_token_accepted(http_site):
    port, routes, _ = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_chunked": "CHUNKED"})
    assert probes.probe_es_transport(port).status == "PASS"


@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
@pytest.mark.parametrize("malformed", [
    {"_bad_delimiter": "yes"},
    {"_omit_trailer_terminator": "yes"},
    {"_bad_trailer": "yes"},
    {"_http10": "yes"},
])
def test_chunked_corrupt_delimiter_trailer_or_http10_never_passes(
    http_site, path, kind, malformed,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama" else
            _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_chunked": "chunked", **malformed})
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(
               port, "model-a", "ollama" if kind == "ollama" else "openai",
           ))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


@pytest.mark.parametrize(("path", "kind"), [
    ("/", "es"), ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_legitimate_chunked_trailer_is_fully_consumed(
    http_site, path, kind,
):
    port, routes, _ = http_site
    body = (_json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_chunked": "chunked", "_valid_trailer": "yes"})
    got = (probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(
               port, "model-a", "ollama" if kind == "ollama" else "openai",
           ))
    assert got.status == "PASS"


def test_chunked_oversized_body_stays_bounded_and_cannot_pass(http_site):
    port, routes, _ = http_site
    body = b"x" * (probes.MAX_HTTP_BYTES + 100)
    routes["/healthz"] = (200, body, {"_chunked": "chunked"})
    result = probes.probe_api_health(port)
    assert result.status == "FAIL"
    assert result.reason == "api_response_oversized"


@pytest.mark.parametrize("status_version", [
    "HTTP/1.2", "HTTP/1.X", "HTTP/1.9", "HTTP/1.invalid",
])
@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_normalized_http11_response_version_cannot_bypass_literal_check(
    http_site, status_version, path, kind,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama" else
            _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_chunked": "chunked",
                                "_status_version": status_version})
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(port, "model-a",
                                      "ollama" if kind == "ollama" else "openai"))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


def test_raw_http11_version_is_captured_before_normalization(http_site):
    port, routes, _ = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_chunked": "chunked",
                               "_status_version": "HTTP/1.1"})
    conn = probes._DeadlineHTTPConnection(port, deadline=time.monotonic() + 3)
    try:
        conn.request("GET", "/")
        response = conn.getresponse()
        assert response.raw_status_version == "HTTP/1.1"
        assert response.version == 11
    finally:
        conn.close()


def test_raw_http12_status_version_is_rejected_before_normalization(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_chunked": "chunked",
                               "_status_version": "HTTP/1.2"})
    conn = probes._DeadlineHTTPConnection(port, deadline=time.monotonic() + 3)
    try:
        conn.request("GET", "/")
        # Raw wire-format validation intentionally rejects unsupported
        # versions before stdlib's status-version normalization occurs.
        with pytest.raises(probes.http.client.HTTPException,
                           match="http_status_line_invalid"):
            conn.getresponse()
        assert requests == [("GET", "/", None)]
    finally:
        conn.close()


@pytest.mark.parametrize("bad_header", [
    {"_lf_headers": "yes"},
    {"_lf_status": "yes"},
    {"_lf_transfer": "yes"},
    {"_lf_terminator": "yes"},
])
@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"),
    ("/", "es"),
    ("/api/tags", "ollama"),
    ("/v1/models", "openai"),
])
def test_bare_lf_in_status_or_headers_rejected_even_with_valid_chunks(
    http_site, bad_header, path, kind,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_chunked": "chunked", **bad_header})
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(port, "model-a",
                                      "ollama" if kind == "ollama" else "openai"))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"),
    ("/", "es"),
    ("/api/tags", "ollama"),
    ("/v1/models", "openai"),
])
def test_lf_only_headers_with_valid_content_length_rejected(
    http_site, path, kind,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_lf_unframed": "yes"})
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(port, "model-a",
                                      "ollama" if kind == "ollama" else "openai"))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


def test_strict_header_guard_restores_buffered_stream_for_body_read(http_site):
    port, routes, _ = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {})
    assert probes.probe_es_transport(port).status == "PASS"
    routes["/"] = (200, body, {"_chunked": "chunked",
                               "_valid_trailer": "yes"})
    assert probes.probe_es_transport(port).status == "PASS"


@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
@pytest.mark.parametrize("bad_header", [
    {"_raw_extra_header": "X-Test: a\x00b"},
    {"_raw_extra_header": "X-Test: a\x01b"},
    {"_raw_extra_header": "Bad Header"},
    {"_raw_extra_header": "Bad Header: value"},
    {"_raw_extra_header": " X-Test: folded-value"},
    {"_raw_extra_header": "X-Test : invalid"},
    {"_interim_raw_header": "Bad Header"},
    {"_interim_raw_header": "X-Test: a\x00b"},
    {"_interim_raw_header": "X-Test : invalid"},
])
def test_raw_header_field_syntax_fails_closed_for_final_and_interim(
    http_site, path, kind, bad_header,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, bad_header)
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(port, "model-a",
                                      "ollama" if kind == "ollama" else "openai"))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


@pytest.mark.parametrize("raw_version", ["HTTP/1.2", "HTTP/1.X", "HTTP/1.9", "HTTP/0.9"])
@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_bad_raw_status_versions_rejected_for_content_length_responses(
    http_site, raw_version, path, kind,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama"
            else _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_unframed_status_version": raw_version})
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(port, "model-a",
                                      "ollama" if kind == "ollama" else "openai"))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


def test_valid_interim_100_header_and_final_identity_still_pass(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_interim_raw_header": "X-Interim: yes"})
    assert probes.probe_es_transport(port).status == "PASS"
    assert requests == [("GET", "/", None)]


def test_valid_obs_text_header_field_remains_parseable(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {"_raw_extra_header": "X-Label: caf\xe9"})
    assert probes.probe_es_transport(port).status == "PASS"
    assert requests == [("GET", "/", None)]


@pytest.mark.parametrize("bad_status", [
    "HTTP/1.1 200 O\x00K",
    "HTTP/1.1 200 O\x01K",
    "HTTP/1.1 200 O\x7fK",
    "HTTP/1.1 200 O\x0bK",
    "HTTP/1.1 200 O\rK",
    "HTTP/1.1 200 O\nK",
])
@pytest.mark.parametrize(("path", "kind"), [
    ("/healthz", "api"), ("/", "es"),
    ("/api/tags", "ollama"), ("/v1/models", "openai"),
])
def test_raw_status_reason_control_bytes_cannot_confirm_service(
    http_site, bad_status, path, kind,
):
    port, routes, requests = http_site
    body = (b'{"status":"ok"}' if kind == "api" else
            _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
            if kind == "es" else
            _json({"models": [{"name": "model-a"}]}) if kind == "ollama" else
            _json({"data": [{"id": "model-a"}]}))
    routes[path] = (200, body, {"_raw_status_line": bad_status})
    got = (probes.probe_api_health(port) if kind == "api" else
           probes.probe_es_transport(port) if kind == "es" else
           probes.probe_llm_inventory(port, "model-a",
                                      "ollama" if kind == "ollama" else "openai"))
    assert got.status == "FAIL"
    assert got.evidence == {}
    assert requests == [("GET", path, None)]


def test_raw_interim_100_continue_status_control_byte_cannot_pass(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {
        "_interim_raw_header": "X-Interim: fine",
        "_interim_status_line": "HTTP/1.1 100 Cont\x00inue",
    })
    got = probes.probe_es_transport(port)
    assert got.status == "FAIL"
    assert got.reason == "es_transport_unavailable"
    assert requests == [("GET", "/", None)]


def test_raw_status_line_normal_valid_reason_phrase_still_accepted(http_site):
    port, routes, requests = http_site
    body = _json({"cluster_name": "local", "version": {"number": "8.13.0"}})
    routes["/"] = (200, body, {
        "_raw_status_line": "HTTP/1.1 200 All Good",
    })
    got = probes.probe_es_transport(port)
    assert got.status == "PASS"
    assert requests == [("GET", "/", None)]
