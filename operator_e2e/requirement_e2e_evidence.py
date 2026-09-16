"""Mode-specific evidence acquisition for the shared Requirement E2E flow."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import requests

from operator_e2e.requirement_e2e_support import (
    HarnessFailure, output_root_fingerprint, validate_artifact, validate_downloaded_artifact,
    verify_worker_identity,
)


class DeploymentEvidenceProvider(Protocol):
    def preflight(self) -> dict[str, Any]: ...
    def verify_artifact(self, item: dict[str, Any], persisted_root: str, copy_to: Path) -> dict[str, Any]: ...


class LocalDeploymentEvidenceProvider:
    def __init__(self, project_root: Path, artifact_root: Path):
        self.project_root, self.artifact_root = project_root, artifact_root

    def preflight(self) -> dict[str, Any]:
        workers = {
            role: {**verify_worker_identity(self.project_root / f".run_sra_api_{role}.identity", role, self.project_root),
                   "identity_verified": True}
            for role in ("schedule", "handoff")
        }
        return {"schema_version": "requirement_e2e_runtime_evidence_v1", "workers": workers,
                "artifact_root_fingerprint": output_root_fingerprint(self.artifact_root)}

    def verify_artifact(self, item, persisted_root, copy_to):
        return validate_artifact(self.artifact_root, persisted_root, item.get("artifact_relative_path", ""),
                                 item.get("artifact_sha256", ""), copy_to)


class RemoteDeploymentEvidenceProvider:
    def __init__(self, api): self.api = api

    def preflight(self) -> dict[str, Any]:
        try: evidence = self.api.get("/v1/operator-e2e/runtime-evidence", timeout=30)
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
            response = self.api.request_raw("GET", f"/v1/report/jobs/{item['remote_job_id']}/word", timeout=60)
        except (requests.Timeout, requests.ConnectionError, HarnessFailure) as exc:
            raise HarnessFailure("artifact_download_failed", stage="ARTIFACT_RECONCILIATION") from exc
        disposition = response.headers.get("content-disposition", "")
        filename = f"{item['run_item_id']}.docx"
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip().strip('"')
        return validate_downloaded_artifact(response.content, filename, item.get("artifact_sha256", ""), copy_to)
