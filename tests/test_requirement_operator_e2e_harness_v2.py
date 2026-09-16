from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from operator_e2e.requirement_e2e_evidence import RemoteDeploymentEvidenceProvider
from operator_e2e.requirement_e2e_support import (
    CANONICAL_SOURCE_SHA256, E2EConfig, HarnessFailure, validate_downloaded_artifact,
)
from operator_e2e.test_requirement_schedule_e2e import DEFAULT_EXCEL, Harness, parse_args


def _docx() -> bytes:
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
    return value.getvalue()


def test_cli_defaults_to_local_canonical_fixture_and_allows_overrides(tmp_path):
    args = parse_args([])
    assert args.mode == "local" and args.excel == DEFAULT_EXCEL
    custom = tmp_path / "custom.xlsx"
    args = parse_args(["--mode", "remote", "--excel", str(custom)])
    assert args.mode == "remote" and args.excel == custom
    assert hashlib.sha256(DEFAULT_EXCEL.read_bytes()).hexdigest() == CANONICAL_SOURCE_SHA256


def test_remote_configuration_does_not_require_linux_artifact_root():
    config = E2EConfig.from_environment({
        "SRA_E2E_MODEL": "model", "SRA_E2E_EDITOR_TOKEN": "token",
        "SRA_E2E_EXPECTED_RUNTIME_SHA": "a" * 40,
    }, "remote")
    assert config.mode == "remote" and config.artifact_root is None


@pytest.mark.parametrize("role", ["schedule", "handoff"])
def test_remote_worker_identity_is_mandatory(role):
    evidence = {
        "schema_version": "requirement_e2e_runtime_evidence_v1",
        "deployment_source": {"git_sha": "a" * 40, "clean": True, "identity_verified": True},
        "artifact_root_fingerprint": "b" * 64,
        "workers": {name: {"alive": True, "identity_verified": name != role}
                    for name in ("schedule", "handoff")},
    }
    provider = RemoteDeploymentEvidenceProvider(SimpleNamespace(get=lambda *_args, **_kwargs: evidence))
    with pytest.raises(HarnessFailure, match="remote_worker_identity_failed"):
        provider.preflight()


def test_downloaded_docx_is_independently_checked_and_copied(tmp_path):
    data = _docx(); digest = hashlib.sha256(data).hexdigest(); target = tmp_path / "artifact.docx"
    result = validate_downloaded_artifact(data, "report.docx", digest, target)
    assert result["actual_sha256"] == digest and target.read_bytes() == data
    with pytest.raises(HarnessFailure, match="artifact_invalid"):
        validate_downloaded_artifact(b"not zip", "report.docx", digest, tmp_path / "bad.docx")
    with pytest.raises(HarnessFailure, match="artifact_sha256_mismatch"):
        validate_downloaded_artifact(data, "report.docx", "0" * 64, tmp_path / "wrong.docx")


def test_local_and_remote_share_one_golden_path_harness():
    source = Path("operator_e2e/test_requirement_schedule_e2e.py").read_text(encoding="utf-8")
    assert "class LocalHarness" not in source and "class RemoteHarness" not in source
    assert source.count("class Harness:") == 1


def test_runtime_evidence_contract_contains_only_bounded_fields(tmp_path, monkeypatch):
    from sra_api.services import requirement_e2e_runtime_evidence as runtime
    monkeypatch.setattr(runtime, "verify_worker_identity", lambda *_: {"pid": 123, "cmdline": "secret"})
    monkeypatch.setattr(runtime, "_git", lambda *_: {
        "identity_kind": "git_worktree", "git_sha": "a" * 40, "clean": True,
        "identity_verified": True,
    })
    evidence = runtime.collect_runtime_evidence(tmp_path, tmp_path / "artifacts")
    encoded = str(evidence).lower()
    assert evidence["workers"]["schedule"] == {"alive": True, "identity_verified": True}
    assert all(word not in encoded for word in ("cmdline", "cwd", "password", "token", "artifact_root_path"))


def test_runtime_evidence_endpoint_requires_auth_and_superuser(monkeypatch):
    from api.routers.editor_dependencies import current_user, require_superuser
    from api.services.auth_store import AuthUser, ROLE_DATA_READER, ROLE_SUPERUSER
    from sra_api.routers import operator_e2e

    app = FastAPI(); app.include_router(operator_e2e.router); client = TestClient(app)
    assert client.get("/v1/operator-e2e/runtime-evidence").status_code == 401
    app.dependency_overrides[current_user] = lambda: AuthUser("reader", ROLE_DATA_READER, "active")
    assert client.get("/v1/operator-e2e/runtime-evidence").status_code == 403
    app.dependency_overrides[require_superuser] = lambda: AuthUser("root", ROLE_SUPERUSER, "active")
    expected = {"schema_version": "requirement_e2e_runtime_evidence_v1", "workers": {},
                "deployment_source": {}, "artifact_root_fingerprint": "a" * 64}
    monkeypatch.setattr(operator_e2e, "configured_runtime_evidence", lambda *_: expected)
    response = client.get("/v1/operator-e2e/runtime-evidence")
    assert response.status_code == 200 and response.json() == expected
    assert client.post("/v1/operator-e2e/runtime-evidence").status_code == 405
