from __future__ import annotations

import hashlib
import io
import json
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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
    assert args.provenance.name == "REQUIREMENT_E2E_PROVENANCE.json"
    assert hashlib.sha256(DEFAULT_EXCEL.read_bytes()).hexdigest() == CANONICAL_SOURCE_SHA256


def test_remote_configuration_does_not_require_linux_artifact_root():
    config = E2EConfig.from_environment({
        "SRA_E2E_MODEL": "model", "SRA_E2E_EDITOR_TOKEN": "token",
    }, "remote")
    assert config.mode == "remote" and config.artifact_root is None
    assert config.expected_runtime_sha is None


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



@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ITIMER_REAL only on Linux")
def test_remote_preflight_absolute_client_deadline_interrupts_blocked_read(monkeypatch):
    """The Linux preflight wait ends even if no read timeout fires."""
    from operator_e2e import requirement_e2e_evidence as evidence

    class HungApi:
        def get(self, *_args, **_kwargs):
            time.sleep(1)
            raise AssertionError("client wait was not interrupted")

    monkeypatch.setattr(evidence, "E2E_PREFLIGHT_TIMEOUT_SECONDS", 0.08)
    previous = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    with pytest.raises(HarnessFailure, match="remote_preflight_client_deadline_exceeded") as failure:
        RemoteDeploymentEvidenceProvider(HungApi()).preflight()
    assert failure.value.stage == "RUNTIME_WORKERS"
    assert time.monotonic() - started < 0.8
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ITIMER_REAL only on Linux")
def test_remote_preflight_preserves_alarm_and_rejects_existing_owner(monkeypatch):
    from operator_e2e import requirement_e2e_evidence as evidence

    class Api:
        def get(self, *_args, **_kwargs):
            raise AssertionError("must never send GET during timer conflict")

    previous = signal.getsignal(signal.SIGALRM)
    def other_alarm(*_args):
        return None

    signal.signal(signal.SIGALRM, other_alarm)
    try:
        with pytest.raises(HarnessFailure, match="remote_preflight_deadline_conflict"):
            RemoteDeploymentEvidenceProvider(Api()).preflight()
    finally:
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ITIMER_REAL only on Linux")
def test_remote_preflight_fails_closed_off_main_thread():
    class Api:
        def get(self, *_args, **_kwargs):
            raise AssertionError("thread without safe deadline must not send credentials")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(RemoteDeploymentEvidenceProvider(Api()).preflight)
        with pytest.raises(HarnessFailure, match="remote_preflight_deadline_unavailable"):
            future.result()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ITIMER_REAL only on Linux")
def test_remote_preflight_linux_deadline_works_with_successful_evidence(monkeypatch):
    from operator_e2e import requirement_e2e_evidence as evidence
    monkeypatch.setattr(evidence, "E2E_PREFLIGHT_TIMEOUT_SECONDS", 2)

    class Api:
        def get(self, path, **kwargs):
            assert path == "/v1/operator-e2e/runtime-evidence?verification=release"
            assert kwargs["timeout"] == 2
            return {
                "schema_version": "requirement_e2e_runtime_evidence_v1",
                "workers": {name: {"alive": True, "identity_verified": True}
                            for name in ("schedule", "handoff")},
                "artifact_root_fingerprint": "a" * 64,
            }

    old_handler = signal.getsignal(signal.SIGALRM)
    result = RemoteDeploymentEvidenceProvider(Api()).preflight()
    assert result["schema_version"] == "requirement_e2e_runtime_evidence_v1"
    assert signal.getsignal(signal.SIGALRM) == old_handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


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
    data = b"package"
    target = tmp_path / "sra_api" / "main.py"; target.parent.mkdir(); target.write_bytes(data)
    (tmp_path / "REQUIREMENT_E2E_PROVENANCE.json").write_text(json.dumps({
        "schema_version": 2, "repository": "hun186/poc-agent",
        "reviewed_runtime_sha": "a" * 40,
        "runtime_files": [{"path": "sra_api/main.py", "sha256": hashlib.sha256(data).hexdigest()}],
    }))
    monkeypatch.setattr(runtime, "verify_worker_identity", lambda *_: {"pid": 123, "cmdline": "secret"})
    monkeypatch.setattr(runtime, "_active_project_modules", lambda *_: [])
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


class _ArtifactStore:
    def __init__(self, evidence):
        self.evidence = evidence

    def get_operator_artifact_evidence(self, *, batch_run_id, run_item_id):
        if self.evidence is None:
            raise KeyError("run_item_not_found")
        assert batch_run_id == "batch-1" and run_item_id == "item-1"
        return self.evidence


def _artifact_app(monkeypatch, root: Path, evidence: dict | None):
    from api.routers.editor_dependencies import current_user, require_superuser
    from api.services.auth_store import AuthUser, ROLE_DATA_READER, ROLE_SUPERUSER
    from sra_api.routers import operator_e2e
    from sra_api.routers.requirement_schedules import schedule_service

    app = FastAPI(); app.include_router(operator_e2e.router)
    app.state.requirement_schedule_service = SimpleNamespace(store=_ArtifactStore(evidence))
    monkeypatch.setenv("REQUIREMENT_HANDOFF_OUTPUT_ROOT", str(root))
    return app, TestClient(app), current_user, require_superuser, AuthUser, ROLE_DATA_READER, ROLE_SUPERUSER


def _durable_evidence(root: Path, data: bytes, **overrides):
    from operator_e2e.requirement_e2e_support import output_root_fingerprint
    result = {
        "batch_run_id": "batch-1", "run_item_id": "item-1",
        "selection_status": "selected", "remote_job_id": "job-1",
        "artifact_relative_path": "published/exact.docx",
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "phase1a_output_root_fingerprint": output_root_fingerprint(root),
    }
    result.update(overrides)
    return result


def test_artifact_endpoint_requires_superuser_and_is_get_only(tmp_path, monkeypatch):
    evidence = _durable_evidence(tmp_path, _docx())
    app, client, current_user, require_superuser, AuthUser, reader, superuser = _artifact_app(
        monkeypatch, tmp_path, evidence,
    )
    path = "/v1/operator-e2e/batches/batch-1/items/item-1/artifact"
    assert client.get(path).status_code == 401
    app.dependency_overrides[current_user] = lambda: AuthUser("reader", reader, "active")
    assert client.get(path).status_code == 403
    app.dependency_overrides[require_superuser] = lambda: AuthUser("root", superuser, "active")
    assert client.post(path).status_code == 405


def test_artifact_endpoint_returns_exact_handoff_published_bytes(tmp_path, monkeypatch):
    data = _docx(); target = tmp_path / "published" / "exact.docx"
    target.parent.mkdir(); target.write_bytes(data)
    evidence = _durable_evidence(tmp_path, data)
    app, client, _current, require_superuser, AuthUser, _reader, superuser = _artifact_app(
        monkeypatch, tmp_path, evidence,
    )
    app.dependency_overrides[require_superuser] = lambda: AuthUser("root", superuser, "active")
    response = client.get("/v1/operator-e2e/batches/batch-1/items/item-1/artifact")
    assert response.status_code == 200 and response.content == data
    assert str(tmp_path) not in str(response.headers)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing", "artifact_missing"),
        ("corrupt", "artifact_invalid"),
        ("sha", "artifact_sha256_mismatch"),
        ("fingerprint", "artifact_root_fingerprint_mismatch"),
        ("metadata", "artifact_metadata_missing"),
        ("wrong_batch", "artifact_missing"),
    ],
)
def test_artifact_endpoint_fails_closed_for_invalid_published_evidence(tmp_path, monkeypatch, mutation, code):
    data = _docx(); target = tmp_path / "published" / "exact.docx"; target.parent.mkdir()
    evidence = _durable_evidence(tmp_path, data)
    if mutation != "missing": target.write_bytes(b"not zip" if mutation == "corrupt" else data)
    if mutation == "sha": evidence["artifact_sha256"] = "0" * 64
    if mutation == "fingerprint": evidence["phase1a_output_root_fingerprint"] = "0" * 64
    if mutation == "metadata": evidence["artifact_relative_path"] = None
    if mutation == "wrong_batch": evidence = None
    app, client, _current, require_superuser, AuthUser, _reader, superuser = _artifact_app(
        monkeypatch, tmp_path, evidence,
    )
    app.dependency_overrides[require_superuser] = lambda: AuthUser("root", superuser, "active")
    response = client.get("/v1/operator-e2e/batches/batch-1/items/item-1/artifact")
    assert response.status_code >= 400 and response.json()["detail"]["code"] == code


def test_artifact_endpoint_rejects_symlink(tmp_path, monkeypatch):
    data = _docx(); outside = tmp_path / "outside.docx"; outside.write_bytes(data)
    target = tmp_path / "published" / "exact.docx"; target.parent.mkdir(); target.symlink_to(outside)
    evidence = _durable_evidence(tmp_path, data)
    app, client, _current, require_superuser, AuthUser, _reader, superuser = _artifact_app(
        monkeypatch, tmp_path, evidence,
    )
    app.dependency_overrides[require_superuser] = lambda: AuthUser("root", superuser, "active")
    response = client.get("/v1/operator-e2e/batches/batch-1/items/item-1/artifact")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "artifact_missing"


def test_remote_provider_never_uses_report_job_word_and_missing_published_artifact_fails(tmp_path):
    # Reproduce the former false PASS: an upstream Report Job DOCX exists while
    # the separately published Handoff artifact is absent.
    upstream_report_job_docx = tmp_path / "report-job-source.docx"
    upstream_report_job_docx.write_bytes(_docx())

    class Api:
        def request_raw(self, method, path, **_kwargs):
            assert method == "GET"
            assert path == "/v1/operator-e2e/batches/batch-1/items/item-1/artifact"
            raise HarnessFailure("artifact_missing")

    provider = RemoteDeploymentEvidenceProvider(Api())
    item = {"run_item_id": "item-1", "batch_run_id": "batch-1", "remote_job_id": "job-1",
            "artifact_sha256": hashlib.sha256(_docx()).hexdigest()}
    with pytest.raises(HarnessFailure, match="artifact_missing"):
        provider.verify_artifact(item, "a" * 64, tmp_path / "copy.docx")
    assert upstream_report_job_docx.is_file()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("authentication_failed", "remote_evidence_authentication_failed"),
        ("authorization_failed", "remote_evidence_authorization_failed"),
        ("release_provenance_invalid", "release_provenance_invalid"),
    ],
)
def test_remote_runtime_evidence_preserves_auth_failure_category(source, expected):
    class Api:
        def get(self, *_args, **_kwargs):
            raise HarnessFailure(source)

    with pytest.raises(HarnessFailure, match=expected):
        RemoteDeploymentEvidenceProvider(Api()).preflight()


def test_remote_provider_independently_validates_exact_downloaded_bytes(tmp_path):
    data = _docx(); digest = hashlib.sha256(data).hexdigest()
    response = SimpleNamespace(content=data, headers={"content-disposition": 'attachment; filename="item-1.docx"'})

    class Api:
        def request_raw(self, method, path, **_kwargs):
            assert (method, path) == (
                "GET", "/v1/operator-e2e/batches/batch-1/items/item-1/artifact",
            )
            return response

    target = tmp_path / "artifacts" / "item-1.docx"
    result = RemoteDeploymentEvidenceProvider(Api()).verify_artifact(
        {"batch_run_id": "batch-1", "run_item_id": "item-1", "artifact_sha256": digest},
        "a" * 64,
        target,
    )
    assert target.read_bytes() == data and result["actual_sha256"] == digest
