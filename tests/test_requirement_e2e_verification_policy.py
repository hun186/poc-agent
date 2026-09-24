from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from operator_e2e.requirement_e2e_evidence import RemoteDeploymentEvidenceProvider
from operator_e2e.requirement_e2e_support import HarnessFailure
from operator_e2e.test_requirement_schedule_e2e import (
    _provenance_source,
    _validate_deployment_source,
    parse_args,
)


def _provenance(root: Path, content: bytes = b"reviewed") -> Path:
    target = root / "sra_api" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    path = root / "REQUIREMENT_E2E_PROVENANCE.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "repository": "hun186/poc-agent",
        "reviewed_runtime_sha": "a" * 40,
        "runtime_files": [{
            "path": "sra_api/main.py",
            "sha256": hashlib.sha256(content).hexdigest(),
        }],
    }), encoding="utf-8")
    return path


def test_verification_defaults_to_strict_release_and_accepts_functional():
    assert parse_args([]).verification == "release"
    assert parse_args(["--verification", "functional"]).verification == "functional"


def test_release_matching_provenance_is_verified(tmp_path):
    source = _provenance_source(tmp_path, _provenance(tmp_path))
    assert source["identity_verified"] is True
    assert source["attestation_status"] == "verified"


def test_release_runtime_drift_still_fails_preflight(tmp_path):
    path = _provenance(tmp_path)
    (tmp_path / "sra_api" / "main.py").write_bytes(b"deployed change")
    with pytest.raises(HarnessFailure, match="operator_runtime_source_mismatch") as failure:
        _provenance_source(tmp_path, path)
    assert failure.value.stage == "CONFIG_PREFLIGHT"


def test_functional_runtime_drift_is_advisory_and_source_is_not_verified(tmp_path):
    path = _provenance(tmp_path)
    (tmp_path / "sra_api" / "main.py").write_bytes(b"deployed change")
    source = _provenance_source(tmp_path, path, verification="functional")
    assert source["identity_verified"] is False
    assert source["attestation_status"] == "mismatch"
    assert source["attestation_category"] == "active_runtime_source_mismatch"
    _validate_deployment_source(
        source, source["provenance_fingerprint"], verification="functional",
    )


def test_functional_malformed_provenance_remains_fatal(tmp_path):
    path = tmp_path / "REQUIREMENT_E2E_PROVENANCE.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(HarnessFailure, match="release_provenance_invalid"):
        _provenance_source(tmp_path, path, verification="functional")


def test_functional_unexpected_runtime_input_remains_fatal(tmp_path, monkeypatch):
    path = _provenance(tmp_path)
    (tmp_path / "sra_api" / "main.py").write_bytes(b"deployed change")
    unexpected = tmp_path / "outside" / "indexes.yaml"
    unexpected.parent.mkdir()
    unexpected.write_text("indexes: {}", encoding="utf-8")
    monkeypatch.setenv("INDEX_CONFIG", str(unexpected))
    with pytest.raises(HarnessFailure, match="unexpected_runtime_input"):
        _provenance_source(tmp_path, path, verification="functional")


def test_functional_remote_evidence_is_authoritative_and_keeps_worker_fence():
    requested = []
    evidence = {
        "schema_version": "requirement_e2e_runtime_evidence_v1",
        "deployment_source": {
            "identity_verified": False,
            "attestation_status": "mismatch",
            "attestation_category": "active_runtime_source_mismatch",
        },
        "workers": {
            "schedule": {"alive": True, "identity_verified": True},
            "handoff": {"alive": False, "identity_verified": False},
        },
        "artifact_root_fingerprint": "b" * 64,
        "acceptance": {"requested_mode": "offline", "classification": "OFFLINE"},
    }

    def get(path, **_kwargs):
        requested.append(path)
        return evidence

    provider = RemoteDeploymentEvidenceProvider(SimpleNamespace(get=get))
    with pytest.raises(HarnessFailure, match="remote_worker_identity_failed"):
        provider.preflight("functional")
    assert requested == ["/v1/operator-e2e/runtime-evidence?verification=functional"]


def test_functional_deployment_source_only_allows_ordinary_byte_drift():
    ordinary = {
        "identity_verified": False,
        "attestation_status": "mismatch",
        "attestation_category": "active_runtime_source_mismatch",
        "provenance_fingerprint": "f" * 64,
    }
    _validate_deployment_source(ordinary, "f" * 64, verification="functional")
    with pytest.raises(HarnessFailure, match="deployment_source_identity_mismatch"):
        _validate_deployment_source(
            {**ordinary, "attestation_category": "runtime_module_shadowing"},
            "f" * 64,
            verification="functional",
        )


def test_deployment_functional_evidence_returns_plan_and_source_mismatch(tmp_path, monkeypatch):
    from sra_api.services import requirement_e2e_runtime_evidence as runtime

    path = _provenance(tmp_path)
    assert path.is_file()
    (tmp_path / "sra_api" / "main.py").write_bytes(b"deployed change")
    monkeypatch.setattr(runtime, "_active_project_modules", lambda *_: [])
    monkeypatch.setattr(runtime, "verify_worker_identity", lambda *_: None)
    monkeypatch.setattr(
        "agent.external_capabilities.frozen_plan",
        lambda resolver: SimpleNamespace(evidence=lambda: {
            "requested_mode": "offline", "classification": "OFFLINE",
        }),
    )
    evidence = runtime.collect_runtime_evidence(
        tmp_path, tmp_path / "artifacts", verification="functional",
    )
    assert evidence["deployment_source"]["identity_verified"] is False
    assert evidence["deployment_source"]["attestation_status"] == "mismatch"
    assert evidence["acceptance"]["classification"] == "OFFLINE"
    assert all(worker["identity_verified"] for worker in evidence["workers"].values())
