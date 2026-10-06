import json

import pytest

from sra_api.services.requirement_product_service import (
    ProductTaskIdentity,
    RequirementProductService,
    neutral_run_status,
)


def _task(**overrides):
    value = {
        "task_id": "task-1",
        "schedule_id": "sch-1",
        "source_id": "src-1",
        "execution_kind": "recurring",
        "product_state": "active",
        "revision": 7,
        "created_by": "alice",
        "created_at": "2026-10-06T12:00:00+00:00",
        "updated_by": "bob",
        "updated_at": "2026-10-06T13:00:00+00:00",
    }
    value.update(overrides)
    return value


def _run(**overrides):
    value = {
        "batch_run_id": "br-1",
        "schedule_id": "sch-1",
        "schedule_version_id": "sv-9",
        "snapshot_id": "snap-5",
        "trigger_type": "manual",
        "trigger_request_id": "private-trigger-identity",
        "scheduled_for": None,
        "state": "completed",
        "selected_count": 1,
        "skipped_count": 0,
        "success_count": 1,
        "failure_count": 0,
        "error_code": None,
        "deadline_elapsed_during_execution": False,
        "created_at": "2026-10-06T12:01:00+00:00",
        "completed_at": "2026-10-06T12:02:00+00:00",
        "phase1a_output_root_fingerprint": "a" * 64,
        "phase1a_batch_id": "requirement-e2e:must-not-leak",
        "service_key": "sk-secret",
        "items": [
            {
                "run_item_id": "ri-1",
                "requirement_id": "req-1",
                "requirement_version_id": "rv-8",
                "requirement_version_number": 8,
                "source_order": 1,
                "selection_status": "selected",
                "selection_reason": "all_active",
                "execution_state": "completed",
                "remote_job_id": "job-backend-private",
                "remote_job_state": "REPORT_JOB_INTERNAL_DONE",
                "error_code": None,
                "artifact_relative_path": "../../private/output.docx",
                "artifact_sha256": "b" * 64,
                "credential": "secret",
            }
        ],
    }
    value.update(overrides)
    return value


def test_identity_is_loaded_only_from_product_task_authority():
    row = _task(
        execution_kind="once",
        product_state="active",
        revision=11,
        unrelated_schedule_state="disabled",
        source_from_request="src-wrong",
    )

    identity = ProductTaskIdentity.from_product_task_row(row)

    assert identity == ProductTaskIdentity(
        task_id="task-1",
        schedule_id="sch-1",
        source_id="src-1",
        execution_kind="once",
        product_state="active",
        revision=11,
    )


def test_present_task_uses_product_identity_and_relative_safe_links():
    service = RequirementProductService()
    task = service.present_task(
        product_task=_task(),
        schedule={
            "schedule_id": "sch-1",
            "name": "Daily Requirement",
            "enabled": True,
            "active_version_id": "sv-9",
            "next_run_at": "2026-10-07T00:00:00+00:00",
            "password": "must-not-leak",
            "model": "requirement-e2e:must-not-leak",
        },
    )

    assert task["task_id"] == "task-1"
    assert task["source_id"] == "src-1"
    assert task["schedule_id"] == "sch-1"
    assert task["execution_kind"] == "recurring"
    assert task["product_state"] == "active"
    assert task["revision"] == 7
    assert task["links"]["self"] == "/v1/requirement-tasks/task-1"
    assert task["links"]["runs"] == "/v1/requirement-tasks/task-1/runs"

    rendered = json.dumps(task, default=str)
    assert "password" not in rendered
    assert "requirement-e2e:" not in rendered


def test_present_task_rejects_cross_schedule_identity():
    with pytest.raises(ValueError, match="requirement_product_task_identity_conflict"):
        RequirementProductService().present_task(
            product_task=_task(),
            schedule={"schedule_id": "sch-other"},
        )


@pytest.mark.parametrize(
    ("state", "items", "expected"),
    [
        ("handoff_pending", [], "queued"),
        ("running", [], "running"),
        ("completed", [], "completed"),
        ("completed_with_failures", [{"execution_state": "failed"}], "completed_with_errors"),
        (
            "completed_with_failures",
            [{"execution_state": "recovery_required"}],
            "recovery_required",
        ),
        ("blocked_no_snapshot", [], "failed"),
    ],
)
def test_status_mapping_is_product_neutral(state, items, expected):
    assert neutral_run_status({"state": state, "items": items}) == expected


def test_status_mapping_rejects_unknown_backend_state():
    with pytest.raises(ValueError, match="requirement_run_state_invalid"):
        neutral_run_status({"state": "REPORT_JOB_NATIVE_SUPER_STATE"})


def test_present_run_exposes_immutable_binding_but_not_backend_native_state_or_paths():
    view = RequirementProductService().present_run(
        product_task=_task(),
        run=_run(),
    )

    assert view["run_id"] == "br-1"
    assert view["task_id"] == "task-1"
    assert view["status"] == "completed"
    assert view["binding"] == {
        "schedule_id": "sch-1",
        "schedule_version_id": "sv-9",
        "snapshot_id": "snap-5",
    }
    assert view["items"][0]["requirement_version_id"] == "rv-8"
    assert view["items"][0]["requirement_version_number"] == 8
    assert view["items"][0]["status"] == "completed"
    assert view["items"][0]["artifact"] == {
        "available": True,
        "sha256": "b" * 64,
    }

    rendered = json.dumps(view, default=str)
    for forbidden in (
        "REPORT_JOB_INTERNAL_DONE",
        "job-backend-private",
        "../../private/output.docx",
        "phase1a_output_root_fingerprint",
        "requirement-e2e:",
        "sk-secret",
        "credential",
        "private-trigger-identity",
    ):
        assert forbidden not in rendered
    assert "/v1/requirement-runs/br-1" in rendered


def test_present_run_rejects_cross_task_schedule_identity():
    with pytest.raises(ValueError, match="requirement_run_identity_conflict"):
        RequirementProductService().present_run(
            product_task=_task(),
            run=_run(schedule_id="sch-other"),
        )


def test_present_identity_rejects_disabled_one_time_task():
    with pytest.raises(ValueError, match="requirement_product_task_identity_invalid"):
        RequirementProductService().task_identity(
            _task(execution_kind="once", product_state="disabled")
        )


def test_present_task_hides_provisioning_identity():
    with pytest.raises(KeyError, match="requirement_task_not_found"):
        RequirementProductService().present_task(
            product_task=_task(product_state="provisioning"),
            schedule={"schedule_id": "sch-1"},
        )


def test_present_run_hides_provisioning_owner():
    with pytest.raises(KeyError, match="requirement_task_not_found"):
        RequirementProductService().present_run(
            product_task=_task(product_state="provisioning"),
            run=_run(),
        )


def test_present_links_encode_internal_ids_instead_of_creating_path_segments():
    view = RequirementProductService().present_run(
        product_task=_task(task_id="task/one"),
        run=_run(batch_run_id="br/one"),
    )

    assert view["links"]["self"] == "/v1/requirement-runs/br%2Fone"
    assert view["links"]["items"] == "/v1/requirement-runs/br%2Fone/items"


def test_status_mapping_rejects_failure_summary_without_recovery_evidence():
    with pytest.raises(ValueError, match="requirement_run_status_evidence_missing"):
        neutral_run_status({"state": "completed_with_failures"})


def test_status_mapping_rejects_malformed_failure_item_evidence():
    with pytest.raises(ValueError, match="requirement_run_status_evidence_missing"):
        neutral_run_status(
            {"state": "completed_with_failures", "items": [{"not_execution_state": "failed"}]}
        )
