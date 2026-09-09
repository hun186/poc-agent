from datetime import datetime, timezone

import pytest

from requirement_scheduler.config import RequirementHandoffConfig
from requirement_scheduler.execution import (
    ExecutionFailure,
    ExecutionHandle,
    ExecutionState,
    FailureCategory,
    build_execution_manifest,
    submission_id,
)
from requirement_scheduler.legacy_report_job_gateway import (
    LegacyReportJobGateway,
    translate_native_state,
)


class Response:
    def __init__(self, status_code=201, body=None):
        self.status_code = status_code
        self._body = {"job_id": "job-1"} if body is None else body

    def json(self):
        return self._body


class Session:
    def __init__(self, response=None):
        self.response = response or Response()
        self.call = None

    def request(self, *args, **kwargs):
        self.call = (args, kwargs)
        return self.response


def gateway(tmp_path, response=None):
    config = RequirementHandoffConfig(
        "https://example.test", "scheduler", lambda _: "runtime-only", tmp_path
    )
    session = Session(response)
    return LegacyReportJobGateway(config, session=session), session


def manifest():
    source = {
        "schedule_id": "s",
        "schedule_version_id": "sv",
        "batch_run_id": "b",
        "run_item_id": "i",
        "snapshot_id": "sn",
        "requirement_id": "r",
        "requirement_version_id": "rv",
        "requirement_version_number": 1,
        "resolved_prompt": "prompt",
        "resolved_model": "model",
        "deadline_at": datetime(2026, 9, 8, tzinfo=timezone.utc),
    }
    return build_execution_manifest(source)


@pytest.mark.parametrize(
    ("native", "neutral"),
    [
        ("queued", ExecutionState.PENDING),
        ("running", ExecutionState.RUNNING),
        ("completed", ExecutionState.COMPLETED),
        ("failed", ExecutionState.FAILED),
        ("interrupted", ExecutionState.RECOVERY_REQUIRED),
    ],
)
def test_native_states_are_translated_only_at_gateway(native, neutral):
    assert translate_native_state(native).state == neutral


def test_unknown_native_state_fails_closed():
    with pytest.raises(ExecutionFailure) as caught:
        translate_native_state("framework-private")
    assert caught.value.category == FailureCategory.RECONCILIATION_UNKNOWN
    assert caught.value.safe_message == "remote_state_unknown"


def test_submit_accepts_report_job_202_and_preserves_payload_identity(tmp_path):
    report_gateway, session = gateway(
        tmp_path,
        Response(
            202,
            {
                "job_id": "job-1",
                "status": "queued",
                "status_url": "/v1/report/jobs/job-1",
                "download_url": "/v1/report/jobs/job-1/word",
            },
        ),
    )
    execution_manifest = manifest()
    sid = submission_id("i")

    assert report_gateway.submit(execution_manifest, idempotency_key=sid).remote_job_id == "job-1"
    _, kwargs = session.call
    assert kwargs["headers"]["Idempotency-Key"] == sid
    assert kwargs["json"] == {
        "prompt": "prompt",
        "filename": "requirement-r-v1.docx",
        "session_id": "requirement-handoff:" + sid,
        "model": "model",
        "options": {},
        "metadata": {"submission_id": sid, "workflow_id": "report_v1"},
    }
    assert "owner" not in kwargs["json"] and "runtime-only" not in str(kwargs["json"])


@pytest.mark.parametrize("job_id", [None, "", 7, "x" * 65])
def test_submit_202_still_validates_remote_job_id(tmp_path, job_id):
    report_gateway, _ = gateway(tmp_path, Response(202, {"job_id": job_id}))
    with pytest.raises(ExecutionFailure) as caught:
        report_gateway.submit(manifest(), idempotency_key=submission_id("i"))
    assert caught.value.category == FailureCategory.INTERNAL_CONTRACT_VIOLATION
    assert caught.value.safe_message == "remote_response_invalid"


@pytest.mark.parametrize(
    ("native", "neutral"),
    [
        ("queued", ExecutionState.PENDING),
        ("running", ExecutionState.RUNNING),
        ("completed", ExecutionState.COMPLETED),
        ("failed", ExecutionState.FAILED),
        ("interrupted", ExecutionState.RECOVERY_REQUIRED),
    ],
)
def test_inspect_reads_native_report_job_status(tmp_path, native, neutral):
    report_gateway, _ = gateway(tmp_path, Response(200, {"status": native}))
    assert report_gateway.inspect(ExecutionHandle("submission", "job-1")).state == neutral


@pytest.mark.parametrize("body", [{}, {"status": None}, {"status": 1}])
def test_inspect_missing_or_non_string_status_fails_bounded_contract(tmp_path, body):
    report_gateway, _ = gateway(tmp_path, Response(200, body))
    with pytest.raises(ExecutionFailure) as caught:
        report_gateway.inspect(ExecutionHandle("submission", "job-1"))
    assert caught.value.category == FailureCategory.INTERNAL_CONTRACT_VIOLATION
    assert caught.value.safe_message == "remote_response_invalid"


def test_inspect_unknown_native_status_uses_reconciliation_unknown(tmp_path):
    report_gateway, _ = gateway(tmp_path, Response(200, {"status": "framework-private"}))
    with pytest.raises(ExecutionFailure) as caught:
        report_gateway.inspect(ExecutionHandle("submission", "job-1"))
    assert caught.value.category == FailureCategory.RECONCILIATION_UNKNOWN
    assert caught.value.safe_message == "remote_state_unknown"


@pytest.mark.parametrize(
    ("status_code", "category", "safe_message"),
    [
        (401, FailureCategory.AUTHENTICATION_FAILED, "remote_authentication_failed"),
        (403, FailureCategory.AUTHORIZATION_FAILED, "remote_authorization_failed"),
        (409, FailureCategory.SEMANTIC_CONFLICT, "remote_semantic_conflict"),
    ],
)
def test_submit_auth_and_semantic_conflicts_are_unchanged(
    tmp_path, status_code, category, safe_message
):
    report_gateway, _ = gateway(tmp_path, Response(status_code, {}))
    with pytest.raises(ExecutionFailure) as caught:
        report_gateway.submit(manifest(), idempotency_key=submission_id("i"))
    assert caught.value.category == category
    assert caught.value.safe_message == safe_message
