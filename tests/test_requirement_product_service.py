from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from data_ingestion.requirements.hashing import canonical_sha256
from data_ingestion.requirements.models import ImportProfileDocument
from requirement_scheduler.models import RecurrenceSpec, RunPolicy, ScheduleVersionCreate
from requirement_scheduler.store import ScheduleStore

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


def _valid_direct_requirements():
    return [
        {
            "external_item_id": "E-1",
            "title": "First",
            "prompt_content": "alpha",
            "source_updated_at": "2026-10-07T01:00:00Z",
            "source_created_at": "2026-10-01T01:00:00Z",
        }
    ]


def _once_schedule_config():
    return ScheduleVersionCreate(
        timezone="UTC",
        recurrence=RecurrenceSpec.validate(
            {"kind": "daily", "local_time": "09:00:00"}
        ),
        run_policy=RunPolicy.ALL_ACTIVE,
        model="model-safe",
    )


class _CreateRequirementStore(_PreviewOnlyStore):
    def __init__(self):
        super().__init__(format="json", status="approved")
        self.sources = {}
        self.active_snapshot_id = None
        self.create_source_calls = 0
        self.patch_source_calls = 0

    def get_active_profile_version(self, profile_id):
        assert profile_id == "prof-1"
        return dict(self.version)

    def get_source(self, source_id):
        if source_id not in self.sources:
            raise KeyError("source_not_found")
        return dict(self.sources[source_id])

    def create_source(
        self, name, source_type, source_mode, source_config, import_profile_id, actor,
        *, enabled=False, source_id=None
    ):
        self.create_source_calls += 1
        value = {
            "source_id": source_id,
            "name": name,
            "source_type": source_type,
            "source_mode": source_mode,
            "source_config": dict(source_config),
            "import_profile_id": import_profile_id,
            "enabled": bool(enabled),
        }
        existing = self.sources.get(source_id)
        if existing is not None and existing != value:
            raise AssertionError("source semantic replay drift")
        self.sources[source_id] = value
        return dict(value)

    def patch_source(self, source_id, actor, **changes):
        self.patch_source_calls += 1
        value = dict(self.sources[source_id])
        value.update(changes)
        self.sources[source_id] = value
        return dict(value)

    def get_requirement_set_for_source(self, source_id):
        if self.active_snapshot_id is None:
            raise KeyError("requirement_set_not_found")
        return {
            "requirement_set_id": "set-1",
            "source_id": source_id,
            "active_snapshot_id": self.active_snapshot_id,
        }


class _CreateRequirementImportService:
    def __init__(self):
        self.store = _CreateRequirementStore()
        self.commit_calls = 0
        self.committed = {}
        self.raise_after_commit_once = False
        self._raised_after_commit = False

    def commit(
        self,
        source_id,
        *,
        actor,
        upload_bytes,
        upload_filename,
        import_run_id,
        snapshot_id,
        expected_profile_version_id=None,
        expected_profile_sha256=None,
    ):
        self.commit_calls += 1
        assert expected_profile_version_id == "pv-1"
        assert expected_profile_sha256 == self.store.version["profile_sha256"]
        previous = self.committed.get(import_run_id)
        result = {
            "import_run_id": import_run_id,
            "snapshot_id": snapshot_id,
            "status": "committed",
            "accepted_count": 1,
            "rejected_count": 0,
        }
        if previous is not None and previous != result:
            raise AssertionError("import identity replay drift")
        self.committed[import_run_id] = result
        self.store.active_snapshot_id = snapshot_id
        if self.raise_after_commit_once and not self._raised_after_commit:
            self._raised_after_commit = True
            raise RuntimeError("simulated_import_lost_response")
        return dict(result)


class _CreateScheduleStore:
    def __init__(self):
        self.request = None
        self.reserve_calls = 0
        self.version_calls = 0
        self.finalize_calls = 0
        self.recurring_finalize_calls = 0
        self.recurring_finalize_now = None
        self.schedule_calls = 0
        self.task_calls = 0
        self.raise_after_finalize_commit = False
        self._lost_response_raised = False
        self.schedule = None
        self.task = None
        self.run = None

    canonical_config = staticmethod(ScheduleStore.canonical_config)

    def reserve_product_task_create(self, *, principal_kind, principal_id, idempotency_key, request_sha256, now_utc):
        self.reserve_calls += 1
        if self.request is not None:
            if self.request["request_sha256"] != request_sha256:
                raise ValueError("requirement_idempotency_conflict")
            return dict(self.request)
        self.request = {
            "request_id": "preq-1",
            "principal_kind": principal_kind,
            "principal_id": principal_id,
            "operation": "task_create",
            "idempotency_key": idempotency_key,
            "request_sha256": request_sha256,
            "state": "reserved",
            "created_at": now_utc,
            "task_id": "task-create-1",
            "source_id": "src-create-1",
            "import_run_id": "run-create-1",
            "snapshot_id": "snap-create-1",
            "schedule_id": "sch-create-1",
            "schedule_version_id": "sv-create-1",
            "batch_run_id": None,
            "safe_result": None,
            "error_code": None,
        }
        return dict(self.request)

    def mark_product_request_in_progress(self, request_id, *, now_utc):
        assert request_id == self.request["request_id"]
        self.request["state"] = "in_progress"

    def fail_product_request_terminal(self, request_id, *, error_code, now_utc):
        assert request_id == self.request["request_id"]
        self.request["state"] = "failed_terminal"
        self.request["error_code"] = error_code

    def create_schedule(self, *, name, requirement_set_id, actor, schedule_id):
        self.schedule_calls += 1
        value = {
            "schedule_id": schedule_id,
            "name": name,
            "requirement_set_id": requirement_set_id,
            "enabled": False,
            "active_version_id": None,
            "next_run_at": None,
            "created_by": actor,
            "created_at": "2026-10-07T04:00:00+00:00",
            "updated_by": actor,
            "updated_at": "2026-10-07T04:00:00+00:00",
        }
        if self.schedule is None:
            self.schedule = value
        return dict(self.schedule)

    def create_product_task_provisioning(self, *, task_id, schedule_id, source_id, execution_kind, actor, now_utc):
        self.task_calls += 1
        if self.task is None:
            self.task = {
                "task_id": task_id,
                "schedule_id": schedule_id,
                "source_id": source_id,
                "execution_kind": execution_kind,
                "product_state": "provisioning",
                "revision": 1,
                "created_by": actor,
                "created_at": now_utc,
                "updated_by": actor,
                "updated_at": now_utc,
            }
        return dict(self.task)

    def create_version(self, *, schedule_id, config, actor, schedule_version_id):
        self.version_calls += 1
        return {
            "schedule_version_id": schedule_version_id,
            "schedule_id": schedule_id,
            "version_number": 1,
            "status": "draft" if self.schedule["active_version_id"] is None else "approved",
        }

    def approve_version(self, *, schedule_id, version_number, actor, now_utc):
        self.schedule["active_version_id"] = "sv-create-1"
        return {"schedule_version_id": "sv-create-1", "status": "approved", "version_number": 1}

    def finalize_one_time_product_task_create(self, *, request_id, task_id, actor, now_utc):
        if self.request["state"] == "succeeded":
            return dict(self.request["safe_result"])
        self.finalize_calls += 1
        self.task["product_state"] = "active"
        self.run = {
            "batch_run_id": "br-create-1",
            "schedule_id": "sch-create-1",
            "schedule_version_id": "sv-create-1",
            "snapshot_id": "snap-create-1",
            "trigger_type": "manual",
            "trigger_request_id": "private-stable-create-trigger",
            "scheduled_for": None,
            "state": "handoff_pending",
            "selected_count": 1,
            "skipped_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "error_code": None,
            "deadline_elapsed_during_execution": False,
            "created_at": now_utc,
            "completed_at": None,
            "items": [
                {
                    "run_item_id": "ri-create-1",
                    "requirement_id": "req-create-1",
                    "requirement_version_id": "rv-create-1",
                    "requirement_version_number": 1,
                    "source_order": 1,
                    "selection_status": "selected",
                    "execution_state": "handoff_pending",
                    "error_code": None,
                    "artifact_relative_path": None,
                    "artifact_sha256": None,
                }
            ],
        }
        result = {
            "task_id": task_id,
            "source_id": "src-create-1",
            "import_run_id": "run-create-1",
            "snapshot_id": "snap-create-1",
            "schedule_id": "sch-create-1",
            "schedule_version_id": "sv-create-1",
            "batch_run_id": "br-create-1",
            "task_revision": 1,
        }
        self.request["state"] = "succeeded"
        self.request["safe_result"] = dict(result)
        self.request["batch_run_id"] = "br-create-1"
        if self.raise_after_finalize_commit and not self._lost_response_raised:
            self._lost_response_raised = True
            raise RuntimeError("simulated_lost_response")
        return result

    def finalize_recurring_product_task_create(self, *, request_id, task_id, actor, now_utc):
        if self.request["state"] == "succeeded":
            return dict(self.request["safe_result"])
        self.recurring_finalize_calls += 1
        self.recurring_finalize_now = now_utc
        assert self.task["execution_kind"] == "recurring"
        assert self.task["product_state"] == "provisioning"
        assert self.schedule["enabled"] is False
        assert self.schedule["active_version_id"] == "sv-create-1"
        assert self.schedule["next_run_at"] is None
        next_run_at = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
        self.schedule["enabled"] = True
        self.schedule["next_run_at"] = next_run_at
        self.task["product_state"] = "active"
        result = {
            "task_id": task_id,
            "source_id": "src-create-1",
            "import_run_id": "run-create-1",
            "snapshot_id": "snap-create-1",
            "schedule_id": "sch-create-1",
            "schedule_version_id": "sv-create-1",
            "next_run_at": next_run_at.isoformat(),
            "task_revision": 1,
        }
        self.request["state"] = "succeeded"
        self.request["safe_result"] = dict(result)
        if self.raise_after_finalize_commit and not self._lost_response_raised:
            self._lost_response_raised = True
            raise RuntimeError("simulated_lost_response")
        return result

    def get_product_task(self, task_id):
        assert self.task is not None and self.task["task_id"] == task_id
        return dict(self.task)

    def get_schedule(self, schedule_id):
        assert self.schedule is not None and self.schedule["schedule_id"] == schedule_id
        return dict(self.schedule)

    def get_batch_run(self, *, schedule_id, batch_run_id):
        assert self.run is not None
        assert self.run["schedule_id"] == schedule_id
        assert self.run["batch_run_id"] == batch_run_id
        return dict(self.run)


def _create_service():
    requirement_service = _CreateRequirementImportService()
    schedule_store = _CreateScheduleStore()
    service = RequirementProductService(
        requirement_import_service=requirement_service,
        schedule_store=schedule_store,
    )
    return service, requirement_service, schedule_store


def test_one_time_product_create_rejects_lower_role_before_reservation():
    service, requirement_service, schedule_store = _create_service()

    with pytest.raises(PermissionError, match="superuser_required"):
        service.create_one_time_task(
            actor="operator",
            is_superuser=False,
            idempotency_key="idem-1",
            name="One Time",
            profile_version_id="pv-1",
            schedule_config=_once_schedule_config(),
            requirements=_valid_direct_requirements(),
        )

    assert schedule_store.reserve_calls == 0
    assert requirement_service.commit_calls == 0
    assert requirement_service.store.sources == {}


def test_one_time_product_create_binds_exact_authorities_and_releases_one_run():
    service, requirement_service, schedule_store = _create_service()
    now = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)

    result = service.create_one_time_task(
        actor="admin",
        is_superuser=True,
        idempotency_key="idem-1",
        name="One Time",
        profile_version_id="pv-1",
        schedule_config=_once_schedule_config(),
        requirements=_valid_direct_requirements(),
        now_utc=now,
    )

    assert result["task"]["task_id"] == "task-create-1"
    assert result["task"]["execution_kind"] == "once"
    assert result["task"]["product_state"] == "active"
    assert result["task"]["schedule"]["enabled"] is False
    assert result["run"]["run_id"] == "br-create-1"
    assert result["run"]["status"] == "queued"
    assert result["run"]["binding"] == {
        "schedule_id": "sch-create-1",
        "schedule_version_id": "sv-create-1",
        "snapshot_id": "snap-create-1",
    }
    assert result["run"]["trigger"]["type"] == "manual"
    assert requirement_service.commit_calls == 1
    assert requirement_service.store.create_source_calls == 1
    assert requirement_service.store.patch_source_calls == 1
    assert schedule_store.version_calls == 1
    assert schedule_store.finalize_calls == 1


def test_one_time_product_create_lost_response_replays_without_duplicate_work():
    service, requirement_service, schedule_store = _create_service()
    schedule_store.raise_after_finalize_commit = True
    kwargs = {
        "actor": "admin",
        "is_superuser": True,
        "idempotency_key": "idem-lost",
        "name": "One Time",
        "profile_version_id": "pv-1",
        "schedule_config": _once_schedule_config(),
        "requirements": _valid_direct_requirements(),
        "now_utc": datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
    }

    with pytest.raises(RuntimeError, match="simulated_lost_response"):
        service.create_one_time_task(**kwargs)

    replay = service.create_one_time_task(**kwargs)

    assert replay["task"]["task_id"] == "task-create-1"
    assert replay["run"]["run_id"] == "br-create-1"
    assert requirement_service.commit_calls == 1
    assert schedule_store.version_calls == 1
    assert schedule_store.finalize_calls == 1


def test_one_time_product_create_same_key_changed_payload_conflicts():
    service, _, _ = _create_service()
    base = {
        "actor": "admin",
        "is_superuser": True,
        "idempotency_key": "idem-conflict",
        "name": "One Time",
        "profile_version_id": "pv-1",
        "schedule_config": _once_schedule_config(),
        "requirements": _valid_direct_requirements(),
        "now_utc": datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
    }
    service.create_one_time_task(**base)

    with pytest.raises(ValueError, match="requirement_idempotency_conflict"):
        service.create_one_time_task(**{**base, "name": "Changed Name"})



def test_one_time_product_create_rejects_zero_row_input_before_mutation():
    service, requirement_service, schedule_store = _create_service()

    with pytest.raises(ValueError, match="requirement_preview_empty"):
        service.create_one_time_task(
            actor="admin",
            is_superuser=True,
            idempotency_key="idem-empty",
            name="Empty",
            profile_version_id="pv-1",
            schedule_config=_once_schedule_config(),
            requirements=[],
            now_utc=datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
        )

    assert schedule_store.request["state"] == "failed_terminal"
    assert schedule_store.request["error_code"] == "requirement_preview_empty"
    assert requirement_service.commit_calls == 0
    assert requirement_service.store.sources == {}
    assert schedule_store.finalize_calls == 0


def test_one_time_product_create_recovers_committed_import_after_profile_switch():
    service, requirement_service, schedule_store = _create_service()
    requirement_service.raise_after_commit_once = True
    kwargs = {
        "actor": "admin",
        "is_superuser": True,
        "idempotency_key": "idem-import-recovery",
        "name": "One Time",
        "profile_version_id": "pv-1",
        "schedule_config": _once_schedule_config(),
        "requirements": _valid_direct_requirements(),
        "now_utc": datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
    }

    with pytest.raises(RuntimeError, match="simulated_import_lost_response"):
        service.create_one_time_task(**kwargs)

    original_get_active = requirement_service.store.get_active_profile_version
    requirement_service.store.get_active_profile_version = lambda _profile_id: {
        **requirement_service.store.version,
        "profile_version_id": "pv-new",
        "profile_sha256": "f" * 64,
    }
    try:
        replay = service.create_one_time_task(**kwargs)
    finally:
        requirement_service.store.get_active_profile_version = original_get_active

    assert replay["task"]["task_id"] == "task-create-1"
    assert replay["run"]["run_id"] == "br-create-1"
    assert requirement_service.commit_calls == 2
    assert schedule_store.finalize_calls == 1



def test_one_time_product_create_rejects_expired_only_input_before_mutation():
    service, requirement_service, schedule_store = _create_service()
    expired = [
        {
            "external_item_id": "E-expired",
            "title": "Expired",
            "prompt_content": "old",
            "source_updated_at": "2026-10-01T01:00:00Z",
            "source_created_at": "2026-10-01T01:00:00Z",
            "expires_at": "2026-10-07T03:59:59Z",
        }
    ]

    with pytest.raises(ValueError, match="requirement_preview_no_selectable_rows"):
        service.create_one_time_task(
            actor="admin",
            is_superuser=True,
            idempotency_key="idem-expired",
            name="Expired Only",
            profile_version_id="pv-1",
            schedule_config=_once_schedule_config(),
            requirements=expired,
            now_utc=datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
        )

    assert schedule_store.request["state"] == "failed_terminal"
    assert schedule_store.request["error_code"] == "requirement_preview_no_selectable_rows"
    assert requirement_service.commit_calls == 0
    assert requirement_service.store.sources == {}
    assert schedule_store.finalize_calls == 0



def test_one_time_product_create_retry_uses_original_request_time_for_eligibility():
    service, requirement_service, schedule_store = _create_service()
    requirement_service.raise_after_commit_once = True
    first_now = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
    requirements = [
        {
            "external_item_id": "E-window",
            "title": "Still eligible at request time",
            "prompt_content": "alpha",
            "source_updated_at": "2026-10-07T03:00:00Z",
            "source_created_at": "2026-10-01T01:00:00Z",
            "expires_at": "2026-10-07T04:05:00Z",
        }
    ]
    base = {
        "actor": "admin",
        "is_superuser": True,
        "idempotency_key": "idem-window",
        "name": "Eligibility Window",
        "profile_version_id": "pv-1",
        "schedule_config": _once_schedule_config(),
        "requirements": requirements,
    }

    with pytest.raises(RuntimeError, match="simulated_import_lost_response"):
        service.create_one_time_task(**base, now_utc=first_now)

    replay = service.create_one_time_task(
        **base,
        now_utc=datetime(2026, 10, 7, 4, 10, tzinfo=timezone.utc),
    )

    assert schedule_store.request["created_at"] == first_now
    assert replay["task"]["task_id"] == "task-create-1"
    assert replay["run"]["run_id"] == "br-create-1"
    assert schedule_store.request["state"] == "succeeded"
    assert schedule_store.finalize_calls == 1



def test_recurring_product_create_rejects_lower_role_before_reservation():
    service, requirement_service, schedule_store = _create_service()

    with pytest.raises(PermissionError, match="superuser_required"):
        service.create_recurring_task(
            actor="operator",
            is_superuser=False,
            idempotency_key="idem-recurring-role",
            name="Recurring",
            profile_version_id="pv-1",
            schedule_config=_once_schedule_config(),
            requirements=_valid_direct_requirements(),
        )

    assert schedule_store.reserve_calls == 0
    assert requirement_service.commit_calls == 0
    assert requirement_service.store.sources == {}


def test_recurring_product_create_enables_only_in_finalizer_and_returns_initial_due():
    service, requirement_service, schedule_store = _create_service()
    now = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)

    result = service.create_recurring_task(
        actor="admin",
        is_superuser=True,
        idempotency_key="idem-recurring",
        name="Recurring",
        profile_version_id="pv-1",
        schedule_config=_once_schedule_config(),
        requirements=_valid_direct_requirements(),
        now_utc=now,
    )

    assert result["task"]["task_id"] == "task-create-1"
    assert result["task"]["execution_kind"] == "recurring"
    assert result["task"]["product_state"] == "active"
    assert result["task"]["schedule"]["enabled"] is True
    assert result["task"]["schedule"]["active_version_id"] == "sv-create-1"
    assert result["recurrence"] == {
        "schedule_version_id": "sv-create-1",
        "initial_next_run_at": "2026-10-08T09:00:00+00:00",
    }
    assert schedule_store.run is None
    assert schedule_store.recurring_finalize_calls == 1
    assert schedule_store.finalize_calls == 0
    assert requirement_service.commit_calls == 1


def test_recurring_product_create_lost_response_replays_original_due_without_duplicate_enable():
    service, requirement_service, schedule_store = _create_service()
    schedule_store.raise_after_finalize_commit = True
    kwargs = {
        "actor": "admin",
        "is_superuser": True,
        "idempotency_key": "idem-recurring-lost",
        "name": "Recurring",
        "profile_version_id": "pv-1",
        "schedule_config": _once_schedule_config(),
        "requirements": _valid_direct_requirements(),
        "now_utc": datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
    }

    with pytest.raises(RuntimeError, match="simulated_lost_response"):
        service.create_recurring_task(**kwargs)

    schedule_store.schedule["next_run_at"] = datetime(
        2026, 10, 9, 9, 0, tzinfo=timezone.utc
    )
    replay = service.create_recurring_task(**kwargs)

    assert replay["recurrence"]["initial_next_run_at"] == "2026-10-08T09:00:00+00:00"
    assert replay["task"]["schedule"]["next_run_at"] == datetime(
        2026, 10, 9, 9, 0, tzinfo=timezone.utc
    )
    assert requirement_service.commit_calls == 1
    assert schedule_store.version_calls == 1
    assert schedule_store.recurring_finalize_calls == 1


def test_task_create_same_key_once_vs_recurring_conflicts():
    service, _, _ = _create_service()
    common = {
        "actor": "admin",
        "is_superuser": True,
        "idempotency_key": "idem-kind-conflict",
        "name": "Task",
        "profile_version_id": "pv-1",
        "schedule_config": _once_schedule_config(),
        "requirements": _valid_direct_requirements(),
        "now_utc": datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
    }
    service.create_one_time_task(**common)

    with pytest.raises(ValueError, match="requirement_idempotency_conflict"):
        service.create_recurring_task(**common)



def test_recurring_product_create_refreshes_finalization_clock():
    service, _, schedule_store = _create_service()
    request_now = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
    finalize_now = datetime(2026, 10, 7, 4, 10, tzinfo=timezone.utc)

    service.create_recurring_task(
        actor="admin",
        is_superuser=True,
        idempotency_key="idem-recurring-clock",
        name="Recurring Clock",
        profile_version_id="pv-1",
        schedule_config=_once_schedule_config(),
        requirements=_valid_direct_requirements(),
        now_utc=request_now,
        finalize_now_utc=finalize_now,
    )

    assert schedule_store.request["created_at"] == request_now
    assert schedule_store.recurring_finalize_now == finalize_now
