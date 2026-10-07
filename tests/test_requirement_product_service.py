import json
from types import SimpleNamespace

import pytest

from data_ingestion.requirements.hashing import canonical_sha256
from data_ingestion.requirements.models import ImportProfileDocument

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


def test_status_mapping_allows_duplicate_valid_failure_states():
    assert neutral_run_status(
        {
            "state": "completed_with_failures",
            "items": [
                {"execution_state": "failed"},
                {"execution_state": "failed"},
            ],
        }
    ) == "completed_with_errors"


def test_status_mapping_rejects_unknown_item_state_in_failure_evidence():
    with pytest.raises(ValueError, match="requirement_run_status_evidence_missing"):
        neutral_run_status(
            {
                "state": "completed_with_failures",
                "items": [{"execution_state": "REPORT_JOB_NATIVE_SUPER_STATE"}],
            }
        )


def test_status_mapping_rejects_empty_failure_evidence():
    with pytest.raises(ValueError, match="requirement_run_status_evidence_missing"):
        neutral_run_status({"state": "completed_with_failures", "items": []})


def test_status_mapping_rejects_failure_summary_without_failure_state():
    with pytest.raises(ValueError, match="requirement_run_status_evidence_missing"):
        neutral_run_status(
            {
                "state": "completed_with_failures",
                "items": [
                    {"execution_state": "completed"},
                    {"execution_state": "not_selected"},
                ],
            }
        )


@pytest.mark.parametrize("state", ["handoff_pending", "running", "completed", "completed_with_failures"])
def test_present_run_requires_snapshot_binding_for_non_blocked_runs(state):
    run = _run(state=state, snapshot_id=None)
    if state == "completed_with_failures":
        run["items"][0]["execution_state"] = "failed"

    with pytest.raises(ValueError, match="requirement_run_snapshot_binding_missing"):
        RequirementProductService().present_run(
            product_task=_task(),
            run=run,
        )


def test_present_run_allows_missing_snapshot_only_for_blocked_no_snapshot():
    view = RequirementProductService().present_run(
        product_task=_task(),
        run=_run(
            state="blocked_no_snapshot",
            snapshot_id=None,
            selected_count=0,
            success_count=0,
            failure_count=0,
            items=[],
        ),
    )

    assert view["status"] == "failed"
    assert view["binding"]["snapshot_id"] is None



def _preview_profile(format="json"):
    document = {
        "format": format,
        "source_timezone": "UTC",
        "source_mode": "authoritative_snapshot",
        "mapping": {
            "external_item_id": {
                "source": "external_item_id",
                "required": True,
                "type": "text",
                "transforms": ["trim"],
            },
            "title": {
                "source": "title",
                "required": True,
                "type": "text",
                "transforms": ["trim"],
            },
            "prompt_content": {
                "source": "prompt_content",
                "required": True,
                "type": "text",
                "transforms": ["trim"],
            },
            "source_updated_at": {
                "source": "source_updated_at",
                "required": True,
                "type": "datetime",
            },
            "source_created_at": {
                "source": "source_created_at",
                "required": True,
                "type": "datetime",
            },
        },
    }
    return ImportProfileDocument.model_validate(document)


class _PreviewOnlyStore:
    def __init__(self, *, format="json", status="approved"):
        self.calls = []
        profile = _preview_profile(format)
        self.version = {
            "profile_id": "prof-1",
            "profile_version_id": "pv-1",
            "version_number": 3,
            "format": profile.format,
            "source_mode": profile.source_mode.value,
            "profile_sha256": canonical_sha256(profile.model_dump(mode="json")),
            "status": status,
            "profile": profile,
        }

    def get_profile_version(self, profile_version_id):
        self.calls.append(("get_profile_version", profile_version_id))
        return dict(self.version)

    def create_source(self, *args, **kwargs):
        raise AssertionError("preview must not create a source")

    def commit_candidate(self, *args, **kwargs):
        raise AssertionError("preview must not create an import run or snapshot")


def _preview_service(*, format="json", status="approved"):
    store = _PreviewOnlyStore(format=format, status=status)
    service = RequirementProductService(
        requirement_import_service=SimpleNamespace(store=store)
    )
    return service, store


def _direct_requirements():
    return [
        {
            "external_item_id": " E-1 ",
            "title": " First ",
            "prompt_content": "alpha",
            "source_updated_at": "2026-10-07T01:00:00Z",
            "source_created_at": "2026-10-01T01:00:00Z",
            "private_extra_column": "must-not-leak",
        },
        {
            "external_item_id": "E-2",
            "title": "Second",
            "prompt_content": "beta",
            "source_updated_at": "not-a-date",
            "source_created_at": "2026-10-01T01:00:00Z",
        },
    ]


def test_product_preview_direct_json_is_side_effect_free_and_normalized():
    service, store = _preview_service()

    preview = service.preview_input(
        profile_version_id="pv-1",
        requirements=_direct_requirements(),
    )

    assert store.calls == [("get_profile_version", "pv-1")]
    assert preview["row_count"] == 2
    assert preview["accepted_count"] == 1
    assert preview["rejected_count"] == 1
    assert preview["has_errors"] is True
    assert preview["normalized_preview"][0]["external_item_id"] == "E-1"
    assert preview["normalized_preview"][0]["title"] == "First"
    assert "private_extra_column" not in json.dumps(preview, default=str)
    assert preview["errors"][0]["source_row_number"] == 2
    assert preview["errors"][0]["code"] == "datetime_parse_error"
    assert preview["warnings"] == []
    assert preview["profile"] == {
        "profile_id": "prof-1",
        "profile_version_id": "pv-1",
        "version_number": 3,
        "profile_sha256": store.version["profile_sha256"],
        "format": "json",
        "source_mode": "authoritative_snapshot",
    }
    assert isinstance(preview["source_sha256"], str)
    assert preview["source_sha256"]


def test_product_preview_uploaded_csv_reuses_requirement_parser():
    service, store = _preview_service(format="csv")
    content = (
        "external_item_id,title,prompt_content,source_updated_at,source_created_at\n"
        "E-9,CSV title,CSV body,2026-10-07T01:00:00Z,2026-10-01T01:00:00Z\n"
    ).encode("utf-8")

    preview = service.preview_input(
        profile_version_id="pv-1",
        upload_bytes=content,
        upload_filename="../unsafe-name.csv",
    )

    assert store.calls == [("get_profile_version", "pv-1")]
    assert preview["accepted_count"] == 1
    assert preview["rejected_count"] == 0
    assert preview["normalized_preview"][0]["external_item_id"] == "E-9"
    assert preview["profile"]["format"] == "csv"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {
            "upload_bytes": b"[]",
            "upload_filename": "requirements.json",
            "requirements": [],
        },
        {"upload_bytes": b"[]"},
        {"upload_filename": "requirements.json"},
    ],
)
def test_product_preview_requires_exactly_one_complete_input_mode(kwargs):
    service, _ = _preview_service()

    with pytest.raises(ValueError, match="requirement_preview_input_invalid"):
        service.preview_input(profile_version_id="pv-1", **kwargs)


def test_product_preview_rejects_unapproved_profile_before_parsing():
    service, store = _preview_service(status="draft")

    with pytest.raises(ValueError, match="requirement_preview_profile_not_approved"):
        service.preview_input(
            profile_version_id="pv-1",
            requirements=_direct_requirements(),
        )

    assert store.calls == [("get_profile_version", "pv-1")]


def test_product_preview_direct_json_must_match_profile_format():
    service, _ = _preview_service(format="csv")

    with pytest.raises(ValueError, match="source_format_invalid"):
        service.preview_input(
            profile_version_id="pv-1",
            requirements=_direct_requirements(),
        )



def test_product_preview_rejects_profile_digest_mismatch():
    service, store = _preview_service()
    store.version["profile_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="requirement_preview_profile_invalid"):
        service.preview_input(
            profile_version_id="pv-1",
            requirements=_direct_requirements(),
        )

    assert store.calls == [("get_profile_version", "pv-1")]
