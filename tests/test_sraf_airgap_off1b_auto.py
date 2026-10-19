"""Regression coverage for safe OFF-1B environment discovery / TCP-only preflight."""
import json
import socket

import pytest

from tools import sraf_airgap_off1b_auto as auto


@pytest.mark.parametrize(("raw", "status", "scope", "port"), [
    ("https://192.168.0.134:9001", "RESOLVED", "RFC1918_IPV4", 9001),
    ("http://192.168.0.134:18080", "RESOLVED", "RFC1918_IPV4", 18080),
    ("http://127.0.0.1:9002", "RESOLVED", "LOOPBACK_IPV4", 9002),
    ("http://10.1.2.3:80", "RESOLVED", "RFC1918_IPV4", 80),
    ("http://172.16.0.1", "RESOLVED", "RFC1918_IPV4", 80),
    ("https://es.internal:9200", "RESOLVED", "DNS_NAME_NOT_PROBED", 9200),
    ("https://8.8.8.8", "RESOLVED", "NON_PRIVATE_IPV4_NOT_PROBED", 443),
    ("https://169.254.169.254", "RESOLVED", "NON_PRIVATE_IPV4_NOT_PROBED", 443),
    ("http://[::1]:8080", "RESOLVED", "NON_IPV4_NOT_PROBED", 8080),
    ("http://192.168.0.134:9001/_search", "INVALID", "UNRESOLVED", None),
    ("http://secret:pass@192.168.0.134:9001", "INVALID", "UNRESOLVED", None),
    ("http://192.168.0.134:9001?token=xyz", "INVALID", "UNRESOLVED", None),
    ("http://192.168.0.134:9001#secret", "INVALID", "UNRESOLVED", None),
    ("http://192.168.0.134:0", "INVALID", "UNRESOLVED", None),
    ("http://192.168.0.134:99999", "INVALID", "UNRESOLVED", None),
    ("http://192.168.0.134:bad", "INVALID", "UNRESOLVED", None),
    ("http://192.168.0.134:9001\nsecret", "INVALID", "UNRESOLVED", None),
    (" ftp://192.168.0.134:21 ", "INVALID", "UNRESOLVED", None),
    (None, "MISSING", "UNRESOLVED", None),
])
def test_url_policy(raw, status, scope, port):
    info, host = auto._parse_endpoint(raw)
    assert (info["configuration"], info["host_scope"], info["port"]) == (
        status, scope, port)
    if scope in ("RFC1918_IPV4", "LOOPBACK_IPV4") and status == "RESOLVED":
        assert host
    else:
        assert host is None


def test_actual_bootstrap_env_precedence(tmp_path, monkeypatch, capsys):
    from config import bootstrap
    (tmp_path / ".env").write_text(
        "ES_URL=http://10.0.0.1:9200\nMODEL_ID=base\n")
    (tmp_path / ".env.dev").write_text(
        "ES_URL=http://10.0.0.2:9200\nMODEL_ID=dev\n")
    (tmp_path / ".env.local").write_text(
        "ES_URL=https://192.168.0.134:9001\nMODEL_ID=local\n")
    monkeypatch.setattr(bootstrap, "_BOOTSTRAPPED", False)
    for key in ("ES_URL", "MODEL_ID", "APP_ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MODEL_ID", "os_env")
    values = auto._effective_runtime_config(tmp_path)
    assert values["ES_URL"] == "https://192.168.0.134:9001"
    assert values["MODEL_ID"] == "os_env"
    assert capsys.readouterr().out == ""


def test_invalid_profile_rejected_before_reading_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "../../secret")
    with pytest.raises(ValueError, match="invalid_profile"):
        auto._effective_runtime_config(tmp_path)


def test_observation_never_discloses_url_credentials_or_model(monkeypatch):
    recorded = []
    monkeypatch.setattr(auto, "_tcp_connect",
                        lambda host, port: recorded.append((host, port)) or True)
    cfg = {
        "ES_URL": "https://192.168.0.134:9001",
        "ES_PASSWORD": "TOP_SECRET_ES_PASSWORD",
        "MODEL_BASE_URL": "http://192.168.0.134:18080",
        "MODEL_ID": "INTERNAL_MODEL_NAME",
    }
    es = auto._observe("es", cfg, no_network=False)
    llm = auto._observe("llm", cfg, no_network=False)
    output = json.dumps([es, llm])
    assert recorded == [("192.168.0.134", 9001), ("192.168.0.134", 18080)]
    assert es["tcp_probe"] == "PASS" and es["auth"] == "NOT_TESTED"
    assert llm["tcp_probe"] == "PASS" and llm["model_configured"] is True
    for secret in ("192.168.0.134", "TOP_SECRET_ES_PASSWORD", "INTERNAL_MODEL_NAME"):
        assert secret not in output


def test_dns_and_public_ip_never_probed(monkeypatch):
    def forbidden(*args):
        pytest.fail("Out-of-scope network target was probed")
    monkeypatch.setattr(auto, "_tcp_connect", forbidden)
    for url in ("https://es.internal:9001", "http://8.8.8.8:11434",
                "http://169.254.169.254:80"):
        record = auto._observe("es", {"ES_URL": url}, no_network=False)
        assert record["tcp_probe"] == "SKIP"
        assert record["reason"] == "endpoint_outside_bounded_tcp_scope"


def test_no_network_mode_does_not_open_socket(monkeypatch):
    monkeypatch.setattr(
        auto, "_tcp_connect",
        lambda *args: pytest.fail("socket used in no-network mode"),
    )
    record = auto._observe(
        "api", {"PUBLIC_API_BASE": "http://192.168.0.134:9002"},
        no_network=True,
    )
    assert record["tcp_probe"] == "SKIP"
    assert record["reason"] == "network_disabled"


def test_failed_connect_classified_without_exception(monkeypatch):
    monkeypatch.setattr(auto, "_tcp_connect", lambda *args: False)
    record = auto._observe(
        "es", {"ES_URL": "https://192.168.0.134:9001"},
        no_network=False,
    )
    assert record["tcp_probe"] == "FAIL"
    assert record["reason"] == "configured_tcp_unavailable"
    assert record["tls_validation"] == "NOT_TESTED"


def test_real_loopback_tcp_connection_without_http():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        assert auto._tcp_connect("127.0.0.1", listener.getsockname()[1])


def test_cli_reports_only_partial_observations(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(auto, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        auto, "_effective_runtime_config", lambda root: {
            "PUBLIC_API_BASE": "http://192.168.0.134:9002",
            "ES_URL": "https://192.168.0.134:9001",
            "MODEL_BASE_URL": "http://192.168.0.134:18080",
            "TOPIC_LLM_URL": "http://192.168.0.134:18080",
        },
    )
    monkeypatch.setattr(auto, "_tcp_connect", lambda host, port: True)
    assert auto.main([]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert len(payload["results"]) == 4
    assert all(x["tcp_probe"] == "PASS" for x in payload["results"])
    assert all(x["feature_acceptance"] == "NOT_TESTED" for x in payload["results"])
    assert "192.168.0.134" not in output


def test_cli_out_of_root_denied(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(auto, "PROJECT_ROOT", tmp_path / "real-root")
    monkeypatch.chdir(tmp_path)
    assert auto.main([]) == 2
    assert "run_from_repository_root" in capsys.readouterr().out


def test_cli_skip_returns_two(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(auto, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        auto, "_effective_runtime_config",
        lambda root: {"ES_URL": "https://es.internal:9200"},
    )
    assert auto.main(["--check", "es"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["tcp_probe"] == "SKIP"
