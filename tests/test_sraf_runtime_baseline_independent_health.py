"""OFF-1S failure may not block opt-in anonymous /healthz; no bearer authority."""
from __future__ import annotations

import json

import pytest

from tools import sraf_runtime_baseline_readonly as baseline
from tools.sraf_airgap_off1s_api_listener import ListenerProof
from tools.sraf_airgap_off1_probes import Observation


@pytest.fixture
def root(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(baseline.sys, "platform", "linux")
    monkeypatch.setattr(
        baseline, "probe_worker_process_identities",
        lambda _: Observation(
            "TEST", "test", "test", "PASS", "safe", True,
            {"verified_role_count": 2}),
    )
    return root


def _health(status):
    return Observation("TEST", "test", "test", status, "safe", True,
                       {"http_status": 200 if status == "PASS" else 503})


def test_without_opt_in_unverified_listener_sends_no_http(monkeypatch, root):
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_: None)
    monkeypatch.setattr(baseline, "probe_api_health", lambda *_:
                        pytest.fail("must not send even anonymous GET by default"))
    data = baseline.observe(root, "9002")
    assert data["schema"] == baseline.SCHEMA
    assert "API-HEALTH-ANONYMOUS" not in data["checks"]
    assert data["loopback_http_attempts"] == 0
    assert data["overall"] == "INCOMPLETE"


def test_opt_in_unverified_listener_observes_unattributed_health(monkeypatch, root):
    calls = []
    monkeypatch.setattr(baseline, "attest_api_listener",
                        lambda *_: calls.append("listener") or None)
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda _: calls.append("health") or _health("PASS"))
    data = baseline.observe(root, "9002", independent_anonymous_health=True)
    assert calls == ["listener", "health"]
    assert data["schema"] == baseline.SCHEMA_INDEPENDENT
    assert data["checks"]["API-LISTENER"]["status"] == "SKIP"
    assert data["checks"]["API-HEALTH"] == {
        "status": "SKIP", "reason": "listener_identity_unverified"}
    assert data["checks"]["API-HEALTH-ANONYMOUS"] == {
        "status": "PASS", "reason": "anonymous_healthz_http_200_unattributed"}
    assert data["checks"]["WORKER-IDENTITIES"]["status"] == "PASS"
    assert data["overall"] == "INCOMPLETE"
    assert data["loopback_http_attempts"] == 1
    assert data["credentials_sent"] is False
    assert data["external_network_requests"] == 0
    assert data["mutations"] == 0


def test_attested_case_reuses_single_anonymous_probe(monkeypatch, root):
    proof = ListenerProof(1234, "12345", 9002, "123456")
    calls = []
    monkeypatch.setattr(baseline, "attest_api_listener",
                        lambda *_: calls.append("listener") or proof)
    monkeypatch.setattr(baseline, "probe_api_health",
                        lambda _: calls.append("health") or _health("PASS"))
    data = baseline.observe(root, "9002", independent_anonymous_health=True)
    assert calls == ["listener", "health", "listener"]
    assert all(x["status"] == "PASS" for x in data["checks"].values())
    assert data["overall"] == "PASS"
    assert data["loopback_http_attempts"] == 1


def test_listener_change_after_get_keeps_anonymous_only(monkeypatch, root):
    proofs = iter((
        ListenerProof(1234, "12345", 9002, "123456"),
        ListenerProof(1235, "12346", 9002, "123456"),
    ))
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_: next(proofs))
    monkeypatch.setattr(baseline, "probe_api_health", lambda _: _health("PASS"))
    data = baseline.observe(root, "9002", independent_anonymous_health=True)
    assert data["checks"]["API-LISTENER"]["status"] == "SKIP"
    assert data["checks"]["API-HEALTH"]["status"] == "SKIP"
    assert data["checks"]["API-HEALTH-ANONYMOUS"]["status"] == "PASS"
    assert data["overall"] == "INCOMPLETE"


def test_no_network_overrides_explicit_health_opt_in(monkeypatch, root):
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_: None)
    monkeypatch.setattr(baseline, "probe_api_health", lambda *_:
                        pytest.fail("no-network must override health opt-in"))
    data = baseline.observe(root, "9002", no_network=True,
                            independent_anonymous_health=True)
    assert data["checks"]["API-HEALTH-ANONYMOUS"]["reason"] == "network_disabled"
    assert data["loopback_http_attempts"] == 0
    assert data["overall"] == "INCOMPLETE"


def test_invalid_port_never_calls_anonymous_probe(monkeypatch, root):
    monkeypatch.setattr(baseline, "probe_api_health", lambda *_:
                        pytest.fail("untrusted input must never contact localhost"))
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_:
                        pytest.fail("untrusted port must not reach attestation"))
    data = baseline.observe(root, "9002;bad", independent_anonymous_health=True)
    assert data["overall"] == "INCOMPLETE"
    assert data["loopback_http_attempts"] == 0


def test_anonymous_health_exception_redacted_and_unverified(monkeypatch, root):
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_: None)
    monkeypatch.setattr(baseline, "probe_api_health", lambda *_:
                        (_ for _ in ()).throw(OSError("secret host path token")))
    data = baseline.observe(root, "9002", independent_anonymous_health=True)
    assert data["checks"]["API-HEALTH-ANONYMOUS"]["status"] == "SKIP"
    assert data["overall"] == "INCOMPLETE"
    assert "secret" not in json.dumps(data)
    assert data["loopback_http_attempts"] == 1


def test_unattributed_health_failure_never_claimed_api_healthy(monkeypatch, root):
    monkeypatch.setattr(baseline, "attest_api_listener", lambda *_: None)
    monkeypatch.setattr(baseline, "probe_api_health", lambda _: _health("FAIL"))
    data = baseline.observe(root, "9002", independent_anonymous_health=True)
    assert data["checks"]["API-HEALTH"]["status"] == "SKIP"
    assert data["checks"]["API-HEALTH-ANONYMOUS"]["status"] == "FAIL"
    assert data["overall"] == "INCOMPLETE"
