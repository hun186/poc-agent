"""Synthetic, no-network coverage for explicitly CA-verified ES IP SAN warnings."""
from __future__ import annotations

from pathlib import Path
import pytest

from tools import sraf_airgap_off1_es_hub as es_hub
from tools import sraf_airgap_off1b_es_https_mapping as transport
from tools import sraf_operator_diagnostics as diagnostics


def raw(**overrides):
    record = {
        "ip_san_policy": "WARN_ONLY",
        "identity_warning": True,
        "credential_control": "NOT_RUN",
        "https_probe": "PASS",
        "tls_validation": "WARN",
        "mapping_probe": "WARN",
        "auth": "NOT_VERIFIED",
        "credentials": "SECRET_PASSWORD_NOT_FOR_LOGS",
        "endpoint": "https://192.168.0.134:9001",
    }
    record.update(overrides)
    return record


def fake_probe(monkeypatch, observed):
    calls = []
    def observe(cfg, *, no_network, root, verify_credentials, warn_only_ip_san):
        calls.append({
            "no_network": no_network,
            "root": root,
            "verify_credentials": verify_credentials,
            "warn_only_ip_san": warn_only_ip_san,
        })
        if isinstance(observed, Exception):
            raise observed
        return observed
    monkeypatch.setattr(transport, "_observe", observe)
    result = es_hub.ca_only_mapping_observation(
        {"ES_PASSWORD": "SECRET_PASSWORD_NOT_FOR_LOGS"}, Path("/sraf"))
    assert calls == [{
        "no_network": False, "root": Path("/sraf"),
        "verify_credentials": False, "warn_only_ip_san": True,
    }]
    assert "SECRET" not in str(result)
    assert "192.168" not in str(result)
    return result


def test_ip_san_mismatch_is_incomplete_not_success(monkeypatch):
    row = fake_probe(monkeypatch, raw())
    assert row == {
        "check": "es_ca_only_tls_mapping",
        "status": "SKIP",
        "reason": "es_ca_only_mapping_observed_ip_san_unverified",
    }


def test_valid_san_also_cannot_certify_basic_auth(monkeypatch):
    row = fake_probe(monkeypatch, raw(
        identity_warning=False, tls_validation="PASS",
        mapping_probe="PASS"))
    assert row["status"] == "SKIP"
    assert row["reason"] == "es_tls_mapping_observed_auth_not_verified"


@pytest.mark.parametrize("overrides, expected", [
    ({"tls_validation": "FAIL", "https_probe": "FAIL"}, ("FAIL", "es_tls_identity_failed")),
    ({"https_probe": "FAIL"}, ("FAIL", "es_https_identity_failed")),
    ({"auth": "FAIL"}, ("FAIL", "es_auth_rejected")),
    ({"mapping_probe": "FAIL", "identity_warning": False}, ("FAIL", "es_mapping_failed")),
    ({"mapping_probe": "FAIL"}, ("SKIP", "es_ca_only_mapping_unverified")),
    ({"mapping_probe": "SKIP"}, ("SKIP", "es_ca_only_incomplete")),
])
def test_ca_transport_and_mapping_failures_never_ignored(monkeypatch, overrides, expected):
    result = fake_probe(monkeypatch, raw(**overrides))
    assert (result["status"], result["reason"]) == expected


@pytest.mark.parametrize("overrides", [
    {"ip_san_policy": "STRICT"},
    {"credential_control": "PASS"},
    {"identity_warning": "YES"},
    {"tls_validation": "INVALID"},
    {"https_probe": "INVALID"},
    {"mapping_probe": "INVALID"},
    {"auth": "INVALID"},
])
def test_policy_or_contract_mismatch_fails_closed(monkeypatch, overrides):
    row = fake_probe(monkeypatch, raw(**overrides))
    assert (row["status"], row["reason"]) == (
        "SKIP", "es_ca_only_observation_unavailable")


@pytest.mark.parametrize("observed", [
    None, [], RuntimeError("SECRET_NATIVE_CA_ERROR"), {"wrong": "shape"}
])
def test_untrusted_observations_never_expose_secrets(monkeypatch, observed):
    row = fake_probe(monkeypatch, observed)
    assert row["status"] == "SKIP"
    assert row["reason"] == "es_ca_only_observation_unavailable"


def test_diagnostic_route_must_be_explicit(monkeypatch):
    monkeypatch.setattr(es_hub, "strict_mapping_observation",
                        lambda cfg, root: {"status": "FAIL", "reason": "es_tls_identity_failed"})
    monkeypatch.setattr(es_hub, "ca_only_mapping_observation",
                        lambda cfg, root: {"status": "SKIP", "reason":
                                           "es_ca_only_mapping_observed_ip_san_unverified"})
    assert diagnostics._es_status({}) == ("FAIL", "es_tls_identity_failed")
    assert diagnostics._es_status({}, warn_only_ip_san=True) == (
        "SKIP", "es_ca_only_mapping_observed_ip_san_unverified")


@pytest.mark.parametrize("argv", [
    ["--es-warn-only-ip-san"],
    ["--level", "L0", "--es-warn-only-ip-san", "--probe-es-tls-mapping"],
    ["--level", "L1", "--es-warn-only-ip-san", "--probe-es-tls-mapping"],
    ["--level", "L2", "--es-warn-only-ip-san", "--probe-sql-read"],
    ["--level", "L3", "--es-warn-only-ip-san", "--probe-es-tls-mapping"],
])
def test_cli_rejects_ca_only_without_exact_l2_es_selection(monkeypatch, argv):
    def forbidden(*args, **kwargs):
        raise AssertionError("network or probe must not run")
    monkeypatch.setattr(diagnostics, "run", forbidden)
    with pytest.raises(SystemExit) as result:
        diagnostics.main(argv)
    assert result.value.code == 2


def test_l2_ca_only_explicit_mode_cannot_upgrade_overall_to_pass(monkeypatch):
    from argparse import Namespace
    def l0(port):
        return "PASS_PARTIAL", [diagnostics._row(
            "L0."+n, "PASS_PARTIAL", "observed") for n in diagnostics.L0_CHECKS]
    def l1():
        return {"ES_URL": "private"}, [
            diagnostics._row("L1."+n, "PASS", "observed")
            for n in diagnostics.L1_CHECKS]
    monkeypatch.setattr(diagnostics, "_local_rows", l0)
    monkeypatch.setattr(diagnostics, "_l1_rows", l1)
    calls = []
    def es_status(cfg, *, warn_only_ip_san=False):
        calls.append(warn_only_ip_san)
        return "SKIP", "es_ca_only_mapping_observed_ip_san_unverified"
    monkeypatch.setattr(diagnostics, "_es_status", es_status)
    flags = Namespace(
        level="L2", probe_sql_read=False, probe_es_tls_mapping=True,
        probe_llm_inference=False, ollama_server_pid=None, live_report=False,
        full_e2e=False, verification="release", max_seconds=1200,
        es_warn_only_ip_san=True
    )
    result = diagnostics.run(flags)
    assert calls == [True]
    assert result["status"] == "INCOMPLETE"
    observed = next(c for c in result["checks"] if c["id"] == "L2.es_tls_mapping")
    assert observed["status"] == "SKIP"
    assert observed["reason"] == "es_ca_only_mapping_observed_ip_san_unverified"
    assert type(observed["elapsed_ms"]) is int and observed["elapsed_ms"] >= 0
    assert result["production_release_ready"] is False
