"""SRAF operator read-only baseline: composed checks cannot assert E2E."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import sraf_runtime_baseline_readonly as baseline
from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1s_api_listener import ListenerProof


def _observation(status, evidence=None):
    return Observation("TEST", "test", "test", status, "opaque private path secret",
                       True, evidence or {})


@pytest.fixture
def valid_env(monkeypatch, tmp_path):
    root = tmp_path / "deployed-repository"
    root.mkdir()
    monkeypatch.setattr(baseline.sys, "platform", "linux")
    monkeypatch.setattr(baseline, "probe_worker_process_identities",
                        lambda _: _observation("PASS", {"verified_role_count": 2}))
    return root


def test_verified_snapshot_is_partial_only_and_redacted(monkeypatch, valid_env):
    observed = {"listener": 0, "health": 0}
    def listener(root, port):
        assert root == valid_env and port == "9002"
        observed["listener"] += 1
        return ListenerProof(1234, "10001", 9002, "56789")
    def health(port):
        assert port == 9002
        observed["health"] += 1
        return _observation("PASS", {"http_status": 200})
    monkeypatch.setattr(baseline, "attest_api_listener", listener)
    monkeypatch.setattr(baseline, "probe_api_health", health)
    data = baseline.observe(valid_env, "9002")
    assert data["overall"] == "PASS"
    assert data["feature_acceptance"] == "NOT_TESTED"
    assert data["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"
    assert data["loopback_http_requests"] == 1
    assert (observed["listener"], observed["health"]) == (2, 1)
    assert all(check["status"] == "PASS" for check in data["checks"].values())
    assert data["external_network_requests"] == 0 and data["model_inferences"] == 0
    assert data["credentials_sent"] is False and data["mutations"] == 0
    serialized = json.dumps(data)
    for sensitive in ("9002", str(valid_env), "opaque private path secret", "PID", "password"):
        assert sensitive not in serialized


def test_unverified_listener_never_sends_http(monkeypatch, valid_env):
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_: None)
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda *_: pytest.fail("must not open a socket"))
    data = baseline.observe(valid_env, "9002")
    assert data["overall"] == "INCOMPLETE"
    assert data["checks"]["API-HEALTH"]["status"] == "SKIP"
    assert data["checks"]["WORKER-IDENTITIES"]["status"] == "PASS"
    assert data["loopback_http_requests"] == 0


def test_listener_changes_after_health_invalidates_both(monkeypatch, valid_env):
    calls = iter((ListenerProof(1234, "10001", 9002, "56789"),
                  ListenerProof(5678, "20002", 9002, "98765")))
    monkeypatch.setattr(baseline, "attest_api_listener",
                        lambda *_: next(calls))
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda *_: ListenerProof(1234, "10001", 9002, "56789"))
    data = baseline.observe(valid_env, "9002")
    assert data["checks"]["API-LISTENER"]["status"] == "SKIP"
    assert data["checks"]["API-HEALTH"]["status"] == "SKIP"
    assert data["overall"] == "INCOMPLETE"
    assert data["loopback_http_requests"] == 1


def test_no_network_mode_skips_even_anonymous_get(monkeypatch, valid_env):
    calls = []
    def listener(*_):
        calls.append(1)
        return ListenerProof(1234, "10001", 9002, "56789")
    monkeypatch.setattr(baseline, "attest_api_listener", listener)
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda *_: pytest.fail("no-network called GET"))
    data = baseline.observe(valid_env, "9002", no_network=True)
    assert len(calls) == 1
    assert data["overall"] == "INCOMPLETE"
    assert data["checks"]["API-HEALTH"]["reason"] == "network_disabled"
    assert data["loopback_http_requests"] == 0


@pytest.mark.parametrize("port", ["0", "-1", "65536", "abc", "9002x",
                                  "09002", "9002;touch /tmp/x", "", "²"])
def test_invalid_port_never_reaches_probes(monkeypatch, valid_env, port):
    monkeypatch.setattr(baseline, "attest_api_listener",
                        lambda *_: pytest.fail("bad port reached listener"))
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda *_: pytest.fail("bad port reached health"))
    monkeypatch.setattr(baseline, "probe_worker_process_identities",
                        lambda *_: pytest.fail("bad port reached worker"))
    data = baseline.observe(valid_env, port)
    assert data["overall"] == "INCOMPLETE"
    assert data["loopback_http_requests"] == 0


def test_untrusted_path_never_reaches_probes(monkeypatch, tmp_path):
    monkeypatch.setattr(baseline, "attest_api_listener",
                        lambda *_: pytest.fail("bad root reached listener"))
    assert baseline.observe(Path("relative-repo"), "9002")["overall"] == "INCOMPLETE"
    assert baseline.observe(tmp_path / "missing", "9002")["overall"] == "INCOMPLETE"


def test_http_exception_is_sanitized_and_worker_failure_independent(monkeypatch, valid_env):
    monkeypatch.setattr(baseline, "attest_api_listener",
                        lambda *_: ListenerProof(1234, "10001", 9002, "56789"))
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda *_: (_ for _ in ()).throw(OSError("Bearer secret private URL")))
    monkeypatch.setattr(baseline, "probe_worker_process_identities",
                        lambda *_: (_ for _ in ()).throw(ValueError("secret path")))
    data = baseline.observe(valid_env, "9002")
    assert data["overall"] == "INCOMPLETE"
    assert data["checks"]["API-HEALTH"]["status"] == "SKIP"
    assert data["checks"]["WORKER-IDENTITIES"]["status"] == "SKIP"
    assert "secret" not in json.dumps(data).lower()


def test_cli_returns_2_for_incomplete_and_never_prints_root(tmp_path, capsys):
    result = baseline.main(["--project-root", str(tmp_path / "not-installed"),
                            "--api-port", "9002"])
    assert result == 2
    output = capsys.readouterr()
    parsed = json.loads(output.out)
    assert parsed["overall"] == "INCOMPLETE"
    assert str(tmp_path) not in output.out
    assert not output.err
