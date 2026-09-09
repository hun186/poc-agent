from __future__ import annotations
from datetime import datetime, timezone
import time
from typing import Any
import requests

from .config import RequirementHandoffConfig
from .execution import (ExecutionFailure, ExecutionHandle, ExecutionManifest, ExecutionState,
                        ExecutionStatus, FailureCategory)

_TRANSIENT = {429, 502, 503, 504}

def translate_native_state(value: str, observed_at: datetime | None = None) -> ExecutionStatus:
    states = {"queued": ExecutionState.PENDING, "running": ExecutionState.RUNNING,
              "completed": ExecutionState.COMPLETED, "failed": ExecutionState.FAILED,
              "interrupted": ExecutionState.RECOVERY_REQUIRED}
    if value not in states:
        raise ExecutionFailure(FailureCategory.RECONCILIATION_UNKNOWN, "remote_state_unknown")
    failure = None
    if value == "failed": failure = ExecutionFailure(FailureCategory.REMOTE_EXECUTION_FAILED, "remote_execution_failed")
    if value == "interrupted": failure = ExecutionFailure(FailureCategory.RECONCILIATION_UNKNOWN, "remote_execution_interrupted")
    return ExecutionStatus(states[value], observed_at or datetime.now(timezone.utc), failure)

class LegacyReportJobGateway:
    def __init__(self, config: RequirementHandoffConfig, session: Any = None, sleep=time.sleep):
        self.config, self.session, self.sleep = config, session or requests.Session(), sleep

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        credential = self.config.credential_provider(self.config.logical_principal)
        if not isinstance(credential, str) or not credential: raise ExecutionFailure(FailureCategory.AUTHENTICATION_FAILED, "credential_unavailable")
        result = {"Authorization": f"Bearer {credential}", "Accept": "application/json"}
        if idempotency_key: result["Idempotency-Key"] = idempotency_key
        return result

    def _request(self, method: str, path: str, **kwargs):
        last = None
        for attempt in range(self.config.request_retries):
            try:
                response = self.session.request(method, self.config.api_base_url.rstrip("/") + path,
                    timeout=(self.config.connect_timeout, self.config.read_timeout), **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
                if attempt + 1 == self.config.request_retries: raise ExecutionFailure(FailureCategory.TRANSPORT_AMBIGUOUS, "remote_transport_ambiguous", True) from exc
            else:
                if response.status_code == 401: raise ExecutionFailure(FailureCategory.AUTHENTICATION_FAILED, "remote_authentication_failed")
                if response.status_code == 403: raise ExecutionFailure(FailureCategory.AUTHORIZATION_FAILED, "remote_authorization_failed")
                if response.status_code == 409: raise ExecutionFailure(FailureCategory.SEMANTIC_CONFLICT, "remote_semantic_conflict")
                if response.status_code not in _TRANSIENT: return response
                last = response
                if attempt + 1 == self.config.request_retries: raise ExecutionFailure(FailureCategory.REMOTE_UNAVAILABLE, "remote_unavailable", True)
            self.sleep(min(self.config.max_backoff, 2**attempt))
        raise AssertionError(last)

    def submit(self, manifest: ExecutionManifest, *, idempotency_key: str) -> ExecutionHandle:
        if idempotency_key != "rhsub_" + __import__("hashlib").sha256(("requirement-handoff-v1\0" + str(manifest.source_identity["run_item_id"])).encode()).hexdigest()[:48]:
            raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "submission_identity_mismatch")
        payload = {"prompt": manifest.execution_input["resolved_prompt"], "filename": manifest.execution_input["logical_filename"],
                   "session_id": manifest.execution_policy["legacy_session_id"], "model": manifest.execution_input["resolved_model"],
                   "options": {}, "metadata": {"submission_id": idempotency_key, "workflow_id": "report_v1"}}
        response = self._request("POST", "/v1/report/jobs", headers=self._headers(idempotency_key=idempotency_key), json=payload)
        if response.status_code not in {200, 201, 202}: raise ExecutionFailure(FailureCategory.REMOTE_UNAVAILABLE, "remote_response_invalid")
        try: body=response.json(); job_id=body["job_id"]
        except Exception as exc: raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "remote_response_invalid") from exc
        if not isinstance(job_id, str) or not job_id or len(job_id)>64: raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "remote_response_invalid")
        return ExecutionHandle(idempotency_key, job_id)

    def inspect(self, handle: ExecutionHandle) -> ExecutionStatus:
        response=self._request("GET", f"/v1/report/jobs/{handle.remote_job_id}", headers=self._headers())
        if response.status_code != 200: raise ExecutionFailure(FailureCategory.REMOTE_UNAVAILABLE, "remote_response_invalid")
        try: state=response.json()["status"]
        except Exception as exc: raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "remote_response_invalid") from exc
        if not isinstance(state, str): raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "remote_response_invalid")
        return translate_native_state(state)

    def download_artifact(self, handle: ExecutionHandle) -> bytes:
        response=self._request("GET", f"/v1/report/jobs/{handle.remote_job_id}/word", headers=self._headers())
        if response.status_code != 200: raise ExecutionFailure(FailureCategory.REMOTE_UNAVAILABLE, "artifact_download_failed")
        media=response.headers.get("content-type", "").split(";",1)[0].strip().lower()
        if media != "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            raise ExecutionFailure(FailureCategory.ARTIFACT_INVALID, "artifact_media_type_invalid")
        return bytes(response.content)
