"""OFF-1E local Ollama inventory is optional and never inference acceptance."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1d_readiness_matrix as matrix
from tools.sraf_airgap_off1_probes import Observation


def _config(url="http://127.0.0.1:11434/api/chat",
            model="private-model:latest"):
    return {"MODEL_BASE_URL": url, "MODEL_ID": model,
            "ES_PASSWORD": "SECRET_SHOULD_NOT_APPEAR"}


def _obs(status="PASS", reason="configured_model_listed", *,
         available=True, http_status=200, item_count=2, executed=True):
    return Observation(
        "LLM-01", "llm-inventory", "named_model_inventory_only",
        status, reason, executed,
        {"model_available": available, "http_status": http_status,
         "item_count": item_count},
    )


def _inventory(monkeypatch, result=None):
    calls = []
    def fake(port, name, *, backend):
        calls.append((port, name, backend))
        return result or _obs()
    monkeypatch.setattr(matrix, "probe_llm_inventory", fake)
    return calls


def _check(cfg, *, network=True, opt_in=True, tcp="PASS"):
    return matrix._llm_inventory(
        cfg, probe_network=network, probe_model_inventory=opt_in,
        tcp_status=tcp)


def test_explicit_opt_in_calls_reviewed_one_get_and_redacts(monkeypatch):
    calls = _inventory(monkeypatch)
    result = _check(_config())
    assert calls == [(11434, "private-model:latest", "ollama")]
    assert result["status"] == "PASS"
    assert result["reason"] == "configured_model_listed"
    assert result["executed"] is True
    assert result["depends_on"] == ["LLM-TCP"]
    assert result["feature_acceptance"] == "NOT_TESTED"
    assert all(v not in json.dumps(result) for v in _config().values())
    assert "FULL_LIVE" not in json.dumps(result)


@pytest.mark.parametrize("network,opt_in,tcp,reason", [
    (False, False, "PASS", "network_disabled"),
    (False, True, "PASS", "network_disabled"),
    (True, False, "PASS", "llm_inventory_not_requested"),
    (True, True, "SKIP", "llm_inventory_tcp_not_passed"),
    (True, True, "FAIL", "llm_inventory_tcp_not_passed"),
])
def test_flag_and_tcp_gates_have_no_inventory_network(
        monkeypatch, network, opt_in, tcp, reason):
    monkeypatch.setattr(matrix, "probe_llm_inventory",
                        lambda *a, **k: pytest.fail("unexpected GET"))
    obs = _check(_config(), network=network, opt_in=opt_in, tcp=tcp)
    assert obs["reason"] == reason
    assert obs["status"] in ("SKIP", "NOT_TESTED")
    assert obs["executed"] is False


@pytest.mark.parametrize("url", [
    "http://192.168.1.20:11434", "http://127.0.0.2:11434",
    "https://127.0.0.1:11434", "http://localhost:11434",
    "http://8.8.8.8:11434", "http://127.0.0.1:11434/ollama",
    "http://127.0.0.1:11434/gateway/api/chat",
    "http://[::1]:11434", "http://127.0.0.1:11434@evil.test",
    "http://127.0.0.1:11434?query=secret",
    "file:///tmp", "", "http://127.0.0.1:0",
])
def test_out_of_scope_urls_never_dispatch_inventory(monkeypatch, url):
    monkeypatch.setattr(matrix, "probe_llm_inventory",
                        lambda *a, **k: pytest.fail("out of scope GET"))
    result = _check(_config(url=url))
    assert result["status"] == "SKIP"
    assert result["reason"] == "llm_inventory_endpoint_outside_scope"
    assert url not in json.dumps(result)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:11434/",
    "http://127.0.0.1:11434/api/chat",
    "http://127.0.0.1:11434/api/generate/",
])
def test_only_supported_local_ollama_roots_allowed(monkeypatch, url):
    calls = _inventory(monkeypatch)
    result = _check(_config(url=url))
    assert result["status"] == "PASS"
    assert len(calls) == 1
    assert calls[0][0] == 11434


@pytest.mark.parametrize("model", [
    None, "", "model name", "mod\nEL", "x" * 257,
    "bad\x00value", "bad\tname", "秘密模型",
])
def test_unsafe_or_absent_model_name_never_dispatches(monkeypatch, model):
    monkeypatch.setattr(matrix, "probe_llm_inventory",
                        lambda *a, **k: pytest.fail("unsafe model GET"))
    result = _check(_config(model=model))
    assert result["status"] == "SKIP"
    assert result["reason"] in ("model_name_not_configured",
                                "llm_inventory_model_invalid")
    if isinstance(model, str):
        assert model not in json.dumps(result)


@pytest.mark.parametrize("observation,expected,reason", [
    (_obs(status="FAIL", reason="configured_model_not_listed",
          available=False), "FAIL", "configured_model_not_listed"),
    (_obs(status="FAIL", reason="model_service_unavailable"),
     "FAIL", "model_service_unavailable"),
    (_obs(status="FAIL", reason="model_inventory_invalid"),
     "FAIL", "model_inventory_invalid"),
    (_obs(status="FAIL", reason="PRIVATE_SECRET_FROM_SERVER"),
     "FAIL", "unexpected_probe_result"),
    (_obs(status="SKIP", reason="model_inventory_auth_required",
          http_status=401), "SKIP", "model_inventory_auth_required"),
    (_obs(status="SKIP", reason="model_inventory_auth_required",
          http_status=403), "SKIP", "model_inventory_auth_required"),
    (_obs(status="SKIP", reason="model_inventory_auth_required",
          http_status=200), "SKIP", "unexpected_probe_result"),
    (_obs(available=False), "SKIP", "unexpected_probe_result"),
    (_obs(http_status=503), "SKIP", "unexpected_probe_result"),
    (_obs(http_status=True), "SKIP", "unexpected_probe_result"),
    (_obs(item_count=0), "SKIP", "unexpected_probe_result"),
    (_obs(item_count=True), "SKIP", "unexpected_probe_result"),
    (_obs(executed=False), "SKIP", "unexpected_probe_result"),
    (_obs(reason="PRIVATE_SUCCESS"), "SKIP", "unexpected_probe_result"),
])
def test_inventory_nested_provider_invariants_fail_closed(
        monkeypatch, observation, expected, reason):
    _inventory(monkeypatch, result=observation)
    result = _check(_config())
    assert (result["status"], result["reason"]) == (expected, reason)
    assert result["feature_acceptance"] == "NOT_TESTED"
    assert "PRIVATE" not in json.dumps(result)


def test_nested_inventory_exception_redacted(monkeypatch):
    def bad(*args, **kwargs):
        raise RuntimeError("model secret and private IP 127.0.0.1")
    monkeypatch.setattr(matrix, "probe_llm_inventory", bad)
    result = _check(_config())
    assert result["status"] == "FAIL"
    assert result["reason"] == "probe_internal_failure"
    assert "secret" not in json.dumps(result)


def test_matrix_integration_inventory_requires_two_flags(monkeypatch):
    calls = _inventory(monkeypatch)
    monkeypatch.setattr(
        matrix, "_local_probe",
        lambda key, component, aspect, fn:
        matrix._record(key, component, aspect, "SKIP", "network_disabled"),
    )
    def tcp_fake(service, cfg, *, probe_network):
        status = "PASS" if probe_network else "SKIP"
        return matrix._record(
            {"api": "API-TCP", "es": "ES-TCP", "llm": "LLM-TCP"}[service],
            service, "configured_tcp_only", status,
            "configured_tcp_connected" if probe_network else "network_disabled")
    monkeypatch.setattr(matrix, "_tcp_probe", tcp_fake)
    monkeypatch.setattr(
        matrix, "_api_health",
        lambda *a, **k: matrix._record(
            "API-HEALTH", "api", "healthz_http_only", "SKIP",
            "network_disabled"),
    )
    cfg = _config()
    for network, inventory, expected in [
        (False, True, "NOT_TESTED"),
        (True, False, "NOT_TESTED"),
        (True, True, "PASS"),
    ]:
        report = matrix.build_report(
            cfg, probe_network=network, probe_model_inventory=inventory)
        row = {r["id"]: r for r in report["results"]}["LLM-INVENTORY"]
        assert row["status"] == expected
        assert report["feature_acceptance"] == "NOT_TESTED"
        assert report["overall"] == "INCOMPLETE"
    assert len(calls) == 1


def test_cli_switch_requires_network_flag_and_exits_incomplete(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: _config())
    calls = _inventory(monkeypatch)
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda key, component, aspect, fn:
                        matrix._record(key, component, aspect, "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_tcp_probe",
                        lambda service, *a, **k:
                        matrix._record({"api":"API-TCP","es":"ES-TCP",
                                        "llm":"LLM-TCP"}[service],
                                       service, "configured_tcp_only", "PASS",
                                       "configured_tcp_connected"))
    monkeypatch.setattr(matrix, "_api_health",
                        lambda *a, **k:
                        matrix._record("API-HEALTH", "api",
                                       "healthz_http_only", "SKIP",
                                       "network_disabled"))
    assert matrix.main(["--probe-llm-inventory"]) == 2
    output = json.loads(capsys.readouterr().out)
    row = {r["id"]: r for r in output["results"]}["LLM-INVENTORY"]
    assert row["status"] == "NOT_TESTED"
    assert calls == []
    assert matrix.main(["--probe-network", "--probe-llm-inventory"]) == 2
    output2 = json.loads(capsys.readouterr().out)
    row2 = {r["id"]: r for r in output2["results"]}["LLM-INVENTORY"]
    assert row2["status"] == "PASS"
    assert len(calls) == 1
    assert output2["feature_acceptance"] == "NOT_TESTED"
