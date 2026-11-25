"""Local checks use real configuration and SDK; no provider request or DB write."""
import json
import certifi
import pytest
from elastic_transport import Transport
from tools.sraf_deep_local_preflight import check_local, main
from test_sraf_deep_startup_config import valid


@pytest.fixture
def env(monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("network request in local preflight")
    monkeypatch.setattr(Transport, "perform_request", forbidden)
    import requests
    monkeypatch.setattr(requests.Session, "request", forbidden)
    data = valid()
    data.update(ES_URL="https://127.0.0.1:9200", ES_USERNAME="private-fixture-user",
                ES_PASSWORD="private-fixture-password", SRAF_DEEP_ES_CA_CERT=certifi.where())
    return data


def test_local_partial_never_claims_live_acceptance(tmp_path, env):
    result = check_local(env, project_root=tmp_path)
    assert result["status"] == "PASS_PARTIAL"
    assert result["es_sdk_ca_setup"] == "PASS"
    assert result["chat_auto"] == "DISABLED"
    assert all(value == "NOT_TESTED" for key, value in result.items() if key.startswith("live_"))
    serialized = json.dumps(result)
    for secret in (env["ES_USERNAME"], env["ES_PASSWORD"], env["ES_URL"],
                   env["SRAF_DEEP_OWNER_GRANTS_JSON"], env["SRAF_DEEP_ES_CA_CERT"]):
        assert secret not in serialized
    assert list(tmp_path.iterdir()) == []


def test_disabled_and_invalid_are_distinguished(tmp_path, env):
    env["SRAF_DEEP_REPORT_ENABLED"] = "0"
    assert check_local(env, project_root=tmp_path)["status"] == "INCOMPLETE"
    assert check_local(env, project_root=tmp_path, require_auto=True)["status"] == "FAIL"
    env["SRAF_DEEP_REPORT_ENABLED"] = "yes"
    result = check_local(env, project_root=tmp_path)
    assert result["configuration"] == "FAIL" and result["status"] == "FAIL"


def test_auto_pilot_https_gate_is_local_only(tmp_path, env):
    assert check_local(env, project_root=tmp_path, require_auto=True)["reason"] == "chat_auto_disabled"
    env.update(SRAF_DEEP_CHAT_AUTO_ENABLED="1", PUBLIC_API_BASE="http://127.0.0.1:9002")
    result = check_local(env, project_root=tmp_path, require_auto=True)
    assert result["reason"] == "chat_auto_https_required_for_pilot"
    env["PUBLIC_API_BASE"] = "https://sraf.example.test"
    result = check_local(env, project_root=tmp_path, require_auto=True)
    assert result["status"] == "PASS_PARTIAL" and result["browser_origin"] == "HTTPS_CONFIGURED"
    assert result["live_openwebui_and_word"] == "NOT_TESTED"


def test_bad_es_setup_redacted(tmp_path, env):
    env["ES_URL"] = "http://private-fixture-host:9200"
    result = check_local(env, project_root=tmp_path)
    assert result["status"] == "FAIL" and result["es_sdk_ca_setup"] == "FAIL"
    assert "private-fixture" not in json.dumps(result)


def test_default_cli_does_not_read_configuration(capsys):
    assert main([]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_TESTED"
