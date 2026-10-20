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
    (b"[]", ("SKIP", "es_mapping_target_ambiguous")),
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
    assert es.main([]) == 2
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
    (500, b"{}", "FAIL", "es_auth_http_unexpected"),
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
    assert es.main([]) == 1
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
    assert es.main([]) == 2
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
    assert obs["auth"] == "FAIL"
    assert obs["credential_control"] == "FAIL"
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
    args = ["--verify-credentials"] if failing_path.endswith("_mapping") else []
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
    command = ["--verify-credentials"] if with_control else []
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
    args = ["--verify-credentials"] if opted_in else []
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
    assert es.main([]) == 1
    output = json.loads(capsys.readouterr().out)["results"][0]
    assert output["https_probe"] == "FAIL"
    assert output["auth"] == "FAIL"
    assert output["reason"] == "es_auth_rejected"
    assert paths == ["/"]
