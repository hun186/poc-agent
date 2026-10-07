from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from data_ingestion.requirements.hashing import canonical_sha256
from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.profile import normalize_rows
from data_ingestion.requirements.source_adapters import acquire_source
from requirement_scheduler.models import ScheduleVersionCreate


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

    def __init__(
        self,
        requirement_import_service: Any | None = None,
        schedule_store: Any | None = None,
    ) -> None:
        self.requirement_import_service = requirement_import_service
        self.schedule_store = schedule_store

    @staticmethod
    def _input_bytes(
        *,
        upload_bytes: bytes | None,
        upload_filename: str | None,
        requirements: Any | None,
    ) -> tuple[bytes, str]:
        has_upload = upload_bytes is not None or upload_filename is not None
        has_direct = requirements is not None
        if has_upload == has_direct:
            raise ValueError("requirement_preview_input_invalid")
        if has_upload:
            if upload_bytes is None or not upload_filename:
                raise ValueError("requirement_preview_input_invalid")
            return upload_bytes, Path(upload_filename).name
        try:
            content = json.dumps(
                requirements,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("source_format_invalid") from exc
        return content, "requirements.json"

    @staticmethod
    def _validate_existing_product_source(
        source: dict[str, Any],
        *,
        source_id: str,
        name: str,
        source_mode: str,
        source_format: str,
        profile_id: str,
    ) -> None:
        expected_config = {"display_name": name, "format": source_format}
        if (
            source.get("source_id") != source_id
            or source.get("name") != name
            or source.get("source_type") != "manual_upload"
            or source.get("source_mode") != source_mode
            or source.get("source_config") != expected_config
            or source.get("import_profile_id") != profile_id
        ):
            raise RuntimeError("persistence_error")

    def _present_one_time_create_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        task = self.schedule_store.get_product_task(result["task_id"])
        schedule = self.schedule_store.get_schedule(result["schedule_id"])
        run = self.schedule_store.get_batch_run(
            schedule_id=result["schedule_id"],
            batch_run_id=result["batch_run_id"],
        )
        return {
            "task": self.present_task(product_task=task, schedule=schedule),
            "run": self.present_run(product_task=task, run=run),
        }

    def _present_recurring_create_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        task_id = _required_text(
            result, "task_id", error="requirement_product_create_result_invalid"
        )
        schedule_id = _required_text(
            result, "schedule_id", error="requirement_product_create_result_invalid"
        )
        schedule_version_id = _required_text(
            result,
            "schedule_version_id",
            error="requirement_product_create_result_invalid",
        )
        initial_next_run_at = _required_text(
            result, "next_run_at", error="requirement_product_create_result_invalid"
        )
        try:
            parsed_next = datetime.fromisoformat(
                initial_next_run_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError("requirement_product_create_result_invalid") from exc
        if parsed_next.tzinfo is None:
            raise ValueError("requirement_product_create_result_invalid")

        task = self.schedule_store.get_product_task(task_id)
        schedule = self.schedule_store.get_schedule(schedule_id)
        identity = ProductTaskIdentity.from_product_task_row(task)
        if (
            identity.execution_kind != "recurring"
            or identity.product_state != "active"
            or not bool(schedule.get("enabled"))
            or schedule.get("active_version_id") != schedule_version_id
        ):
            raise ValueError("requirement_product_create_result_invalid")
        return {
            "task": self.present_task(product_task=task, schedule=schedule),
            "recurrence": {
                "schedule_version_id": schedule_version_id,
                "initial_next_run_at": initial_next_run_at,
            },
        }

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

        input_bytes, input_filename = self._input_bytes(
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            requirements=requirements,
        )
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
        profile_id = _required_text(
            version, "profile_id", error="requirement_preview_profile_invalid"
        )
        profile_sha256 = _required_text(
            version, "profile_sha256", error="requirement_preview_profile_invalid"
        )
        if canonical_sha256(profile.model_dump(mode="json")) != profile_sha256:
            raise ValueError("requirement_preview_profile_invalid")
        if (
            version.get("format") != profile.format
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
            upload_bytes=input_bytes,
            upload_filename=input_filename,
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
                "profile_id": profile_id,
                "profile_version_id": profile_version_id,
                "version_number": version_number,
                "profile_sha256": profile_sha256,
                "format": profile.format,
                "source_mode": profile.source_mode.value,
            },
        }

    @staticmethod
    def _preview_selectable_count(
        preview: dict[str, Any], *, evaluation_time: datetime
    ) -> int:
        rows = preview.get("normalized_preview")
        if not isinstance(rows, list):
            raise RuntimeError("requirement_preview_invalid")
        selectable = 0
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("requirement_preview_invalid")
            expires_at = row.get("expires_at")
            if expires_at is None:
                selectable += 1
                continue
            if isinstance(expires_at, datetime):
                expiry = expires_at
            elif isinstance(expires_at, str):
                try:
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise RuntimeError("requirement_preview_invalid") from exc
            else:
                raise RuntimeError("requirement_preview_invalid")
            if expiry.tzinfo is None:
                raise RuntimeError("requirement_preview_invalid")
            if expiry.astimezone(timezone.utc) > evaluation_time.astimezone(timezone.utc):
                selectable += 1
        return selectable

    @staticmethod
    def _request_evaluation_time(request: dict[str, Any]) -> datetime:
        value = request.get("created_at")
        if isinstance(value, datetime):
            evaluation_time = value
        elif isinstance(value, str):
            try:
                evaluation_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise RuntimeError("persistence_error") from exc
        else:
            raise RuntimeError("persistence_error")
        if evaluation_time.tzinfo is None:
            raise RuntimeError("persistence_error")
        return evaluation_time.astimezone(timezone.utc)

    def create_one_time_task(
        self,
        *,
        actor: str,
        is_superuser: bool,
        idempotency_key: str,
        name: str,
        profile_version_id: str,
        schedule_config: ScheduleVersionCreate,
        upload_bytes: bytes | None = None,
        upload_filename: str | None = None,
        requirements: Any | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Provision one Product Task and atomically release its initial manual Run."""

        if not is_superuser:
            raise PermissionError("superuser_required")
        if self.requirement_import_service is None or self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        if not actor or len(actor) > 128:
            raise ValueError("requirement_product_request_invalid")
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 240:
            raise ValueError("schedule_name_invalid")

        input_bytes, input_filename = self._input_bytes(
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            requirements=requirements,
        )
        input_sha256 = canonical_sha256(
            {"bytes_sha256": hashlib.sha256(input_bytes).hexdigest()}
        )
        _, schedule_sha256 = self.schedule_store.canonical_config(schedule_config)
        request_sha256 = canonical_sha256(
            {
                "operation": "task_create",
                "execution_kind": "once",
                "name": clean_name,
                "profile_version_id": profile_version_id,
                "input_sha256": input_sha256,
                "input_filename": input_filename,
                "schedule_config_sha256": schedule_sha256,
            }
        )
        now = now_utc or datetime.now(timezone.utc).replace(microsecond=0)
        request = self.schedule_store.reserve_product_task_create(
            principal_kind="user",
            principal_id=actor,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            now_utc=now,
        )
        if request["state"] == "succeeded":
            result = request.get("safe_result")
            if not isinstance(result, dict):
                raise RuntimeError("persistence_error")
            return self._present_one_time_create_result(result)
        if request["state"] == "failed_terminal":
            raise ValueError(
                request.get("error_code") or "requirement_product_request_terminal"
            )

        try:
            preview = self.preview_input(
                profile_version_id=profile_version_id,
                upload_bytes=input_bytes if requirements is None else None,
                upload_filename=input_filename if requirements is None else None,
                requirements=requirements,
            )
        except (KeyError, ValueError) as exc:
            code = str(exc).strip("'").split(":", 1)[0]
            if not code or len(code) > 64:
                code = "requirement_preview_invalid"
            self.schedule_store.fail_product_request_terminal(
                request["request_id"], error_code=code, now_utc=now
            )
            raise
        if preview["has_errors"]:
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_preview_rejected",
                now_utc=now,
            )
            raise ValueError("requirement_preview_rejected")
        if int(preview.get("accepted_count") or 0) < 1:
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_preview_empty",
                now_utc=now,
            )
            raise ValueError("requirement_preview_empty")
        evaluation_time = self._request_evaluation_time(request)
        if self._preview_selectable_count(preview, evaluation_time=evaluation_time) < 1:
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_preview_no_selectable_rows",
                now_utc=now,
            )
            raise ValueError("requirement_preview_no_selectable_rows")

        profile = preview["profile"]

        self.schedule_store.mark_product_request_in_progress(
            request["request_id"], now_utc=now
        )

        requirement_store = self.requirement_import_service.store
        try:
            source = requirement_store.get_source(request["source_id"])
            self._validate_existing_product_source(
                source,
                source_id=request["source_id"],
                name=clean_name,
                source_mode=profile["source_mode"],
                source_format=profile["format"],
                profile_id=profile["profile_id"],
            )
        except KeyError:
            source = requirement_store.create_source(
                clean_name,
                "manual_upload",
                profile["source_mode"],
                {"display_name": clean_name, "format": profile["format"]},
                profile["profile_id"],
                actor,
                enabled=False,
                source_id=request["source_id"],
            )
        if not bool(source.get("enabled")):
            source = requirement_store.patch_source(
                request["source_id"], actor, enabled=True
            )
        self._validate_existing_product_source(
            source,
            source_id=request["source_id"],
            name=clean_name,
            source_mode=profile["source_mode"],
            source_format=profile["format"],
            profile_id=profile["profile_id"],
        )
        if not bool(source.get("enabled")):
            raise RuntimeError("persistence_error")

        try:
            import_result = self.requirement_import_service.commit(
                request["source_id"],
                actor=actor,
                upload_bytes=input_bytes,
                upload_filename=input_filename,
                import_run_id=request["import_run_id"],
                snapshot_id=request["snapshot_id"],
                expected_profile_version_id=profile_version_id,
                expected_profile_sha256=profile["profile_sha256"],
            )
        except ValueError as exc:
            code = str(exc).strip("'").split(":", 1)[0]
            if code == "profile_invalid":
                self.schedule_store.fail_product_request_terminal(
                    request["request_id"],
                    error_code="requirement_preview_profile_not_active",
                    now_utc=now,
                )
            raise
        if (
            import_result.get("status") != "committed"
            or import_result.get("import_run_id") != request["import_run_id"]
            or import_result.get("snapshot_id") != request["snapshot_id"]
        ):
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_product_import_failed",
                now_utc=now,
            )
            raise ValueError("requirement_product_import_failed")

        requirement_set = requirement_store.get_requirement_set_for_source(
            request["source_id"]
        )
        if requirement_set.get("active_snapshot_id") != request["snapshot_id"]:
            raise RuntimeError("persistence_error")

        schedule = self.schedule_store.create_schedule(
            name=clean_name,
            requirement_set_id=requirement_set["requirement_set_id"],
            actor=actor,
            schedule_id=request["schedule_id"],
        )
        if (
            bool(schedule.get("enabled"))
            or schedule.get("active_version_id") not in {
                None, request["schedule_version_id"]
            }
            or schedule.get("next_run_at") is not None
        ):
            raise RuntimeError("persistence_error")
        self.schedule_store.create_product_task_provisioning(
            task_id=request["task_id"],
            schedule_id=request["schedule_id"],
            source_id=request["source_id"],
            execution_kind="once",
            actor=actor,
            now_utc=now,
        )
        version = self.schedule_store.create_version(
            schedule_id=request["schedule_id"],
            config=schedule_config,
            actor=actor,
            schedule_version_id=request["schedule_version_id"],
        )
        if version.get("schedule_version_id") != request["schedule_version_id"]:
            raise RuntimeError("persistence_error")
        self.schedule_store.approve_version(
            schedule_id=request["schedule_id"],
            version_number=int(version["version_number"]),
            actor=actor,
            now_utc=now,
        )

        result = self.schedule_store.finalize_one_time_product_task_create(
            request_id=request["request_id"],
            task_id=request["task_id"],
            actor=actor,
            now_utc=now,
        )
        return self._present_one_time_create_result(result)

    def create_recurring_task(
        self,
        *,
        actor: str,
        is_superuser: bool,
        idempotency_key: str,
        name: str,
        profile_version_id: str,
        schedule_config: ScheduleVersionCreate,
        upload_bytes: bytes | None = None,
        upload_filename: str | None = None,
        requirements: Any | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Provision one recurring Product Task and atomically enable recurrence."""

        if not is_superuser:
            raise PermissionError("superuser_required")
        if self.requirement_import_service is None or self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        if not actor or len(actor) > 128:
            raise ValueError("requirement_product_request_invalid")
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 240:
            raise ValueError("schedule_name_invalid")

        input_bytes, input_filename = self._input_bytes(
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            requirements=requirements,
        )
        input_sha256 = canonical_sha256(
            {"bytes_sha256": hashlib.sha256(input_bytes).hexdigest()}
        )
        _, schedule_sha256 = self.schedule_store.canonical_config(schedule_config)
        request_sha256 = canonical_sha256(
            {
                "operation": "task_create",
                "execution_kind": "recurring",
                "name": clean_name,
                "profile_version_id": profile_version_id,
                "input_sha256": input_sha256,
                "input_filename": input_filename,
                "schedule_config_sha256": schedule_sha256,
            }
        )
        now = now_utc or datetime.now(timezone.utc).replace(microsecond=0)
        request = self.schedule_store.reserve_product_task_create(
            principal_kind="user",
            principal_id=actor,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            now_utc=now,
        )
        if request["state"] == "succeeded":
            result = request.get("safe_result")
            if not isinstance(result, dict):
                raise RuntimeError("persistence_error")
            return self._present_recurring_create_result(result)
        if request["state"] == "failed_terminal":
            raise ValueError(
                request.get("error_code") or "requirement_product_request_terminal"
            )

        try:
            preview = self.preview_input(
                profile_version_id=profile_version_id,
                upload_bytes=input_bytes if requirements is None else None,
                upload_filename=input_filename if requirements is None else None,
                requirements=requirements,
            )
        except (KeyError, ValueError) as exc:
            code = str(exc).strip("'").split(":", 1)[0]
            if not code or len(code) > 64:
                code = "requirement_preview_invalid"
            self.schedule_store.fail_product_request_terminal(
                request["request_id"], error_code=code, now_utc=now
            )
            raise
        if preview["has_errors"]:
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_preview_rejected",
                now_utc=now,
            )
            raise ValueError("requirement_preview_rejected")
        if int(preview.get("accepted_count") or 0) < 1:
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_preview_empty",
                now_utc=now,
            )
            raise ValueError("requirement_preview_empty")
        evaluation_time = self._request_evaluation_time(request)
        if self._preview_selectable_count(preview, evaluation_time=evaluation_time) < 1:
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_preview_no_selectable_rows",
                now_utc=now,
            )
            raise ValueError("requirement_preview_no_selectable_rows")

        profile = preview["profile"]

        self.schedule_store.mark_product_request_in_progress(
            request["request_id"], now_utc=now
        )

        requirement_store = self.requirement_import_service.store
        try:
            source = requirement_store.get_source(request["source_id"])
            self._validate_existing_product_source(
                source,
                source_id=request["source_id"],
                name=clean_name,
                source_mode=profile["source_mode"],
                source_format=profile["format"],
                profile_id=profile["profile_id"],
            )
        except KeyError:
            source = requirement_store.create_source(
                clean_name,
                "manual_upload",
                profile["source_mode"],
                {"display_name": clean_name, "format": profile["format"]},
                profile["profile_id"],
                actor,
                enabled=False,
                source_id=request["source_id"],
            )
        if not bool(source.get("enabled")):
            source = requirement_store.patch_source(
                request["source_id"], actor, enabled=True
            )
        self._validate_existing_product_source(
            source,
            source_id=request["source_id"],
            name=clean_name,
            source_mode=profile["source_mode"],
            source_format=profile["format"],
            profile_id=profile["profile_id"],
        )
        if not bool(source.get("enabled")):
            raise RuntimeError("persistence_error")

        try:
            import_result = self.requirement_import_service.commit(
                request["source_id"],
                actor=actor,
                upload_bytes=input_bytes,
                upload_filename=input_filename,
                import_run_id=request["import_run_id"],
                snapshot_id=request["snapshot_id"],
                expected_profile_version_id=profile_version_id,
                expected_profile_sha256=profile["profile_sha256"],
            )
        except ValueError as exc:
            code = str(exc).strip("'").split(":", 1)[0]
            if code == "profile_invalid":
                self.schedule_store.fail_product_request_terminal(
                    request["request_id"],
                    error_code="requirement_preview_profile_not_active",
                    now_utc=now,
                )
            raise
        if (
            import_result.get("status") != "committed"
            or import_result.get("import_run_id") != request["import_run_id"]
            or import_result.get("snapshot_id") != request["snapshot_id"]
        ):
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_product_import_failed",
                now_utc=now,
            )
            raise ValueError("requirement_product_import_failed")

        requirement_set = requirement_store.get_requirement_set_for_source(
            request["source_id"]
        )
        if requirement_set.get("active_snapshot_id") != request["snapshot_id"]:
            raise RuntimeError("persistence_error")

        schedule = self.schedule_store.create_schedule(
            name=clean_name,
            requirement_set_id=requirement_set["requirement_set_id"],
            actor=actor,
            schedule_id=request["schedule_id"],
        )
        if (
            bool(schedule.get("enabled"))
            or schedule.get("active_version_id") not in {
                None, request["schedule_version_id"]
            }
            or schedule.get("next_run_at") is not None
        ):
            raise RuntimeError("persistence_error")
        self.schedule_store.create_product_task_provisioning(
            task_id=request["task_id"],
            schedule_id=request["schedule_id"],
            source_id=request["source_id"],
            execution_kind="recurring",
            actor=actor,
            now_utc=now,
        )
        version = self.schedule_store.create_version(
            schedule_id=request["schedule_id"],
            config=schedule_config,
            actor=actor,
            schedule_version_id=request["schedule_version_id"],
        )
        if version.get("schedule_version_id") != request["schedule_version_id"]:
            raise RuntimeError("persistence_error")
        self.schedule_store.approve_version(
            schedule_id=request["schedule_id"],
            version_number=int(version["version_number"]),
            actor=actor,
            now_utc=now,
        )

        result = self.schedule_store.finalize_recurring_product_task_create(
            request_id=request["request_id"],
            task_id=request["task_id"],
            actor=actor,
            now_utc=now,
        )
        return self._present_one_time_create_result(result)

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
