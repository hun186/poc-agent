"""Synthetic OFF-1 strict ES projection tests. Never open network sockets."""
from pathlib import Path

import pytest

from tools import sraf_airgap_off1_es_hub as projected
from tools import sraf_airgap_off1b_es_https_mapping as strict


def _raw(**changes):
    raw = {
        "ip_san_policy": "STRICT", "credential_control": "NOT_RUN",
        "identity_warning": False, "https_probe": "PASS",
        "tls_validation": "PASS", "mapping_probe": "PASS",
        "auth": "NOT_VERIFIED",
        "reason": "SECRET_HOST_DATABASE_USERNAME_DO_NOT_LEAK",
        "url": "https://192.168.0.134:9001/secret",
    }
    raw.update(changes)
    return raw


def _run(monkeypatch, raw):
    seen = []
    def fake(cfg, *, no_network, root, verify_credentials, warn_only_ip_san):
        seen.append((no_network, verify_credentials, warn_only_ip_san, root))
        if isinstance(raw, Exception):
            raise raw
        return raw
    monkeypatch.setattr(strict, "_observe", fake)
    got = projected.strict_mapping_observation(
        {"ES_PASSWORD": "SECRET_PASSWORD_DO_NOT_LEAK"}, Path("/trusted/sraf"))
    assert seen == [(False, False, False, Path("/trusted/sraf"))]
    return got


def test_strict_tls_and_mapping_pass_only_partially_without_negative_auth_control(monkeypatch):
    obs = _run(monkeypatch, _raw())
    assert obs == {
        "check": "es_strict_tls_mapping", "status": "SKIP",
        "reason": "es_tls_mapping_observed_auth_not_verified",
        "https_probe": "PASS", "tls_validation": "PASS",
        "mapping_probe": "PASS", "auth": "NOT_VERIFIED",
        "credential_control": "NOT_RUN",
    }


@pytest.mark.parametrize("change,expected", [
    ({"tls_validation": "FAIL", "https_probe": "FAIL"},
     ("FAIL", "es_tls_identity_failed")),
    ({"https_probe": "FAIL"}, ("FAIL", "es_https_identity_failed")),
    ({"auth": "FAIL"}, ("FAIL", "es_auth_rejected")),
    ({"mapping_probe": "FAIL"}, ("FAIL", "es_mapping_failed")),
    ({"mapping_probe": "SKIP"}, ("SKIP", "es_strict_incomplete")),
])
def test_strict_status_classification(monkeypatch, change, expected):
    obs = _run(monkeypatch, _raw(**change))
    assert (obs["status"], obs["reason"]) == expected


@pytest.mark.parametrize("changes", [
    {"ip_san_policy": "WARN_ONLY"},
    {"identity_warning": True},
    {"credential_control": "PASS"},
    {"https_probe": "SECRET_INVALID"},
    {"tls_validation": "SECRET_INVALID"},
    {"mapping_probe": "SECRET_INVALID"},
    {"auth": "SECRET_INVALID"},
])
def test_relaxed_tls_or_unknown_status_fails_closed(monkeypatch, changes):
    obs = _run(monkeypatch, _raw(**changes))
    assert obs["status"] == "SKIP"
    assert obs["reason"] == "es_strict_observation_unavailable"
    assert "SECRET" not in str(obs)


@pytest.mark.parametrize("raw", [None, [], OSError("SECRET_EXCEPTION"), {"auth": "PASS"}])
def test_errors_or_unstructured_responses_are_redacted(monkeypatch, raw):
    obs = _run(monkeypatch, raw)
    assert obs["status"] == "SKIP"
    assert obs["reason"] == "es_strict_observation_unavailable"
    assert "SECRET" not in str(obs)
