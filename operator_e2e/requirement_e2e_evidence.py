"""Mode-specific evidence acquisition for the shared Requirement E2E flow."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol
import signal
import sys
import threading

import requests

from operator_e2e.requirement_e2e_support import (
    HarnessFailure, output_root_fingerprint, validate_artifact, validate_downloaded_artifact,
    verify_worker_identity,
)

# Full E2E preparation is explicitly initiated by the operator, not API
# startup. It probes several LLM models and prepares the isolated ES fixture
# sequentially. A fixed 30s HTTP read timeout is shorter than healthy
# high-load preparations; 10 minutes is a bounded operator-only allowance.
E2E_PREFLIGHT_TIMEOUT_SECONDS = 600


class _PreflightClientDeadlineExpired(BaseException):
    """Deliberately bypass broad network-library Exception/retry handlers."""


@contextmanager
def _preflight_client_deadline(seconds: float) -> Iterator[None]:
    """Bound a Linux operator's *wait* for the GET, not server-side work.

    SIGALRM is process global. Only the Linux main thread may safely own the
    timer; fail closed on any pre-existing handler/timer rather than clobber it.
    Remote operators on other platforms retain Requests' inactivity timeout.
    """
    if not sys.platform.startswith("linux"):
        yield
        return
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        raise HarnessFailure("remote_preflight_deadline_unavailable", stage="RUNTIME_WORKERS")
    previous_handler = signal.getsignal(signal.SIGALRM)
    active_seconds, interval = signal.getitimer(signal.ITIMER_REAL)
    if previous_handler not in (signal.SIG_DFL, signal.SIG_IGN) or active_seconds > 0 or interval > 0:
        raise HarnessFailure("remote_preflight_deadline_conflict", stage="RUNTIME_WORKERS")

    def expire(_signum, _frame):
        raise _PreflightClientDeadlineExpired()

    signal.signal(signal.SIGALRM, expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, previous_handler)


class DeploymentEvidenceProvider(Protocol):
    def preflight(self, verification: str = "release") -> dict[str, Any]: ...
    def verify_artifact(self, item: dict[str, Any], persisted_root: str, copy_to: Path) -> dict[str, Any]: ...


class LocalDeploymentEvidenceProvider:
    def __init__(self, project_root: Path, artifact_root: Path, api):
        self.project_root, self.artifact_root, self.api = project_root, artifact_root, api

    def preflight(self, verification: str = "release") -> dict[str, Any]:
        # Capability authority belongs to the already-running API/ReportJobWorker
        # process. Local artifact access does not make the harness process an
        # acceptable substitute for that runtime evidence.
        return RemoteDeploymentEvidenceProvider(self.api).preflight(verification)

    def verify_artifact(self, item, persisted_root, copy_to):
        return validate_artifact(self.artifact_root, persisted_root, item.get("artifact_relative_path", ""),
                                 item.get("artifact_sha256", ""), copy_to)


class RemoteDeploymentEvidenceProvider:
    def __init__(self, api): self.api = api

    def preflight(self, verification: str = "release") -> dict[str, Any]:
        try:
            with _preflight_client_deadline(E2E_PREFLIGHT_TIMEOUT_SECONDS):
                evidence = self.api.get(
                    f"/v1/operator-e2e/runtime-evidence?verification={verification}",
                    timeout=E2E_PREFLIGHT_TIMEOUT_SECONDS,
                )
        except _PreflightClientDeadlineExpired as exc:
            raise HarnessFailure("remote_preflight_client_deadline_exceeded", stage="RUNTIME_WORKERS") from exc
        except HarnessFailure as exc:
            if exc.category in {"remote_preflight_deadline_conflict", "remote_preflight_deadline_unavailable"}:
                raise
            if exc.category == "authentication_failed":
                raise HarnessFailure("remote_evidence_authentication_failed", stage="RUNTIME_WORKERS") from exc
            if exc.category == "authorization_failed":
                raise HarnessFailure("remote_evidence_authorization_failed", stage="RUNTIME_WORKERS") from exc
            if exc.category in {"active_runtime_source_mismatch", "unexpected_active_runtime_module",
                                "unexpected_runtime_input",
                                "runtime_module_shadowing", "release_provenance_invalid",
                                "release_provenance_missing"}:
                raise HarnessFailure(exc.category, stage="RUNTIME_WORKERS") from exc
            raise HarnessFailure("remote_runtime_evidence_unavailable", stage="RUNTIME_WORKERS") from exc
        except Exception as exc:
            raise HarnessFailure("remote_runtime_evidence_unavailable", stage="RUNTIME_WORKERS") from exc
        if evidence.get("schema_version") != "requirement_e2e_runtime_evidence_v1":
            raise HarnessFailure("remote_runtime_evidence_invalid", stage="RUNTIME_WORKERS")
        workers = evidence.get("workers") or {}
        if any(not workers.get(role, {}).get("alive") or not workers.get(role, {}).get("identity_verified")
               for role in ("schedule", "handoff")):
            raise HarnessFailure("remote_worker_identity_failed", stage="RUNTIME_WORKERS")
        if not evidence.get("artifact_root_fingerprint"):
            raise HarnessFailure("remote_runtime_evidence_invalid", stage="RUNTIME_WORKERS")
        return evidence

    def verify_artifact(self, item, persisted_root, copy_to):
        try:
            response = self.api.request_raw(
                "GET",
                f"/v1/operator-e2e/batches/{item['batch_run_id']}/items/{item['run_item_id']}/artifact",
                timeout=60,
            )
        except HarnessFailure as exc:
            if exc.category in {
                "artifact_missing", "artifact_invalid", "artifact_metadata_missing",
                "artifact_sha256_mismatch", "artifact_root_fingerprint_mismatch",
            }:
                raise
            if exc.category == "authentication_failed":
                raise HarnessFailure("remote_evidence_authentication_failed", stage="ARTIFACT_RECONCILIATION") from exc
            if exc.category == "authorization_failed":
                raise HarnessFailure("remote_evidence_authorization_failed", stage="ARTIFACT_RECONCILIATION") from exc
            raise HarnessFailure("artifact_download_failed", stage="ARTIFACT_RECONCILIATION") from exc
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise HarnessFailure("artifact_download_failed", stage="ARTIFACT_RECONCILIATION") from exc
        disposition = response.headers.get("content-disposition", "")
        filename = f"{item['run_item_id']}.docx"
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip().strip('"')
        return validate_downloaded_artifact(response.content, filename, item.get("artifact_sha256", ""), copy_to)
