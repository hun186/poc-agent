"""OFF-1D readiness: only deterministic bounded evidence, never FULL_LIVE."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1d_readiness_matrix as matrix


def _local(monkeypatch, *, disk="PASS", odbc="PASS"):
    monkeypatch.setattr(
        matrix, "probe_disk", lambda: SimpleNamespace(
            status=disk, reason="disk_threshold_met" if disk == "PASS"
            else "disk_space_low", executed=True))
    monkeypatch.setattr(
        matrix, "probe_odbc_library", lambda: SimpleNamespace(
            status=odbc,
            reason="odbc_library_file_observed" if odbc == "PASS"
            else "odbc_library_not_found", executed=True))


def _rows(report):
    return {row["id"]: row for row in report["results"]}


def _tcp(monkeypatch, statuses=None):
    statuses = statuses or {}
    calls = []

    def observe(service, cfg, *, no_network):
        calls.append((service, no_network))
        assert "ES_PASSWORD" in cfg
        probe = statuses.get(service, "PASS") if not no_network else "SKIP"
        return {
            "configuration": "RESOLVED", "tcp_probe": probe,
            "reason": ("network_disabled" if no_network else
                       "configured_tcp_connected" if probe == "PASS" else
                       "configured_tcp_unavailable"),
        }

    monkeypatch.setattr(matrix.tcp, "_observe", observe)
    return calls


def _health(monkeypatch, *, status="PASS"):
    calls = []

    def observe(cfg, *, no_network):
        assert not no_network
        calls.append(True)
        return {
            "configuration": "RESOLVED",
            "http_probe": status,
            "reason": "healthz_http_200" if status == "PASS"
            else "healthz_http_not_200",
            "http_status": 200 if status == "PASS" else 503,
            "http_method": "GET", "healthz_endpoint": "/healthz",
        }

    monkeypatch.setattr(matrix.api_http, "_observe", observe)
    return calls


def _cfg():
    return {
        "ES_URL": "https://192.168.10.25:9200",
        "ES_PASSWORD": "PRIVATE_CREDENTIAL",
        "ES_USERNAME": "operator-user",
        "MODEL_ID": "secret-model-name",
        "PUBLIC_API_BASE": "https://public.example.invalid/secret",
    }


def test_default_is_local_only_and_never_networks(monkeypatch):
    _local(monkeypatch)
    calls = _tcp(monkeypatch)
    health = _health(monkeypatch)
    report = matrix.build_report(_cfg())
    rows = _rows(report)
    assert calls == [("api", True), ("es", True), ("llm", True)]
    assert health == []
    assert report["schema"] == matrix.SCHEMA
    assert report["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert report["network_mode"] == "LOCAL_ONLY_NO_NETWORK"
    assert report["overall"] == "INCOMPLETE"
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert rows["HOST-DISK"]["status"] == "PASS"
    assert rows["SQL-ODBC"]["status"] == "PASS"
    assert rows["API-TCP"]["status"] == "SKIP"
    assert rows["API-HEALTH"]["status"] == "SKIP"
    assert rows["API-HEALTH"]["depends_on"] == ["API-TCP"]
    assert all(rows[key]["status"] == "NOT_TESTED" for key in (
        "SQL-READ", "ES-MAPPING", "LLM-INVENTORY", "LLM-INFERENCE",
        "WORKERS", "WORD", "ISOLATION"))
    assert all(item["feature_acceptance"] == "NOT_TESTED"
               for item in report["results"])
    text = json.dumps(report)
    assert all(value not in text for value in _cfg().values())
    assert "FULL_LIVE" not in text


def test_network_opt_in_probes_every_independent_tcp_and_then_api(monkeypatch):
    _local(monkeypatch)
    calls = _tcp(monkeypatch)
    health = _health(monkeypatch)
    report = matrix.build_report(_cfg(), probe_network=True)
    rows = _rows(report)
    assert calls == [("api", False), ("es", False), ("llm", False)]
    assert health == [True]
    assert report["network_mode"] == "BOUNDED_TCP_AND_LOOPBACK_HTTP"
    assert all(rows[key]["status"] == "PASS"
               for key in ("API-TCP", "API-HEALTH", "ES-TCP", "LLM-TCP"))
    assert report["overall"] == "INCOMPLETE"
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert rows["WORKERS"]["status"] == "NOT_TESTED"
    assert rows["WORD"]["status"] == "NOT_TESTED"


@pytest.mark.parametrize("failed", ["api", "es", "llm"])
def test_tcp_failure_does_not_cancel_other_independent_checks(monkeypatch, failed):
    _local(monkeypatch)
    calls = _tcp(monkeypatch, {failed: "FAIL"})
    health = _health(monkeypatch)
    result = matrix.build_report(_cfg(), probe_network=True)
    rows = _rows(result)
    assert [x[0] for x in calls] == ["api", "es", "llm"]
    assert rows[{"api": "API-TCP", "es": "ES-TCP", "llm": "LLM-TCP"}[failed]]["status"] == "FAIL"
    if failed == "api":
        assert health == []
        assert rows["API-HEALTH"]["status"] == "SKIP"
        assert rows["API-HEALTH"]["reason"] == "upstream_api_tcp_not_passed"
    else:
        assert health == [True]
        assert rows["API-HEALTH"]["status"] == "PASS"
    assert result["overall"] == "ISSUES_FOUND"
    assert result["counts"]["FAIL"] >= 1


@pytest.mark.parametrize("status,reason", [
    ("FAIL", "healthz_http_not_200"),
    ("FAIL", "api_transport_unavailable"),
    ("FAIL", "api_response_oversized"),
    ("SKIP", "config_not_resolved"),
])
def test_api_health_observation_is_bounded_and_not_an_identity_claim(
        monkeypatch, status, reason):
    _local(monkeypatch)
    _tcp(monkeypatch)
    monkeypatch.setattr(matrix.api_http, "_observe",
                        lambda *a, **k: {"http_probe": status,
                                         "reason": reason})
    report = matrix.build_report(_cfg(), probe_network=True)
    record = _rows(report)["API-HEALTH"]
    assert record["status"] == status
    assert record["reason"] == reason
    assert record["feature_acceptance"] == "NOT_TESTED"
    assert report["overall"] == (
        "ISSUES_FOUND" if status == "FAIL" else "INCOMPLETE")



@pytest.mark.parametrize("alter", [
    {"configuration": "INVALID"},
    {"configuration": "MISSING"},
    {"http_status": 503},
    {"http_status": True},
    {"http_status": None},
    {"reason": "healthz_http_not_200"},
    {"http_method": "POST"},
    {"healthz_endpoint": "/ready"},
])
def test_contradictory_health_pass_is_not_authoritative(monkeypatch, alter):
    _local(monkeypatch)
    _tcp(monkeypatch)
    fake = {
        "configuration": "RESOLVED",
        "http_probe": "PASS",
        "reason": "healthz_http_200",
        "http_status": 200,
        "http_method": "GET",
        "healthz_endpoint": "/healthz",
    }
    fake.update(alter)
    monkeypatch.setattr(matrix.api_http, "_observe",
                        lambda *a, **k: fake)
    result = matrix.build_report(_cfg(), probe_network=True)
    obs = _rows(result)["API-HEALTH"]
    assert obs["status"] != "PASS"
    assert obs["feature_acceptance"] == "NOT_TESTED"
    if alter.get("configuration") == "INVALID":
        assert obs["status"] == "SKIP"  # fake PASS does not override validation
    assert result["overall"] != "FULL_LIVE"


@pytest.mark.parametrize("source", ["disk", "odbc", "tcp", "health"])
def test_unknown_reason_fail_keeps_severity_and_is_redacted(
        monkeypatch, source, tmp_path, capsys):
    _local(monkeypatch)
    _tcp(monkeypatch)
    _health(monkeypatch)
    secret_reason = "backend-password=/private/secret"
    if source == "disk":
        monkeypatch.setattr(matrix, "probe_disk",
                            lambda: SimpleNamespace(
                                status="FAIL", reason=secret_reason,
                                executed=True))
    elif source == "odbc":
        monkeypatch.setattr(matrix, "probe_odbc_library",
                            lambda: SimpleNamespace(
                                status="FAIL", reason=secret_reason,
                                executed=True))
    elif source == "tcp":
        original = matrix.tcp._observe

        def fail_tcp(service, cfg, *, no_network):
            obs = original(service, cfg, no_network=no_network)
            if service == "es":
                obs["tcp_probe"] = "FAIL"
                obs["reason"] = secret_reason
            return obs

        monkeypatch.setattr(matrix.tcp, "_observe", fail_tcp)
    else:
        monkeypatch.setattr(matrix.api_http, "_observe",
                            lambda *a, **k: {
                                "configuration": "RESOLVED",
                                "http_probe": "FAIL",
                                "reason": secret_reason,
                                "http_status": 502,
                                "http_method": "GET",
                                "healthz_endpoint": "/healthz",
                            })
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: _cfg())
    assert matrix.main(["--probe-network"]) == 1
    payload = json.loads(capsys.readouterr().out)
    row_key = {
        "disk": "HOST-DISK", "odbc": "SQL-ODBC",
        "tcp": "ES-TCP", "health": "API-HEALTH",
    }[source]
    assert _rows(payload)[row_key]["status"] == "FAIL"
    assert _rows(payload)[row_key]["reason"] == "unexpected_probe_result"
    assert payload["overall"] == "ISSUES_FOUND"
    assert secret_reason not in json.dumps(payload)


@pytest.mark.parametrize("bad_profile", [
    "bad profile", "invalid/profile", "x" * 33, "stage\nleak",
])
def test_invalid_app_env_is_error_exit_one_without_probes_or_secrets(
        tmp_path, monkeypatch, capsys, bad_profile):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("APP_ENV", bad_profile)
    monkeypatch.setattr(matrix, "probe_disk",
                        lambda: pytest.fail("probes must not execute"))
    monkeypatch.setattr(matrix, "probe_odbc_library",
                        lambda: pytest.fail("probes must not execute"))
    monkeypatch.setattr(matrix.tcp, "_observe",
                        lambda *a, **k: pytest.fail("network attempted"))
    assert matrix.main(["--probe-network"]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["error"] == "runtime_profile_invalid"
    assert report["overall"] == "ISSUES_FOUND"
    assert report["feature_acceptance"] == "NOT_TESTED"
    assert bad_profile not in output
    assert "FULL_LIVE" not in output


def test_unexpected_profile_loader_value_error_is_still_incomplete(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    def exception(root):
        raise ValueError("secret from .env parser")
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config", exception)
    assert matrix.main(["--probe-network"]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["error"] == "readiness_matrix_unavailable"
    assert "secret" not in output


def test_invalid_config_is_failure_even_in_no_network_mode(monkeypatch):
    _local(monkeypatch)
    def observe(service, cfg, *, no_network):
        return {"configuration": "INVALID" if service == "es" else "MISSING",
                "tcp_probe": "SKIP", "reason": "config_not_resolved"}
    monkeypatch.setattr(matrix.tcp, "_observe", observe)
    monkeypatch.setattr(matrix.api_http, "_observe",
                        lambda *a, **k: pytest.fail("no health request"))
    report = matrix.build_report(_cfg())
    assert _rows(report)["ES-TCP"]["status"] == "FAIL"
    assert _rows(report)["ES-TCP"]["reason"] == "configuration_invalid"
    assert report["overall"] == "ISSUES_FOUND"


def test_local_odbc_observation_never_claims_sql_connectivity(monkeypatch):
    _local(monkeypatch, odbc="WARN")
    _tcp(monkeypatch)
    _health(monkeypatch)
    report = matrix.build_report(_cfg())
    rows = _rows(report)
    assert rows["SQL-ODBC"]["status"] == "WARN"
    assert rows["SQL-READ"]["status"] == "NOT_TESTED"
    assert rows["SQL-READ"]["depends_on"] == ["SQL-ODBC"]
    assert "sql_server_read_only" in rows["SQL-READ"]["aspect"]


def test_untrusted_exception_or_reason_is_never_printed(monkeypatch):
    monkeypatch.setattr(matrix, "probe_disk",
                        lambda: (_ for _ in ()).throw(
                            RuntimeError("PASSWORD=secret_and_path=/private/secret")))
    monkeypatch.setattr(matrix, "probe_odbc_library",
                        lambda: SimpleNamespace(
                            status="PASS", reason="/private/token-abc",
                            executed=True))
    monkeypatch.setattr(matrix.tcp, "_observe",
                        lambda *a, **k: {"configuration": "RESOLVED",
                                         "tcp_probe": "PASS",
                                         "reason": "Bearer private-token"})
    monkeypatch.setattr(matrix.api_http, "_observe",
                        lambda *a, **k: {"http_probe": "PASS",
                                         "reason": "private-api-response"})
    report = matrix.build_report(_cfg(), probe_network=True)
    output = json.dumps(report)
    for marker in ("PASSWORD=", "/private/", "token-abc",
                   "Bearer", "private-api-response"):
        assert marker not in output
    assert _rows(report)["HOST-DISK"]["status"] == "FAIL"
    assert _rows(report)["SQL-ODBC"]["reason"] == "unexpected_probe_result"
    assert _rows(report)["SQL-ODBC"]["status"] == "SKIP"
    # An unrecognized PASS-looking response never becomes evidence.
    assert _rows(report)["API-TCP"]["status"] == "SKIP"
    assert _rows(report)["ES-TCP"]["status"] == "SKIP"
    assert _rows(report)["API-HEALTH"]["status"] == "SKIP"
    assert report["feature_acceptance"] == "NOT_TESTED"


def test_aggregated_counts_and_fixed_dependency_graph(monkeypatch):
    _local(monkeypatch)
    _tcp(monkeypatch, {"es": "FAIL"})
    _health(monkeypatch)
    report = matrix.build_report(_cfg(), probe_network=True)
    assert len(report["results"]) == 13
    assert sum(report["counts"].values()) == 13
    assert len({item["id"] for item in report["results"]}) == 13
    rows = _rows(report)
    assert rows["ES-MAPPING"]["depends_on"] == ["ES-TCP"]
    assert rows["LLM-INFERENCE"]["depends_on"] == ["LLM-INVENTORY"]
    assert rows["WORKERS"]["depends_on"] == ["API-HEALTH", "SQL-READ"]
    assert rows["WORD"]["depends_on"] == ["WORKERS", "LLM-INFERENCE"]


def test_cli_default_is_offline_partial_and_exit_two(tmp_path, monkeypatch, capsys):
    _local(monkeypatch)
    _tcp(monkeypatch)
    _health(monkeypatch)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: _cfg())
    assert matrix.main([]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert output["network_mode"] == "LOCAL_ONLY_NO_NETWORK"
    assert "PRIVATE_CREDENTIAL" not in json.dumps(output)


def test_cli_failure_exit_one_but_not_full_live(tmp_path, monkeypatch, capsys):
    _local(monkeypatch)
    _tcp(monkeypatch, {"es": "FAIL"})
    _health(monkeypatch)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: _cfg())
    assert matrix.main(["--probe-network"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["overall"] == "ISSUES_FOUND"
    assert result["feature_acceptance"] == "NOT_TESTED"


def test_wrong_cwd_does_not_load_settings_or_probe(tmp_path, monkeypatch, capsys):
    root = tmp_path / "app"
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", root)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda *a: pytest.fail("settings accessed"))
    assert matrix.main(["--probe-network"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == (
        "run_from_repository_root")


def test_unavailable_runtime_configuration_redacted(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    def unavailable(*a):
        raise ValueError("operator-private-password-and-path")
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config", unavailable)
    assert matrix.main(["--probe-network"]) == 2
    text = capsys.readouterr().out
    assert json.loads(text)["error"] == "readiness_matrix_unavailable"
    assert "operator-private" not in text
