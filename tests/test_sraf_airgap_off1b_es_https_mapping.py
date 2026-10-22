"""OFF-1B ES HTTPS/mapping: safe configuration, redaction and mapping parity."""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from agent.es.mock_es_client import REQUIREMENT_E2E_INDEX, REQUIREMENT_E2E_MAPPING
from tools import sraf_airgap_off1b_es_https_mapping as es


def _ca(tmp_path):
    cert = tmp_path / "agent" / "certs" / "http_ca.crt"
    cert.parent.mkdir(parents=True)
    cert.write_text("a test certificate placeholder, not used in network tests")
    return cert


def _cfg(index="my_index"):
    return {
        "ES_URL": "https://192.168.0.134:9001",
        "ES_INDEX": index,
        "ES_USERNAME": "operator",
        "ES_PASSWORD": "SECRET_PASSWORD",
    }


def _root_document():
    return json.dumps({
        "cluster_name": "INTERNAL_ES_CLUSTER",
        "version": {"number": "8.13.1"},
    }).encode()


def _auth_document(username="operator"):
    return json.dumps({
        "username": username,
        "enabled": True,
        "authentication_type": "realm",
        "authentication_realm": {"name": "file", "type": "file"},
    }).encode()


def _mapping_document(index):
    return json.dumps({index: REQUIREMENT_E2E_MAPPING}).encode()


def test_mapping_reuses_real_requirements_predicate():
    index = REQUIREMENT_E2E_INDEX
    assert es._mapping_result(_mapping_document(index), index) == (
        "PASS", "es_mapping_compatible")
    incompatible = copy.deepcopy(REQUIREMENT_E2E_MAPPING)
    del incompatible["mappings"]["properties"]["multidim_event_json"]
    status, reason = es._mapping_result(
        json.dumps({index: incompatible}).encode(), index)
    assert (status, reason) == ("FAIL", "mapping_incompatible")


@pytest.mark.parametrize("payload,expected", [
    (b"{}", ("SKIP", "es_mapping_target_ambiguous")),
    (b'{"a":{"mappings":{}},"b":{"mappings":{}}}',
     ("SKIP", "es_mapping_target_ambiguous")),
    (b"[]", ("FAIL", "es_mapping_response_invalid")),
    (b"[{}]", ("FAIL", "es_mapping_response_invalid")),
    (b"[{}, {}]", ("FAIL", "es_mapping_response_invalid")),
    (b"null", ("FAIL", "es_mapping_response_invalid")),
    (b'"value"', ("FAIL", "es_mapping_response_invalid")),
    (b"123", ("FAIL", "es_mapping_response_invalid")),
    (b"not json", ("FAIL", "es_mapping_response_invalid")),
    (b'{"a":{"anything":true}}', ("FAIL", "es_mapping_response_invalid")),
])
def test_mapping_response_cannot_false_pass(payload, expected):
    assert es._mapping_result(payload, "my_index") == expected


@pytest.mark.parametrize("bad", (
    "../index", "/_all", "*", "my,index", "index?x=1", "bad/index",
    "index%2fsecret", "Upper", ".hidden", " my_index", "my_index ",
    "index#x", "a" * 260,
))
def test_index_selector_rejected(bad):
    assert es._configured_index(bad) is None


@pytest.mark.parametrize("value", (
    "my_index", "index-2026", "foo.bar", "a" * 255,
))
def test_index_selector_accepts_literals(value):
    assert es._configured_index(value) == value


def test_no_network_does_not_open_tls_or_read_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        es, "_https_get", lambda *_: pytest.fail("no socket allowed"))
    obs = es._observe(_cfg(), no_network=True, root=tmp_path)
    assert obs["https_probe"] == "SKIP"
    assert obs["mapping_probe"] == "SKIP"
    assert obs["reason"] == "network_disabled"
    assert "SECRET_PASSWORD" not in json.dumps(obs)


@pytest.mark.parametrize("url", [
    "http://192.168.0.134:9001",
    "https://8.8.8.8:9001",
    "https://es.internal:9001",
    "https://169.254.169.254:9001",
    "https://192.168.0.134:9001/_search",
    "https://admin:password@192.168.0.134:9001",
    "https://192.168.0.134:9001?unsafe=",
    "https://192.168.0.134:9001#",
])
def test_only_private_numeric_https_root_may_probe(
        monkeypatch, tmp_path, url):
    _ca(tmp_path)
    monkeypatch.setattr(
        es, "_https_get", lambda *_: pytest.fail("unsafe destination called"))
    cfg = {**_cfg(), "ES_URL": url}
    obs = es._observe(cfg, no_network=False, root=tmp_path)
    assert obs["https_probe"] == "SKIP"


@pytest.mark.parametrize("remove", ["ES_USERNAME", "ES_PASSWORD", "ES_INDEX"])
def test_missing_deployment_config_never_network(monkeypatch, tmp_path, remove):
    _ca(tmp_path)
    cfg = _cfg()
    del cfg[remove]
    monkeypatch.setattr(
        es, "_https_get", lambda *_: pytest.fail("missing config connected"))
    obs = es._observe(cfg, no_network=False, root=tmp_path)
    assert obs["https_probe"] == "SKIP"


def test_missing_ca_fails_closed_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(
        es, "_https_get", lambda *_: pytest.fail("missing CA connected"))
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert obs["https_probe"] == "SKIP"
    assert obs["reason"] == "es_ca_missing"


def test_ca_symlink_refused(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.pem"
    target.write_text("not trusted")
    cert = tmp_path / "agent" / "certs" / "http_ca.crt"
    cert.parent.mkdir(parents=True)
    cert.symlink_to(target)
    assert es._trusted_ca_file(tmp_path) is None


def test_https_root_and_mapping_positive_are_still_only_partial(
        monkeypatch, tmp_path):
    _ca(tmp_path)
    calls = []
    def fake(host, port, path, user, password, ca):
        calls.append((host, port, path, user, password))
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return (200, _auth_document(), "https_response_received") if (
                password == "SECRET_PASSWORD") else (
                401, b"{}", "https_response_received")
        return 200, _mapping_document(REQUIREMENT_E2E_INDEX), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(REQUIREMENT_E2E_INDEX),
                      no_network=False, root=tmp_path,
                      verify_credentials=True)
    assert [x[2] for x in calls] == [
        "/", "/_security/_authenticate", "/_security/_authenticate",
        "/" + REQUIREMENT_E2E_INDEX + "/_mapping",
    ]
    assert calls[2][4] != "SECRET_PASSWORD"
    assert calls[2][3] == "operator"
    assert {x[:2] for x in calls} == {("192.168.0.134", 9001)}
    assert obs["https_probe"] == "PASS"
    assert obs["mapping_probe"] == "PASS"
    assert obs["tls_validation"] == "PASS"
    assert obs["auth"] == "PASS"
    assert obs["credential_control"] == "PASS"
    assert obs["service_identity"] == "NOT_TESTED"
    assert obs["feature_acceptance"] == "NOT_TESTED"
    result = json.dumps(obs)
    for value in ("SECRET_PASSWORD", "operator", "my_index", "INTERNAL_ES_CLUSTER", "192.168.0.134"):
        assert value not in result


@pytest.mark.parametrize("status,expected", [
    (401, "es_auth_rejected"), (403, "es_root_access_denied"),
    (404, "es_identity_http_unexpected"), (302, "es_identity_http_unexpected"),
])
def test_root_auth_failures_never_progress_to_mapping(
        monkeypatch, tmp_path, status, expected):
    _ca(tmp_path)
    calls = []
    def fake(host, port, path, user, password, ca):
        calls.append(path)
        return status, b"{}", "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert calls == ["/"]
    assert obs["https_probe"] == "FAIL"
    assert obs["mapping_probe"] == "SKIP"
    assert obs["reason"] == expected


@pytest.mark.parametrize("status,expected", [
    (401, "es_mapping_access_denied"),
    (403, "es_mapping_access_denied"),
    (404, "es_index_missing"),
    (302, "es_mapping_http_unexpected"),
])
def test_mapping_auth_and_index_failures(monkeypatch, tmp_path, status, expected):
    _ca(tmp_path)
    def fake(host, port, path, user, password, ca):
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return status, b"{}", "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert obs["https_probe"] == "PASS"
    assert obs["mapping_probe"] == "FAIL"
    assert obs["reason"] == expected


def test_mapping_incompatible_is_not_success(monkeypatch, tmp_path):
    _ca(tmp_path)
    mismatch = json.dumps({"my_index": {"mappings": {}}}).encode()
    monkeypatch.setattr(es, "_https_get",
                        lambda host, port, path, *_:
                        (200, _root_document() if path == "/" else
                         _auth_document() if path == "/_security/_authenticate"
                         else mismatch, "https_response_received"))
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert obs["mapping_probe"] == "FAIL"
    assert obs["reason"] == "mapping_incompatible"


@pytest.mark.parametrize("reason,expected_tls", [
    ("es_tls_identity_unverified", "FAIL"),
    ("es_https_transport_unavailable", "NOT_VERIFIED"),
    ("es_ca_invalid", "NOT_VERIFIED"),
])
def test_transport_error_no_tls_success(monkeypatch, tmp_path, reason, expected_tls):
    _ca(tmp_path)
    monkeypatch.setattr(es, "_https_get",
                        lambda *_: (None, None, reason))
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert obs["https_probe"] == "FAIL"
    assert obs["tls_validation"] == expected_tls
    assert obs["mapping_probe"] == "SKIP"


def test_actual_deadline_waitfor_bounds_slow_server(monkeypatch, tmp_path):
    _ca(tmp_path)
    async def slow(*args):
        await asyncio.sleep(5)
        return 200, b"{}"
    monkeypatch.setattr(es, "_one_https_get", slow)
    monkeypatch.setattr(es, "DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr(es.ssl, "create_default_context",
                        lambda **kwargs: es.ssl.SSLContext(es.ssl.PROTOCOL_TLS_CLIENT))
    status, body, reason = es._https_get(
        "127.0.0.1", 9001, "/", "operator", "PRIVATE_SECRET",
        tmp_path / "agent" / "certs" / "http_ca.crt")
    assert status is None and body is None
    assert reason == "es_https_transport_unavailable"


def test_cli_config_only_outputs_single_redacted_partial_document(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda root: _cfg())
    assert es.main(["--no-network"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert payload["network_mode"] == "CONFIG_ONLY"
    assert payload["results"][0]["https_probe"] == "SKIP"
    assert "SECRET_PASSWORD" not in json.dumps(payload)


def test_cli_wrong_root_never_reads_env(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        es, "_effective_runtime_config",
        lambda *_: pytest.fail("invalid invocation loaded config"))
    assert es.main(["--strict-ip-san"]) == 2
    assert "run_from_repository_root" in capsys.readouterr().out


@pytest.mark.parametrize("payload", [
    b'{}', b'[]', b'broken json',
    b'{"username":"operator"}',
    _auth_document("another_user"),
    json.dumps({"username": "operator", "enabled": True,
                "authentication_type": "anonymous",
                "authentication_realm": {"type": "anonymous"}}).encode(),
    json.dumps({"username": "operator", "enabled": False,
                "authentication_type": "realm",
                "authentication_realm": {"type": "file"}}).encode(),
    json.dumps({"username": "operator", "enabled": True,
                "authentication_type": "realm",
                "authentication_realm": {}}).encode(),
])
def test_security_auth_endpoint_must_attest_basic_principal(payload):
    assert es._verified_basic_principal(payload, "operator") is False
    assert es._verified_basic_principal(_auth_document(), "operator") is True


@pytest.mark.parametrize(("status", "document", "auth", "reason"), [
    (200, _auth_document("wrong_user"), "FAIL", "es_principal_unverified"),
    (200, b'{"enabled":true}', "FAIL", "es_principal_unverified"),
    (200, b"invalid", "FAIL", "es_principal_unverified"),
    (401, b"{}", "FAIL", "es_auth_rejected"),
    (403, b"{}", "NOT_VERIFIED", "es_auth_access_denied"),
    (404, b"{}", "NOT_TESTED", "es_auth_endpoint_unavailable"),
    (429, b"{}", "NOT_VERIFIED", "es_auth_http_unexpected"),
    (500, b"{}", "NOT_VERIFIED", "es_auth_http_unexpected"),
    (502, b"{}", "NOT_VERIFIED", "es_auth_http_unexpected"),
])
def test_public_root_and_mapping_cannot_fake_authentication(
        monkeypatch, tmp_path, status, document, auth, reason):
    _ca(tmp_path)
    calls = []
    def fake(host, port, path, user, password, ca):
        calls.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return status, document, "https_response_received"
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert calls == ["/", "/_security/_authenticate"]
    assert obs["https_probe"] == "PASS"
    assert obs["auth"] == auth
    assert obs["mapping_probe"] == "SKIP"
    assert obs["reason"] == reason
    for private in ("operator", "SECRET_PASSWORD", "wrong_user", "INTERNAL_ES_CLUSTER"):
        assert private not in json.dumps(obs)


def test_authenticated_only_after_protected_security_endpoint(monkeypatch, tmp_path):
    _ca(tmp_path)
    seen = []
    def fake(host, port, path, user, password, ca):
        seen.append((path, password))
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return ((200, _auth_document(), "https_response_received")
                    if password == "SECRET_PASSWORD" else
                    (401, b"{}", "https_response_received"))
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path,
                      verify_credentials=True)
    assert obs["auth"] == "PASS"
    assert obs["credential_control"] == "PASS"
    assert obs["mapping_probe"] == "PASS"
    assert [x[0] for x in seen] == [
        "/", "/_security/_authenticate", "/_security/_authenticate",
        "/my_index/_mapping",
    ]
    assert seen[2][1] != "SECRET_PASSWORD"
    assert obs["feature_acceptance"] == "NOT_TESTED"


def test_authenticated_endpoint_transport_error_no_mapping(monkeypatch, tmp_path):
    _ca(tmp_path)
    seen = []
    def fake(host, port, path, user, password, ca):
        seen.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        assert path == "/_security/_authenticate"
        return None, None, "es_tls_identity_unverified"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert seen == ["/", "/_security/_authenticate"]
    assert obs["tls_validation"] == "FAIL"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["mapping_probe"] == "SKIP"
    assert obs["reason"] == "es_auth_transport_unavailable"


def test_cli_fail_code_for_unverified_principal(monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    def fake(host, port, path, user, password, ca):
        return (200, _root_document() if path == "/" else
                _auth_document("wrong_user"), "https_response_received")
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--strict-ip-san"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["results"][0]["auth"] == "FAIL"
    assert doc["results"][0]["mapping_probe"] == "SKIP"



def test_default_never_sends_bad_password_and_never_claims_auth_pass(
        monkeypatch, tmp_path):
    _ca(tmp_path)
    requests = []
    def fake(host, port, path, username, password, ca):
        requests.append((path, username, password))
        assert password == "SECRET_PASSWORD"
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path)
    assert [x[0] for x in requests] == [
        "/", "/_security/_authenticate", "/my_index/_mapping",
    ]
    assert obs["https_probe"] == "PASS"
    assert obs["mapping_probe"] == "PASS"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["credential_control"] == "NOT_RUN"
    assert obs["tls_validation"] == "PASS"


def test_default_cli_partial_never_promotes_unverified_auth(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    def fake(host, port, path, user, password, ca):
        assert password == "SECRET_PASSWORD"
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--strict-ip-san"]) == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["results"][0]["auth"] == "NOT_VERIFIED"
    assert doc["results"][0]["mapping_probe"] == "PASS"
    assert doc["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


def test_proxy_ignores_wrong_password_does_not_false_pass(
        monkeypatch, tmp_path):
    _ca(tmp_path)
    calls = []
    def fake(host, port, path, user, password, ca):
        calls.append((path, password))
        # A broken proxy authenticates every Authorization header using
        # injected credentials for 'operator', ignoring supplied password.
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path,
                      verify_credentials=True)
    assert [x[0] for x in calls] == [
        "/", "/_security/_authenticate", "/_security/_authenticate",
    ]
    assert calls[1][1] == "SECRET_PASSWORD"
    assert calls[2][1] != "SECRET_PASSWORD"
    assert obs["auth"] == "FAIL"
    assert obs["credential_control"] == "FAIL"
    assert obs["mapping_probe"] == "SKIP"
    assert obs["reason"] == "es_credential_control_not_rejected"
    assert calls[2][1] not in json.dumps(obs)


@pytest.mark.parametrize("failure_stage", [
    "/_security/_authenticate", "/my_index/_mapping",
])
@pytest.mark.parametrize("reason,expected_tls", [
    ("es_tls_identity_unverified", "FAIL"),
    ("es_https_transport_unavailable", "NOT_VERIFIED"),
    ("es_ca_invalid", "NOT_VERIFIED"),
])
def test_later_connection_failure_never_leaves_tls_pass(
        monkeypatch, tmp_path, failure_stage, reason, expected_tls):
    _ca(tmp_path)
    seen = []
    def fake(host, port, path, user, password, ca):
        seen.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            if user == "operator" and password == "SECRET_PASSWORD":
                if failure_stage == path:
                    return None, None, reason
                return 200, _auth_document(), "https_response_received"
            return 401, b"{}", "https_response_received"
        assert path == "/my_index/_mapping"
        return None, None, reason
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path,
                      verify_credentials=True)
    assert obs["tls_validation"] == expected_tls
    assert obs["tls_validation"] != "PASS"
    assert obs["mapping_probe"] != "PASS"
    if failure_stage == "/_security/_authenticate":
        assert obs["auth"] != "PASS"
        assert seen == ["/", "/_security/_authenticate"]
    else:
        assert seen[-1] == "/my_index/_mapping"
        if reason == "es_tls_identity_unverified":
            assert obs["auth"] == "NOT_VERIFIED"


@pytest.mark.parametrize("reason,expected_tls", [
    ("es_tls_identity_unverified", "FAIL"),
    ("es_https_transport_unavailable", "NOT_VERIFIED"),
])
def test_negative_control_transport_fail_does_not_claim_auth(
        monkeypatch, tmp_path, reason, expected_tls):
    _ca(tmp_path)
    seen = []
    def fake(host, port, path, user, password, ca):
        seen.append((path, password))
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            if password == "SECRET_PASSWORD":
                return 200, _auth_document(), "https_response_received"
            return None, None, reason
        pytest.fail("mapping must not be attempted without control")
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path,
                      verify_credentials=True)
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["credential_control"] == "INCOMPLETE"
    assert obs["mapping_probe"] == "SKIP"
    assert obs["tls_validation"] == expected_tls
    assert len(seen) == 3


def test_cli_opted_in_bad_password_control_returns_success(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    def fake(host, port, path, user, password, ca):
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            if password == "SECRET_PASSWORD":
                return 200, _auth_document(), "https_response_received"
            return 401, b"{}", "https_response_received"
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--verify-credentials"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["auth"] == "PASS"
    assert result["results"][0]["credential_control"] == "PASS"
    assert result["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"



def test_negative_control_403_does_not_prove_wrong_password_rejection(
        monkeypatch, tmp_path):
    _ca(tmp_path)
    called = []
    def fake(host, port, path, user, password, ca):
        called.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        assert path == "/_security/_authenticate"
        if password == "SECRET_PASSWORD":
            return 200, _auth_document(), "https_response_received"
        # A proxy can deny access to this endpoint with 403 without checking
        # the supplied credential. Only HTTP 401 is a negative-auth control.
        return 403, b"{}", "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path,
                      verify_credentials=True)
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["credential_control"] == "INCOMPLETE"
    assert obs["reason"] == "es_credential_control_unverified"
    assert obs["mapping_probe"] == "SKIP"
    assert called == ["/", "/_security/_authenticate",
                      "/_security/_authenticate"]



@pytest.mark.parametrize("failing_path", [
    "/_security/_authenticate", "/my_index/_mapping",
])
def test_cli_returns_failure_for_any_later_certificate_validation(
        monkeypatch, tmp_path, capsys, failing_path):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    def fake(host, port, path, user, password, ca):
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            if password == "SECRET_PASSWORD":
                if failing_path == path:
                    return None, None, "es_tls_identity_unverified"
                return 200, _auth_document(), "https_response_received"
            return 401, b"{}", "https_response_received"
        assert path == "/my_index/_mapping"
        return None, None, "es_tls_identity_unverified"
    monkeypatch.setattr(es, "_https_get", fake)
    args = ["--verify-credentials"] if failing_path.endswith("_mapping") else ["--strict-ip-san"]
    assert es.main(args) == 1
    doc = json.loads(capsys.readouterr().out)
    result = doc["results"][0]
    assert result["tls_validation"] == "FAIL"
    assert result["mapping_probe"] != "PASS"
    assert doc["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


def test_cli_credential_control_certificate_failure_returns_failure(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    def fake(host, port, path, user, password, ca):
        if path == "/":
            return 200, _root_document(), "https_response_received"
        assert path == "/_security/_authenticate"
        if password == "SECRET_PASSWORD":
            return 200, _auth_document(), "https_response_received"
        return None, None, "es_tls_identity_unverified"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--verify-credentials"]) == 1
    obs = json.loads(capsys.readouterr().out)["results"][0]
    assert obs["tls_validation"] == "FAIL"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["credential_control"] == "INCOMPLETE"
    assert obs["mapping_probe"] == "SKIP"



@pytest.mark.parametrize("with_control", (False, True))
def test_protected_auth_403_is_access_denied_not_bad_credentials(
        monkeypatch, tmp_path, capsys, with_control):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    requests = []
    def fake(host, port, path, user, password, ca):
        requests.append((path, password))
        assert password == "SECRET_PASSWORD"
        if path == "/":
            return 200, _root_document(), "https_response_received"
        assert path == "/_security/_authenticate"
        # Gateway forbids access before inspecting Authorization header.
        return 403, b'{"error":"forbidden"}', "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    command = ["--verify-credentials"] if with_control else ["--strict-ip-san"]
    assert es.main(command) == 2
    payload = json.loads(capsys.readouterr().out)
    obs = payload["results"][0]
    assert obs["https_probe"] == "PASS"
    assert obs["tls_validation"] == "PASS"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["reason"] == "es_auth_access_denied"
    assert obs["credential_control"] == "NOT_RUN"
    assert obs["mapping_probe"] == "SKIP"
    assert [path for path, _ in requests] == ["/", "/_security/_authenticate"]
    assert "SECRET_PASSWORD" not in json.dumps(payload)
    assert "operator" not in json.dumps(payload)



@pytest.mark.parametrize("opted_in", (False, True))
def test_root_gateway_403_is_access_denied_not_rejected_credentials(
        monkeypatch, tmp_path, capsys, opted_in):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    requests = []
    def fake(host, port, path, user, password, ca):
        requests.append((path, password))
        assert path == "/"
        assert password == "SECRET_PASSWORD"
        # Gateway ACL denies before Basic auth; password has not been tested.
        return 403, b'{"error":"gateway_denied"}', "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    args = ["--verify-credentials"] if opted_in else ["--strict-ip-san"]
    assert es.main(args) == 1
    output = capsys.readouterr().out
    result = json.loads(output)["results"][0]
    assert result["https_probe"] == "FAIL"
    assert result["auth"] == "NOT_VERIFIED"
    assert result["reason"] == "es_root_access_denied"
    assert result["credential_control"] == "NOT_RUN"
    assert result["mapping_probe"] == "SKIP"
    assert result["tls_validation"] == "PASS"
    assert requests == [("/", "SECRET_PASSWORD")]
    assert "SECRET_PASSWORD" not in output
    assert "operator" not in output


def test_root_es_401_is_rejected_and_never_attempts_mapping(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    paths = []
    def fake(host, port, path, user, password, ca):
        paths.append(path)
        return 401, b"{}", "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--strict-ip-san"]) == 1
    output = json.loads(capsys.readouterr().out)["results"][0]
    assert output["https_probe"] == "FAIL"
    assert output["auth"] == "FAIL"
    assert output["reason"] == "es_auth_rejected"
    assert paths == ["/"]



@pytest.mark.parametrize("malformation", [
    "top_properties_array",
    "nested_properties_array",
    "nested_fields_array",
    "nested_properties_scalar",
    "unrelated_property_fields_array",
    "non_mapping_field_node",
])
def test_malformed_nested_es_mapping_returns_redacted_invalid_result(
        malformation):
    mapping = copy.deepcopy(REQUIREMENT_E2E_MAPPING)
    properties = mapping["mappings"]["properties"]
    if malformation == "top_properties_array":
        mapping["mappings"]["properties"] = []
    elif malformation == "nested_properties_array":
        properties["multidim_event_json"]["properties"] = []
    elif malformation == "nested_fields_array":
        properties["communication"]["properties"]["subject"]["fields"] = []
    elif malformation == "nested_properties_scalar":
        properties["multidim_event_json"]["properties"] = "SECRET_BAD_SCHEMA"
    elif malformation == "unrelated_property_fields_array":
        properties["extra_field"] = {"type": "keyword", "fields": []}
    else:
        properties["uuid"] = ["SECRET_BAD_FIELD"]
    body = json.dumps({"my_index": mapping}).encode()
    assert es._mapping_result(body, "my_index") == (
        "FAIL", "es_mapping_response_invalid")


def test_malformed_mapping_cli_is_structured_fail_not_traceback(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    corrupted = copy.deepcopy(REQUIREMENT_E2E_MAPPING)
    corrupted["mappings"]["properties"]["multidim_event_json"][
        "properties"] = ["SECRET_INVALID_NESTED"]
    mapping_body = json.dumps({"my_index": corrupted}).encode()
    calls = []
    def fake(host, port, path, user, password, ca):
        calls.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return 200, mapping_body, "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--strict-ip-san"]) == 1
    output = capsys.readouterr().out
    obs = json.loads(output)["results"][0]
    assert obs["mapping_probe"] == "FAIL"
    assert obs["reason"] == "es_mapping_response_invalid"
    assert obs["auth"] == "NOT_VERIFIED"
    assert "SECRET_INVALID_NESTED" not in output
    assert "my_index" not in output
    assert calls == ["/", "/_security/_authenticate", "/my_index/_mapping"]


def test_mapping_predicate_unexpected_attribute_error_is_redacted(monkeypatch):
    def defective(mapping, selector):
        raise AttributeError("private_host 192.168.0.134 hidden")
    monkeypatch.setattr(es, "mapping_compatibility", defective)
    assert es._mapping_result(_mapping_document("my_index"), "my_index") == (
        "FAIL", "es_mapping_response_invalid")



@pytest.mark.parametrize("invalid_mapping", (
    b"[]", b"[{}]", b"[{},{}]", b"null", b'["PRIVATE_TOKEN"]',
))
def test_cli_rejects_nonobject_mapping_response_as_observed_failure(
        monkeypatch, tmp_path, capsys, invalid_mapping):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    seen = []
    def fake(host, port, path, user, password, ca):
        seen.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        assert path == "/my_index/_mapping"
        return 200, invalid_mapping, "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--strict-ip-san"]) == 1
    output = capsys.readouterr().out
    doc = json.loads(output)
    obs = doc["results"][0]
    assert obs["mapping_probe"] == "FAIL"
    assert obs["reason"] == "es_mapping_response_invalid"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["feature_acceptance"] == "NOT_TESTED"
    assert "PRIVATE_TOKEN" not in output
    assert "my_index" not in output
    assert seen == ["/", "/_security/_authenticate", "/my_index/_mapping"]



@pytest.mark.parametrize("status", (302, 408, 429, 500, 502, 503))
@pytest.mark.parametrize("verify_credentials", (False, True))
def test_unexpected_protected_auth_http_is_incomplete_not_bad_password(
        monkeypatch, tmp_path, capsys, status, verify_credentials):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    paths = []
    def fake(host, port, path, user, password, ca):
        paths.append(path)
        assert password == "SECRET_PASSWORD"
        if path == "/":
            return 200, _root_document(), "https_response_received"
        assert path == "/_security/_authenticate"
        # Non-auth service/gateway errors cannot prove credentials invalid.
        return status, b'{"secret":"NEVER_PRINT_REMOTE_DATA"}', "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    argv = ["--verify-credentials"] if verify_credentials else ["--strict-ip-san"]
    assert es.main(argv) == 2
    result_text = capsys.readouterr().out
    doc = json.loads(result_text)
    obs = doc["results"][0]
    assert obs["https_probe"] == "PASS"
    assert obs["tls_validation"] == "PASS"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["reason"] == "es_auth_http_unexpected"
    assert obs["credential_control"] == "NOT_RUN"
    assert obs["mapping_probe"] == "SKIP"
    assert obs["feature_acceptance"] == "NOT_TESTED"
    assert paths == ["/", "/_security/_authenticate"]
    for secret in ("SECRET_PASSWORD", "NEVER_PRINT_REMOTE_DATA", "operator"):
        assert secret not in result_text



@pytest.mark.parametrize("status,body,expected_control,expected_auth,expected_reason", [
    (200, _auth_document(), "FAIL", "FAIL", "es_credential_control_not_rejected"),
    (200, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (200, _auth_document("other_user"), "INCOMPLETE", "NOT_VERIFIED",
     "es_credential_control_unverified"),
    (302, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (403, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (404, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (408, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (429, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (500, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (502, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
    (503, b"{}", "INCOMPLETE", "NOT_VERIFIED", "es_credential_control_unverified"),
])
def test_opted_in_control_http_is_classified_only_on_credible_attestation(
        monkeypatch, tmp_path, capsys, status, body, expected_control,
        expected_auth, expected_reason):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    seen = []
    def fake(host, port, path, username, password, ca):
        seen.append((path, password))
        if path == "/":
            return 200, _root_document(), "https_response_received"
        assert path == "/_security/_authenticate"
        if password == "SECRET_PASSWORD":
            return 200, _auth_document(), "https_response_received"
        return status, body, "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    exit_code = 1 if expected_control == "FAIL" else 2
    assert es.main(["--verify-credentials"]) == exit_code
    output = capsys.readouterr().out
    obs = json.loads(output)["results"][0]
    assert obs["credential_control"] == expected_control
    assert obs["auth"] == expected_auth
    assert obs["reason"] == expected_reason
    assert obs["mapping_probe"] == "SKIP"
    assert obs["https_probe"] == "PASS"
    assert obs["tls_validation"] == "PASS"
    assert len(seen) == 3
    assert [x[0] for x in seen] == ["/", "/_security/_authenticate",
                                      "/_security/_authenticate"]
    assert seen[-1][1] != "SECRET_PASSWORD"
    for sensitive in ("SECRET_PASSWORD", "operator", "my_index"):
        assert sensitive not in output
    assert seen[-1][1] not in output


def test_negative_control_401_is_only_successful_challenge_response(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    seen = []
    def fake(host, port, path, username, password, ca):
        seen.append(path)
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            if password == "SECRET_PASSWORD":
                return 200, _auth_document(), "https_response_received"
            return 401, b'{"error":"PRIVATE_EVIDENCE"}', "https_response_received"
        return 200, _mapping_document("my_index"), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--verify-credentials"]) == 0
    output = capsys.readouterr().out
    obs = json.loads(output)["results"][0]
    assert obs["auth"] == "PASS"
    assert obs["credential_control"] == "PASS"
    assert obs["mapping_probe"] == "PASS"
    assert seen == ["/", "/_security/_authenticate",
                    "/_security/_authenticate", "/my_index/_mapping"]
    assert "PRIVATE_EVIDENCE" not in output



@pytest.mark.parametrize("matching", (True, False))
def test_ca_verified_warning_only_tls_reports_explicit_san_identity(
        monkeypatch, tmp_path, matching):
    # Unit seam for real TLS: the connection is CA-verified regardless of SAN,
    # and the per-connection peer SAN result must never silently become PASS.
    seen = []
    async def fake_request(host, port, path, username, password, ctx,
                           *, ip_san_attestation=None):
        assert ip_san_attestation is not None
        assert ctx.verify_mode == es.ssl.CERT_REQUIRED
        assert ctx.check_hostname is False
        ip_san_attestation.append(matching)
        seen.append(path)
        return 200, b"{}"
    monkeypatch.setattr(es, "_one_https_get", fake_request)
    monkeypatch.setattr(
        es.ssl, "create_default_context",
        lambda **kwargs: es.ssl.SSLContext(es.ssl.PROTOCOL_TLS_CLIENT),
    )
    status, body, reason = es._https_get(
        "192.168.0.134", 9001, "/", "operator", "SECRET_PASSWORD",
        _ca(tmp_path), warn_only_ip_san=True,
    )
    assert status == 200 and body == b"{}"
    assert reason == ("https_response_received" if matching else
                      "https_response_ca_only_ip_san_mismatch")
    assert seen == ["/"]


def test_ca_only_diagnostic_still_rejects_untrusted_chain(monkeypatch, tmp_path):
    async def reject_chain(*args, **kwargs):
        raise es.ssl.SSLCertVerificationError("certificate verify failed")
    monkeypatch.setattr(es, "_one_https_get", reject_chain)
    monkeypatch.setattr(
        es.ssl, "create_default_context",
        lambda **kwargs: es.ssl.SSLContext(es.ssl.PROTOCOL_TLS_CLIENT),
    )
    status, body, reason = es._https_get(
        "192.168.0.134", 9001, "/", "operator", "SECRET_PASSWORD",
        _ca(tmp_path), warn_only_ip_san=True,
    )
    assert status is None and body is None
    assert reason == "es_tls_identity_unverified"


@pytest.mark.parametrize("mismatch_stage", ["/", "/_security/_authenticate",
                                            "/" + REQUIREMENT_E2E_INDEX + "/_mapping"])
def test_ip_san_warning_mode_inspects_mapping_but_never_certifies_identity(
        monkeypatch, tmp_path, mismatch_stage):
    _ca(tmp_path)
    calls = []
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san is True
        calls.append((path, password))
        reason = ("https_response_ca_only_ip_san_mismatch"
                  if path == mismatch_stage else "https_response_received")
        if path == "/":
            return 200, _root_document(), reason
        if path == "/_security/_authenticate":
            return 200, _auth_document(), reason
        assert path == "/" + REQUIREMENT_E2E_INDEX + "/_mapping"
        return 200, _mapping_document(REQUIREMENT_E2E_INDEX), reason
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(REQUIREMENT_E2E_INDEX), no_network=False,
                      root=tmp_path, warn_only_ip_san=True)
    assert [x[0] for x in calls] == [
        "/", "/_security/_authenticate",
        "/" + REQUIREMENT_E2E_INDEX + "/_mapping",
    ]
    assert all(x[1] == "SECRET_PASSWORD" for x in calls)
    assert obs["ip_san_policy"] == "WARN_ONLY"
    assert obs["identity_warning"] is True
    assert obs["tls_validation"] == "WARN"
    assert obs["https_probe"] == "PASS"
    assert obs["auth"] == "NOT_VERIFIED"
    assert obs["mapping_probe"] == "WARN"
    assert obs["reason"] == "es_mapping_compatible_identity_unverified"
    assert obs["feature_acceptance"] == "NOT_TESTED"
    assert obs["credential_control"] == "NOT_RUN"
    for private in ("operator", "SECRET_PASSWORD", "192.168.0.134",
                    "INTERNAL_ES_CLUSTER"):
        assert private not in json.dumps(obs)


def test_ip_san_warning_mode_preserves_incompatible_mapping_as_warning(
        monkeypatch, tmp_path):
    _ca(tmp_path)
    incompatible = copy.deepcopy(REQUIREMENT_E2E_MAPPING)
    incompatible["mappings"]["properties"].pop("multidim_event_json")
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san
        if path == "/":
            return 200, _root_document(), "https_response_ca_only_ip_san_mismatch"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return 200, json.dumps({REQUIREMENT_E2E_INDEX: incompatible}).encode(), (
            "https_response_received")
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(REQUIREMENT_E2E_INDEX), no_network=False,
                      root=tmp_path, warn_only_ip_san=True)
    assert obs["tls_validation"] == "WARN"
    assert obs["mapping_probe"] == "WARN"
    assert obs["reason"] == "mapping_incompatible_identity_unverified"


def test_ip_san_warning_only_cannot_hide_later_tls_failure(monkeypatch, tmp_path):
    _ca(tmp_path)
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san
        if path == "/":
            return 200, _root_document(), "https_response_ca_only_ip_san_mismatch"
        if path == "/_security/_authenticate":
            return None, None, "es_tls_identity_unverified"
        pytest.fail("mapping attempted after certificate-chain failure")
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(), no_network=False, root=tmp_path,
                      warn_only_ip_san=True)
    assert obs["tls_validation"] == "FAIL"
    assert obs["identity_warning"] is True
    assert obs["mapping_probe"] == "SKIP"


def test_warning_mode_cli_exit_incomplete_and_never_claims_acceptance(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config",
                        lambda _: _cfg(REQUIREMENT_E2E_INDEX))
    called = []
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san
        called.append(path)
        reason = "https_response_ca_only_ip_san_mismatch"
        if path == "/":
            return 200, _root_document(), reason
        if path == "/_security/_authenticate":
            return 200, _auth_document(), reason
        return 200, _mapping_document(REQUIREMENT_E2E_INDEX), reason
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--warn-only-ip-san"]) == 2
    out = capsys.readouterr().out
    obs = json.loads(out)["results"][0]
    assert obs["identity_warning"] is True
    assert obs["tls_validation"] == "WARN"
    assert obs["mapping_probe"] == "WARN"
    assert obs["auth"] == "NOT_VERIFIED"
    assert len(called) == 3
    for private in ("SECRET_PASSWORD", "operator", "192.168.0.134",
                    "INTERNAL_ES_CLUSTER"):
        assert private not in out


def test_warning_mode_prohibits_wrong_password_control(monkeypatch, capsys):
    monkeypatch.setattr(
        es, "_https_get", lambda *a, **kw: pytest.fail("no network allowed"))
    with pytest.raises(SystemExit) as caught:
        es.main(["--warn-only-ip-san", "--verify-credentials"])
    assert caught.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_warning_no_network_never_opens_socket(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config", lambda _: _cfg())
    monkeypatch.setattr(
        es, "_https_get", lambda *a, **kw: pytest.fail("no network allowed"))
    assert es.main(["--no-network", "--warn-only-ip-san"]) == 2
    obs = json.loads(capsys.readouterr().out)["results"][0]
    assert obs["reason"] == "network_disabled"
    assert obs["tls_validation"] == "NOT_TESTED"
    assert obs["mapping_probe"] == "SKIP"



@pytest.mark.parametrize("exc", [
    TimeoutError("simulated dribbling deadline"),
    asyncio.IncompleteReadError(partial=b"x", expected=19),
    ValueError("malformed_http_response"),
    OSError("socket_lost"),
])
def test_san_mismatch_survives_credential_bearing_transport_failure(
        monkeypatch, tmp_path, exc):
    # Codex P2: SAN mismatch is known before Authorization, so a broken
    # response must not erase proof that the peer had a wrong IP identity.
    async def bad_response(host, port, path, username, password, context,
                           *, ip_san_attestation=None):
        assert ip_san_attestation is not None
        ip_san_attestation.append(False)
        raise exc
    monkeypatch.setattr(es, "_one_https_get", bad_response)
    monkeypatch.setattr(
        es.ssl, "create_default_context",
        lambda **kwargs: es.ssl.SSLContext(es.ssl.PROTOCOL_TLS_CLIENT),
    )
    status, body, reason = es._https_get(
        "192.168.0.134", 9001, "/", "operator", "SECRET_PASSWORD",
        _ca(tmp_path), warn_only_ip_san=True,
    )
    assert status is None and body is None
    assert reason == "es_https_transport_unavailable_ip_san_mismatch"


@pytest.mark.parametrize("stage", ["/", "/_security/_authenticate",
                                    "/" + REQUIREMENT_E2E_INDEX + "/_mapping"])
def test_mismatched_peer_failing_response_remains_visible_for_every_get(
        monkeypatch, tmp_path, stage):
    _ca(tmp_path)
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san is True
        if path == stage:
            return None, None, "es_https_transport_unavailable_ip_san_mismatch"
        if path == "/":
            return 200, _root_document(), "https_response_received"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return 200, _mapping_document(REQUIREMENT_E2E_INDEX), "https_response_received"
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(REQUIREMENT_E2E_INDEX), no_network=False,
                      root=tmp_path, warn_only_ip_san=True)
    assert obs["identity_warning"] is True
    assert obs["tls_validation"] == "WARN"
    assert obs["reason"] in (
        "es_https_transport_unavailable_ip_san_mismatch",
        "es_auth_transport_unavailable",
    )
    assert obs["auth"] != "PASS"
    assert obs["mapping_probe"] != "PASS"


def test_quick_cli_defaults_to_san_warning_and_never_claims_tls_pass(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config",
                        lambda _: _cfg(REQUIREMENT_E2E_INDEX))
    calls = []
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san is True
        calls.append((path, password))
        if path == "/":
            return 200, _root_document(), "https_response_ca_only_ip_san_mismatch"
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        return (200, _mapping_document(REQUIREMENT_E2E_INDEX),
                "https_response_received")
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main([]) == 2
    obs = json.loads(capsys.readouterr().out)["results"][0]
    assert obs["ip_san_policy"] == "WARN_ONLY"
    assert obs["identity_warning"] is True
    assert obs["tls_validation"] == "WARN"
    assert obs["mapping_probe"] == "WARN"
    assert obs["credential_control"] == "NOT_RUN"
    assert len(calls) == 3
    assert all(pwd == "SECRET_PASSWORD" for _, pwd in calls)


def test_strict_cli_is_explicit_and_failed_ip_san_stops_all_requests(
        monkeypatch, tmp_path, capsys):
    _ca(tmp_path)
    monkeypatch.setattr(es, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(es, "_effective_runtime_config",
                        lambda _: _cfg())
    called = []
    def fake(host, port, path, username, password, ca):
        called.append(path)
        return None, None, "es_tls_identity_unverified"
    monkeypatch.setattr(es, "_https_get", fake)
    assert es.main(["--strict-ip-san"]) == 1
    obs = json.loads(capsys.readouterr().out)["results"][0]
    assert obs["ip_san_policy"] == "STRICT"
    assert obs["identity_warning"] is False
    assert obs["tls_validation"] == "FAIL"
    assert obs["mapping_probe"] == "SKIP"
    assert called == ["/"]


def test_strict_and_warn_explicit_flags_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as caught:
        es.main(["--strict-ip-san", "--warn-only-ip-san"])
    assert caught.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err



@pytest.mark.parametrize("failed_stage", (
    "/_security/_authenticate",
    "/" + REQUIREMENT_E2E_INDEX + "/_mapping",
))
@pytest.mark.parametrize("later_failure,expected_tls", (
    ("es_https_transport_unavailable", "WARN"),
    ("es_tls_identity_unverified", "FAIL"),
))
def test_earlier_san_warning_survives_later_handshake_without_san_evidence(
        monkeypatch, tmp_path, failed_stage, later_failure, expected_tls):
    # The root request already observed the old-IP SAN and sent Basic auth.
    # A later socket loss *before* inspecting that connection's peer may not
    # erase this observation. A real CA/certificate failure must still FAIL.
    _ca(tmp_path)
    calls = []
    def fake(host, port, path, username, password, ca, *,
             warn_only_ip_san=False):
        assert warn_only_ip_san is True
        calls.append(path)
        if path == "/":
            return (200, _root_document(),
                    "https_response_ca_only_ip_san_mismatch")
        if path == failed_stage:
            return None, None, later_failure
        if path == "/_security/_authenticate":
            return 200, _auth_document(), "https_response_received"
        pytest.fail("Unexpected later mapping request")
    monkeypatch.setattr(es, "_https_get", fake)
    obs = es._observe(_cfg(REQUIREMENT_E2E_INDEX), no_network=False,
                      root=tmp_path, warn_only_ip_san=True)
    assert obs["identity_warning"] is True
    assert obs["tls_validation"] == expected_tls
    assert obs["mapping_probe"] != "PASS"
    assert obs["auth"] != "PASS"
    assert obs["credential_control"] == "NOT_RUN"
    assert calls == (
        ["/", "/_security/_authenticate"] if failed_stage.endswith(
            "_authenticate") else
        ["/", "/_security/_authenticate",
         "/" + REQUIREMENT_E2E_INDEX + "/_mapping"]
    )
    for private in ("operator", "SECRET_PASSWORD", "192.168.0.134"):
        assert private not in json.dumps(obs)



def _fake_http_stream(payload: bytes) -> asyncio.StreamReader:
    # A StreamReader constructor needs an event loop in hosted Python.
    # Prefeed all bytes + EOF inside the loop; the ensuing reads never block.
    async def ready() -> asyncio.StreamReader:
        reader = asyncio.StreamReader(limit=es.MAX_HEADERS)
        reader.feed_data(payload)
        reader.feed_eof()
        return reader
    return asyncio.run(ready())


def _chunked(*pieces: bytes, trailer: bytes = b"") -> bytes:
    return b"".join(
        f"{len(piece):x}\r\n".encode("ascii") + piece + b"\r\n"
        for piece in pieces
    ) + b"0\r\n" + trailer + b"\r\n"


def test_chunked_es_mapping_fixture_decodes_and_uses_existing_predicate():
    index = REQUIREMENT_E2E_INDEX
    body = _mapping_document(index)
    midpoint = max(1, len(body) // 3)
    stream = _fake_http_stream(_chunked(
        body[:midpoint], body[midpoint:midpoint * 2], body[midpoint * 2:]
    ))
    decoded = asyncio.run(es._read_http_body(
        stream, [b"Transfer-Encoding: chunked"], es.MAX_MAPPING_BODY,
    ))
    assert decoded == body
    assert es._mapping_result(decoded, index) == (
        "PASS", "es_mapping_compatible"
    )


def test_chunked_mapping_over_original_64k_cap_remains_bounded_and_compatible():
    index = REQUIREMENT_E2E_INDEX
    mapping = {index: {**REQUIREMENT_E2E_MAPPING, "padding": "x" * (es.MAX_BODY + 500)}}
    body = json.dumps(mapping).encode("utf-8")
    assert es.MAX_BODY < len(body) < es.MAX_MAPPING_BODY
    stream = _fake_http_stream(_chunked(body[:50000], body[50000:]))
    decoded = asyncio.run(es._read_http_body(
        stream, [b"Transfer-Encoding: Chunked"], es.MAX_MAPPING_BODY,
    ))
    assert decoded == body
    assert es._mapping_result(decoded, index) == ("PASS", "es_mapping_compatible")


def test_fixed_length_legacy_http_response_still_supported():
    body = b'{"ok":true}'
    stream = _fake_http_stream(body)
    assert asyncio.run(es._read_http_body(
        stream, [b"Content-Length: 11"], es.MAX_BODY
    )) == body


@pytest.mark.parametrize("fields", [
    [b"Transfer-Encoding: chunked", b"Content-Length: 1"],
    [b"Transfer-Encoding: chunked", b"Transfer-Encoding: chunked"],
    [b"Transfer-Encoding: gzip, chunked"],
    [b"Transfer-Encoding: gzip"],
    [b"Transfer-Encoding: identity"],
    [b"Content-Length: 1", b"Content-Length: 1"],
    [],
])
def test_chunked_unsafe_or_ambiguous_framing_is_rejected(fields):
    stream = _fake_http_stream(_chunked(b"x"))
    with pytest.raises(ValueError):
        asyncio.run(es._read_http_body(stream, fields, es.MAX_MAPPING_BODY))


@pytest.mark.parametrize("payload", [
    b"zz\r\n",
    b"1\r\nA\rX",
    b"1\r\nA\r\n0\r\nX-Invalid",
    b"1\r\nA\r\n0\r\nX: bad\r\n",
    b"1\r\nA\r\n0\r\nNot-A-Field\r\n\r\n",
    b"3\r\nA\r\n0\r\n\r\n",
    b"100000000\r\n",
    b"0;" + b"x" * es.MAX_CHUNK_LINE + b"\r\n\r\n",
    b"1;q=\x00\r\nA\r\n0\r\n\r\n",
])
def test_malformed_truncated_or_unbounded_chunks_fail_closed(payload):
    reader = _fake_http_stream(payload)
    with pytest.raises((ValueError, asyncio.IncompleteReadError)):
        asyncio.run(es._read_chunked_body(reader, es.MAX_MAPPING_BODY))


def test_chunked_with_bounded_trailers_and_extensions_is_readable():
    stream = _fake_http_stream(b"3;source=es\r\nabc\r\n0\r\nX-Trace: ok\r\n\r\n")
    assert asyncio.run(es._read_chunked_body(stream, es.MAX_BODY)) == b"abc"


def test_cumulative_chunked_payload_limit_applies_across_chunks():
    reader = _fake_http_stream(_chunked(b"123456", b"7890"))
    with pytest.raises(ValueError, match="oversized_chunked_body"):
        asyncio.run(es._read_chunked_body(reader, 9))


def test_large_chunk_size_rejected_before_body_allocation():
    reader = _fake_http_stream(b"200001\r\n")
    with pytest.raises(ValueError, match="oversized_chunked_body"):
        asyncio.run(es._read_chunked_body(reader, es.MAX_MAPPING_BODY))


def test_chunked_accepts_exact_body_limit():
    reader = _fake_http_stream(_chunked(b"a" * 64, b"b" * 32))
    decoded = asyncio.run(es._read_chunked_body(reader, 96))
    assert decoded == b"a" * 64 + b"b" * 32


def test_chunked_deadline_remains_absolute_even_when_server_drips_chunks():
    async def drip():
        reader = asyncio.StreamReader(limit=es.MAX_HEADERS)
        reader.feed_data(b"1\r\nA\r\n")
        return await asyncio.wait_for(
            es._read_chunked_body(reader, es.MAX_BODY), timeout=0.001
        )
    with pytest.raises(TimeoutError):
        asyncio.run(drip())



def test_chunked_transfer_must_be_http11_not_http10():
    stream = _fake_http_stream(_chunked(_mapping_document(REQUIREMENT_E2E_INDEX)))
    with pytest.raises(ValueError, match="unsupported_http_framing"):
        asyncio.run(es._read_http_body(
            stream, [b"Transfer-Encoding: chunked"], es.MAX_MAPPING_BODY,
            http_version=b"HTTP/1.0",
        ))
    legacy = b'{"ok":true}'
    stream2 = _fake_http_stream(legacy)
    assert asyncio.run(es._read_http_body(
        stream2, [b"Content-Length: 11"], es.MAX_BODY,
        http_version=b"HTTP/1.0",
    )) == legacy


@pytest.mark.parametrize("trailer", [
    b"Content-Length: 999",
    b"TRANSFER-ENCODING: gzip",
    b"Host: attacker",
    b"Authorization: Basic fake",
    b"Content-Type: text/plain",
    b"Content-Encoding: gzip",
    b"Connection: keep-alive",
    b"proxy-status: fake",
    b"Proxy-Connection: keep-alive",
    b"Access-Control-Allow-Origin: *",
    b"X-Frame-Options: DISABLE",
])
def test_forbidden_trailer_cannot_modify_framing_auth_or_response(trailer):
    payload = b"1\r\nA\r\n0\r\n" + trailer + b"\r\n\r\n"
    stream = _fake_http_stream(payload)
    with pytest.raises(ValueError, match="chunk_trailer_field_forbidden"):
        asyncio.run(es._read_http_body(
            stream, [b"Transfer-Encoding: chunked"], es.MAX_BODY,
        ))
