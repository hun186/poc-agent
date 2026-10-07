from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import quote

from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.profile import normalize_rows
from data_ingestion.requirements.source_adapters import acquire_source


_PRODUCT_STATES = {"provisioning", "active", "disabled"}
_EXECUTION_KINDS = {"once", "recurring"}

_RUN_STATE_MAP = {
    "handoff_pending": "queued",
    "running": "running",
    "completed": "completed",
    "blocked_no_snapshot": "failed",
    "failed": "failed",
    "recovery_required": "recovery_required",
}

_ITEM_STATE_MAP = {
    "handoff_pending": "queued",
    "submitting": "running",
    "pending": "running",
    "running": "running",
    "reconciling": "running",
    "completed": "completed",
    "failed": "failed",
    "expired": "failed",
    "recovery_required": "recovery_required",
    "not_selected": "not_selected",
}


def _required_text(row: dict[str, Any], key: str, *, error: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(error)
    return value


def _safe_link(*parts: str) -> str:
    return "/" + "/".join(quote(str(part), safe="") for part in parts)


@dataclass(frozen=True)
class ProductTaskIdentity:
    task_id: str
    schedule_id: str
    source_id: str
    execution_kind: str
    product_state: str
    revision: int

    @classmethod
    def from_product_task_row(cls, row: dict[str, Any]) -> "ProductTaskIdentity":
        task_id = _required_text(row, "task_id", error="requirement_product_task_identity_invalid")
        schedule_id = _required_text(row, "schedule_id", error="requirement_product_task_identity_invalid")
        source_id = _required_text(row, "source_id", error="requirement_product_task_identity_invalid")
        execution_kind = _required_text(row, "execution_kind", error="requirement_product_task_identity_invalid")
        product_state = _required_text(row, "product_state", error="requirement_product_task_identity_invalid")
        revision = row.get("revision")

        if execution_kind not in _EXECUTION_KINDS or product_state not in _PRODUCT_STATES:
            raise ValueError("requirement_product_task_identity_invalid")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("requirement_product_task_identity_invalid")
        if execution_kind == "once" and product_state == "disabled":
            raise ValueError("requirement_product_task_identity_invalid")

        return cls(
            task_id=task_id,
            schedule_id=schedule_id,
            source_id=source_id,
            execution_kind=execution_kind,
            product_state=product_state,
            revision=revision,
        )


def _require_visible(identity: ProductTaskIdentity) -> None:
    if identity.product_state == "provisioning":
        raise KeyError("requirement_task_not_found")


def neutral_run_status(run: dict[str, Any]) -> str:
    state = _required_text(run, "state", error="requirement_run_state_invalid")
    if state == "completed_with_failures":
        if "items" not in run:
            raise ValueError("requirement_run_status_evidence_missing")
        items = run.get("items")
        if not isinstance(items, (list, tuple)):
            raise ValueError("requirement_run_status_evidence_missing")

        item_states: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("requirement_run_status_evidence_missing")
            execution_state = item.get("execution_state")
            if not isinstance(execution_state, str) or execution_state not in _ITEM_STATE_MAP:
                raise ValueError("requirement_run_status_evidence_missing")
            item_states.append(execution_state)

        failure_states = {"failed", "expired", "recovery_required"}
        if not any(item_state in failure_states for item_state in item_states):
            raise ValueError("requirement_run_status_evidence_missing")
        if "recovery_required" in item_states:
            return "recovery_required"
        return "completed_with_errors"
    try:
        return _RUN_STATE_MAP[state]
    except KeyError:
        raise ValueError("requirement_run_state_invalid") from None


def _present_run_item(item: dict[str, Any]) -> dict[str, Any]:
    run_item_id = _required_text(item, "run_item_id", error="requirement_run_item_identity_invalid")
    requirement_id = _required_text(item, "requirement_id", error="requirement_run_item_identity_invalid")
    version_id = _required_text(item, "requirement_version_id", error="requirement_run_item_identity_invalid")
    version_number = item.get("requirement_version_number")
    if isinstance(version_number, bool) or not isinstance(version_number, int) or version_number < 1:
        raise ValueError("requirement_run_item_identity_invalid")

    execution_state = _required_text(item, "execution_state", error="requirement_run_item_state_invalid")
    try:
        status = _ITEM_STATE_MAP[execution_state]
    except KeyError:
        raise ValueError("requirement_run_item_state_invalid") from None

    selection_status = item.get("selection_status")
    if selection_status not in {"selected", "skipped"}:
        raise ValueError("requirement_run_item_selection_invalid")

    presented: dict[str, Any] = {
        "run_item_id": run_item_id,
        "requirement_id": requirement_id,
        "requirement_version_id": version_id,
        "requirement_version_number": version_number,
        "source_order": item.get("source_order"),
        "selection_status": selection_status,
        "status": status,
        "error_category": item.get("error_code"),
    }
    artifact_available = (
        bool(item.get("artifact_sha256"))
        and bool(item.get("artifact_relative_path"))
        and status == "completed"
    )
    presented["artifact"] = {
        "available": artifact_available,
        "sha256": item.get("artifact_sha256") if artifact_available else None,
    }
    return presented


class RequirementProductService:
    """Product façade presenters plus side-effect-free preview orchestration."""

    def __init__(self, requirement_import_service: Any | None = None) -> None:
        self.requirement_import_service = requirement_import_service

    def preview_input(
        self,
        *,
        profile_version_id: str,
        upload_bytes: bytes | None = None,
        upload_filename: str | None = None,
        requirements: Any | None = None,
    ) -> dict[str, Any]:
        """Normalize candidate Requirement input without creating durable state."""

        if not isinstance(profile_version_id, str) or not profile_version_id:
            raise ValueError("requirement_preview_profile_invalid")
        if self.requirement_import_service is None:
            raise RuntimeError("requirement_preview_unconfigured")

        has_upload = upload_bytes is not None or upload_filename is not None
        has_direct = requirements is not None
        if has_upload == has_direct:
            raise ValueError("requirement_preview_input_invalid")
        if has_upload and (upload_bytes is None or not upload_filename):
            raise ValueError("requirement_preview_input_invalid")

        version = self.requirement_import_service.store.get_profile_version(
            profile_version_id
        )
        if version.get("status") != "approved":
            raise ValueError("requirement_preview_profile_not_approved")
        if version.get("profile_version_id") != profile_version_id:
            raise ValueError("requirement_preview_profile_invalid")

        profile = version.get("profile")
        if not isinstance(profile, ImportProfileDocument):
            raise ValueError("requirement_preview_profile_invalid")
        if (
            version.get("profile_id") is None
            or version.get("format") != profile.format
            or version.get("source_mode") != profile.source_mode.value
        ):
            raise ValueError("requirement_preview_profile_invalid")
        version_number = version.get("version_number")
        if (
            isinstance(version_number, bool)
            or not isinstance(version_number, int)
            or version_number < 1
        ):
            raise ValueError("requirement_preview_profile_invalid")

        if has_direct:
            try:
                upload_bytes = json.dumps(
                    requirements,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ValueError("source_format_invalid") from exc
            upload_filename = "requirements.json"

        source = {
            "source_type": "manual_upload",
            "source_mode": profile.source_mode.value,
            "source_config": {
                "display_name": "Product preview",
                "format": profile.format,
            },
        }
        acquired = acquire_source(
            source,
            profile,
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
        )
        candidate = normalize_rows(
            acquired.rows,
            profile,
            acquired.source_row_numbers,
        )

        diagnostics = [
            item.model_dump(mode="json") for item in candidate.diagnostics
        ]
        errors = [item for item in diagnostics if item["severity"] == "error"]
        warnings = [item for item in diagnostics if item["severity"] == "warning"]
        preview_fields = {
            "source_row_number",
            "external_item_id",
            "title",
            "prompt_content",
            "source_updated_at",
            "expires_at",
            "source_created_by",
            "source_updated_by",
            "source_created_at",
        }
        normalized_preview = [
            row.model_dump(mode="json", include=preview_fields)
            for row in candidate.rows
        ]

        return {
            "source_sha256": acquired.source_sha256,
            "row_count": len(acquired.rows),
            "accepted_count": len(candidate.rows),
            "rejected_count": len(errors),
            "has_errors": bool(errors),
            "normalized_preview": normalized_preview,
            "errors": errors,
            "warnings": warnings,
            "profile": {
                "profile_id": version["profile_id"],
                "profile_version_id": profile_version_id,
                "version_number": version_number,
                "profile_sha256": version.get("profile_sha256"),
                "format": profile.format,
                "source_mode": profile.source_mode.value,
            },
        }

    @staticmethod
    def task_identity(product_task: dict[str, Any]) -> ProductTaskIdentity:
        return ProductTaskIdentity.from_product_task_row(product_task)

    @staticmethod
    def present_task(*, product_task: dict[str, Any], schedule: dict[str, Any]) -> dict[str, Any]:
        identity = ProductTaskIdentity.from_product_task_row(product_task)
        _require_visible(identity)
        if schedule.get("schedule_id") != identity.schedule_id:
            raise ValueError("requirement_product_task_identity_conflict")

        return {
            "task_id": identity.task_id,
            "name": schedule.get("name"),
            "execution_kind": identity.execution_kind,
            "product_state": identity.product_state,
            "revision": identity.revision,
            "source_id": identity.source_id,
            "schedule_id": identity.schedule_id,
            "schedule": {
                "enabled": bool(schedule.get("enabled")),
                "active_version_id": schedule.get("active_version_id"),
                "next_run_at": schedule.get("next_run_at"),
            },
            "created_by": product_task.get("created_by"),
            "created_at": product_task.get("created_at"),
            "updated_by": product_task.get("updated_by"),
            "updated_at": product_task.get("updated_at"),
            "links": {
                "self": _safe_link("v1", "requirement-tasks", identity.task_id),
                "runs": _safe_link("v1", "requirement-tasks", identity.task_id, "runs"),
            },
        }

    @staticmethod
    def present_run(*, product_task: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        identity = ProductTaskIdentity.from_product_task_row(product_task)
        _require_visible(identity)
        run_id = _required_text(run, "batch_run_id", error="requirement_run_identity_invalid")
        schedule_id = _required_text(run, "schedule_id", error="requirement_run_identity_invalid")
        schedule_version_id = _required_text(
            run, "schedule_version_id", error="requirement_run_identity_invalid"
        )
        if schedule_id != identity.schedule_id:
            raise ValueError("requirement_run_identity_conflict")

        raw_run_state = _required_text(run, "state", error="requirement_run_state_invalid")
        snapshot_id = run.get("snapshot_id")
        if snapshot_id is not None and (not isinstance(snapshot_id, str) or not snapshot_id):
            raise ValueError("requirement_run_identity_invalid")
        if raw_run_state != "blocked_no_snapshot" and snapshot_id is None:
            raise ValueError("requirement_run_snapshot_binding_missing")

        items = run.get("items", ())
        if items is None:
            items = ()
        if not isinstance(items, (list, tuple)):
            raise ValueError("requirement_run_items_invalid")

        presented_items = tuple(
            _present_run_item(item)
            for item in items
            if isinstance(item, dict)
        )
        if len(presented_items) != len(items):
            raise ValueError("requirement_run_items_invalid")

        trigger_type = run.get("trigger_type")
        if trigger_type not in {"manual", "scheduled"}:
            raise ValueError("requirement_run_trigger_invalid")

        return {
            "run_id": run_id,
            "task_id": identity.task_id,
            "status": neutral_run_status(run),
            "binding": {
                "schedule_id": schedule_id,
                "schedule_version_id": schedule_version_id,
                "snapshot_id": snapshot_id,
            },
            "trigger": {
                "type": trigger_type,
                "scheduled_for": run.get("scheduled_for"),
            },
            "counts": {
                "selected": int(run.get("selected_count") or 0),
                "skipped": int(run.get("skipped_count") or 0),
                "succeeded": int(run.get("success_count") or 0),
                "failed": int(run.get("failure_count") or 0),
            },
            "error_category": run.get("error_code"),
            "deadline_elapsed_during_execution": bool(
                run.get("deadline_elapsed_during_execution")
            ),
            "created_at": run.get("created_at"),
            "completed_at": run.get("completed_at"),
            "items": presented_items,
            "links": {
                "self": _safe_link("v1", "requirement-runs", run_id),
                "items": _safe_link("v1", "requirement-runs", run_id, "items"),
                "artifacts": _safe_link("v1", "requirement-runs", run_id, "artifacts"),
            },
        }
