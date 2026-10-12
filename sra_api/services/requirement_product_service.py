from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from zipfile import ZipFile, BadZipFile, LargeZipFile
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from data_ingestion.requirements.hashing import canonical_sha256
from data_ingestion.requirements.models import ImportProfileDocument
from data_ingestion.requirements.profile import normalize_rows
from data_ingestion.requirements.source_adapters import acquire_source
from requirement_scheduler.models import RecurrenceSpec, RunPolicy, ScheduleVersionCreate


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
            evidence = run.get("_failure_state_evidence")
            if evidence == "recovery_required":
                return "recovery_required"
            if evidence in {"failed", "expired"}:
                return "completed_with_errors"
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
            or identity.schedule_id != schedule_id
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
        max_rows: int | None = None,
        max_result_rows: int | None = None,
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
        if max_rows is not None and input_filename.lower().endswith(".xlsx"):
            # Reject compressed XLSX bombs before openpyxl inflates any worksheet.
            try:
                with ZipFile(BytesIO(input_bytes)) as archive:
                    entries = archive.infolist()
                    if len(entries) > 2000:
                        raise ValueError("requirement_preview_too_large")
                    expanded = 0
                    for entry in entries:
                        expanded += entry.file_size
                        if (entry.flag_bits & 1 or entry.file_size > 20 * 1024 * 1024
                                or expanded > 40 * 1024 * 1024):
                            raise ValueError("requirement_preview_too_large")
            except (BadZipFile, LargeZipFile, OSError) as exc:
                raise ValueError("requirement_preview_archive_invalid") from exc
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
            **({"max_rows": max_rows} if max_rows is not None else {}),
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
        selected_rows = (candidate.rows[:max_result_rows]
                         if max_result_rows is not None else candidate.rows)
        normalized_preview = [
            row.model_dump(mode="json", include=preview_fields)
            for row in selected_rows
        ]
        if max_result_rows is not None:
            # Bounded HTTP sample, never used for actual Product creation.
            def bounded(item):
                return {
                    key: value[:1024] if isinstance(value, str) else value
                    for key, value in item.items()
                }
            normalized_preview = [bounded(row) for row in normalized_preview]
            errors_sample = [bounded(item) for item in errors[:max_result_rows]]
            warnings_sample = [bounded(item) for item in warnings[:max_result_rows]]
        else:
            errors_sample, warnings_sample = errors, warnings

        return {
            "source_sha256": acquired.source_sha256,
            "row_count": len(acquired.rows),
            "accepted_count": len(candidate.rows),
            "rejected_count": len(errors),
            "has_errors": bool(errors),
            "normalized_preview": normalized_preview,
            "errors": errors_sample,
            "warnings": warnings_sample,
            "preview_truncated": (len(candidate.rows) > len(normalized_preview)
                                  or len(errors) > len(errors_sample)
                                  or len(warnings) > len(warnings_sample)),
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
        finalize_now_utc: datetime | None = None,
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

        finalization_now = (
            finalize_now_utc
            if finalize_now_utc is not None
            else datetime.now(timezone.utc).replace(microsecond=0)
        )
        if finalization_now.tzinfo is None:
            raise ValueError("timezone_naive")
        if finalization_now.astimezone(timezone.utc) < self._request_evaluation_time(request):
            raise ValueError("requirement_product_request_invalid")
        result = self.schedule_store.finalize_recurring_product_task_create(
            request_id=request["request_id"],
            task_id=request["task_id"],
            actor=actor,
            now_utc=finalization_now.astimezone(timezone.utc),
        )
        return self._present_recurring_create_result(result)

    def replace_task_input(
        self,
        *,
        task_id: str,
        actor: str,
        idempotency_key: str,
        upload_bytes: bytes | None = None,
        upload_filename: str | None = None,
        requirements: Any | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Replace Product input using a reserved immutable base-snapshot CAS."""
        if self.requirement_import_service is None or self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        if not task_id or not actor or len(actor) > 128 or not idempotency_key:
            raise ValueError("requirement_product_request_invalid")
        input_bytes, input_filename = self._input_bytes(
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            requirements=requirements,
        )
        request_sha256 = canonical_sha256({
            "operation": "input_replace",
            "task_id": task_id,
            "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "input_filename": input_filename,
        })
        now = now_utc or datetime.now(timezone.utc).replace(microsecond=0)
        request = self.schedule_store.reserve_product_input_replacement(
            task_id=task_id,
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
            return result
        if request["state"] == "failed_terminal":
            raise ValueError(
                request.get("error_code") or "requirement_product_request_terminal"
            )
        if (
            not request.get("base_snapshot_id")
            or not request.get("import_run_id")
            or not request.get("snapshot_id")
            or request.get("task_id") != task_id
        ):
            raise RuntimeError("persistence_error")

        self.schedule_store.mark_product_input_replacement_in_progress(
            request["request_id"], now_utc=now,
        )
        try:
            imported = self.requirement_import_service.commit(
                request["source_id"],
                actor=actor,
                upload_bytes=input_bytes,
                upload_filename=input_filename,
                import_run_id=request["import_run_id"],
                snapshot_id=request["snapshot_id"],
                expected_base_snapshot_id=request["base_snapshot_id"],
            )
        except ValueError as exc:
            if str(exc).strip("'").split(":", 1)[0] == "requirement_input_conflict":
                self.schedule_store.fail_product_request_terminal(
                    request["request_id"],
                    error_code="requirement_input_conflict",
                    now_utc=now,
                )
            raise
        if (
            imported.get("import_run_id") != request["import_run_id"]
            or imported.get("status") not in {"committed", "failed"}
            or (imported["status"] == "committed"
                and imported.get("snapshot_id") != request["snapshot_id"])
        ):
            raise RuntimeError("persistence_error")
        if imported["status"] == "failed":
            self.schedule_store.fail_product_request_terminal(
                request["request_id"],
                error_code="requirement_import_failed",
                now_utc=now,
            )
            raise ValueError("requirement_import_failed")
        return self.schedule_store.complete_product_input_replacement(
            request_id=request["request_id"],
            task_id=task_id,
            now_utc=now,
        )

    def update_task(
        self,
        *,
        task_id: str,
        actor: str,
        is_superuser: bool,
        idempotency_key: str,
        name: str | None = None,
        enabled: bool | None = None,
        timezone_name: str | None = None,
        recurrence: dict[str, Any] | None = None,
        run_policy: RunPolicy | str | None = None,
        model: str | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply one in-place Product Task update or create one immutable Schedule draft."""

        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        if not task_id or not actor or len(actor) > 128:
            raise ValueError("requirement_product_request_invalid")
        if not idempotency_key:
            raise ValueError("requirement_product_request_invalid")

        in_place_mode = name is not None or enabled is not None
        schedule_mode = any(
            value is not None
            for value in (timezone_name, recurrence, run_policy, model)
        )
        if in_place_mode and schedule_mode:
            raise ValueError("requirement_task_patch_mixed_modes")
        if not in_place_mode and not schedule_mode:
            raise ValueError("requirement_task_patch_invalid")

        clean_name: str | None = None
        if name is not None:
            if not isinstance(name, str):
                raise ValueError("schedule_name_invalid")
            clean_name = name.strip()
            if not clean_name or len(clean_name) > 240:
                raise ValueError("schedule_name_invalid")
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise ValueError("requirement_task_state_invalid")
            if not is_superuser:
                raise PermissionError("superuser_required")

        normalized_recurrence: RecurrenceSpec | None = None
        if recurrence is not None:
            normalized_recurrence = RecurrenceSpec.validate(recurrence)
        normalized_policy: RunPolicy | None = None
        if run_policy is not None:
            try:
                normalized_policy = (
                    run_policy if isinstance(run_policy, RunPolicy) else RunPolicy(run_policy)
                )
            except (TypeError, ValueError):
                raise ValueError("requirement_task_patch_invalid") from None
        clean_model: str | None = None
        if model is not None:
            if not isinstance(model, str):
                raise ValueError("schedule_model_invalid")
            clean_model = model.strip()
            if not clean_model or len(clean_model) > 240:
                raise ValueError("schedule_model_invalid")
        clean_timezone: str | None = None
        if timezone_name is not None:
            if not isinstance(timezone_name, str):
                raise ValueError("timezone_invalid")
            clean_timezone = timezone_name.strip()
            if not clean_timezone:
                raise ValueError("timezone_invalid")
            try:
                ZoneInfo(clean_timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("timezone_invalid") from None

        mode = "in_place" if in_place_mode else "schedule_proposal"
        patch_document: dict[str, Any] = {}
        if clean_name is not None:
            patch_document["name"] = clean_name
        if enabled is not None:
            patch_document["enabled"] = enabled
        if clean_timezone is not None:
            patch_document["timezone"] = clean_timezone
        if normalized_recurrence is not None:
            patch_document["recurrence"] = normalized_recurrence.as_dict()
        if normalized_policy is not None:
            patch_document["run_policy"] = normalized_policy.value
        if clean_model is not None:
            patch_document["model"] = clean_model

        request_sha256 = canonical_sha256(
            {
                "operation": "task_update",
                "task_id": task_id,
                "mode": mode,
                "patch": patch_document,
            }
        )
        now = now_utc or datetime.now(timezone.utc).replace(microsecond=0)
        request = self.schedule_store.reserve_product_task_update(
            task_id=task_id,
            principal_kind="user",
            principal_id=actor,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            allocate_schedule_version=schedule_mode,
            now_utc=now,
        )
        if request["state"] == "succeeded":
            result = request.get("safe_result")
            if not isinstance(result, dict):
                raise RuntimeError("persistence_error")
            return result
        if request["state"] == "failed_terminal":
            raise ValueError(
                request.get("error_code") or "requirement_product_request_terminal"
            )

        self.schedule_store.mark_product_task_update_in_progress(
            request["request_id"],
            now_utc=now,
        )

        if in_place_mode:
            return self.schedule_store.finalize_product_task_update(
                request_id=request["request_id"],
                task_id=task_id,
                actor=actor,
                name=clean_name,
                enabled=enabled,
                is_superuser=is_superuser,
                now_utc=now,
            )

        try:
            existing_draft = self.schedule_store.get_schedule_version_config(
                request["schedule_id"],
                request["schedule_version_id"],
            )
        except KeyError:
            existing_draft = None

        if existing_draft is None:
            active = self.schedule_store.get_active_schedule_config(
                request["schedule_id"]
            )
            base_config = active["config"]
            proposed = ScheduleVersionCreate(
                clean_timezone
                if clean_timezone is not None
                else base_config.timezone,
                normalized_recurrence
                if normalized_recurrence is not None
                else base_config.recurrence,
                normalized_policy
                if normalized_policy is not None
                else base_config.run_policy,
                clean_model if clean_model is not None else base_config.model,
            )
            version = self.schedule_store.create_version(
                schedule_id=request["schedule_id"],
                config=proposed,
                actor=actor,
                schedule_version_id=request["schedule_version_id"],
            )
        else:
            version = {
                "schedule_version_id": existing_draft["schedule_version_id"],
                "status": existing_draft["status"],
            }

        if (
            version.get("schedule_version_id") != request["schedule_version_id"]
            or version.get("status") != "draft"
        ):
            raise RuntimeError("persistence_error")

        return self.schedule_store.complete_product_task_update_proposal(
            request_id=request["request_id"],
            task_id=task_id,
            actor=actor,
            now_utc=now,
        )

    def activate_task_version(
        self,
        *,
        task_id: str,
        schedule_version_id: str,
        actor: str,
        is_superuser: bool,
        idempotency_key: str,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Activate one request-owned Product Schedule draft."""

        if not is_superuser:
            raise PermissionError("superuser_required")
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        if (
            not task_id
            or not schedule_version_id
            or not actor
            or len(actor) > 128
            or not idempotency_key
        ):
            raise ValueError("requirement_product_request_invalid")

        request_sha256 = canonical_sha256(
            {
                "operation": "task_version_activate",
                "task_id": task_id,
                "schedule_version_id": schedule_version_id,
            }
        )
        now = now_utc or datetime.now(timezone.utc).replace(microsecond=0)
        request = self.schedule_store.reserve_product_task_version_activation(
            task_id=task_id,
            schedule_version_id=schedule_version_id,
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
            return result
        if request["state"] == "failed_terminal":
            raise ValueError(
                request.get("error_code") or "requirement_product_request_terminal"
            )

        self.schedule_store.mark_product_task_version_activation_in_progress(
            request["request_id"],
            now_utc=now,
        )
        return self.schedule_store.finalize_product_task_version_activation(
            request_id=request["request_id"],
            task_id=task_id,
            schedule_version_id=schedule_version_id,
            actor=actor,
            now_utc=now,
        )

    @staticmethod
    def _present_task_projection(task: dict[str, Any]) -> dict[str, Any]:
        schedule = {
            "schedule_id": task["schedule_id"],
            "name": task["schedule_name"],
            "enabled": task["schedule_enabled"],
            "active_version_id": task["schedule_active_version_id"],
            "next_run_at": task["schedule_next_run_at"],
        }
        return RequirementProductService.present_task(product_task=task, schedule=schedule)

    def get_task(self, task_id: str) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        return self._present_task_projection(
            self.schedule_store.get_product_task_projection(task_id)
        )

    def list_tasks(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        tasks = self.schedule_store.list_product_task_projections(limit=limit, offset=offset)
        return {
            "items": [self._present_task_projection(task) for task in tasks],
            "limit": limit,
            "offset": offset,
        }

    def list_task_runs(self, task_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        task = self.schedule_store.get_product_task(task_id)
        runs = self.schedule_store.list_batch_runs(
            schedule_id=task["schedule_id"], limit=limit, offset=offset
        )
        return {
            "items": [
                self.present_run(
                    product_task=task,
                    run=self.schedule_store.get_batch_run(
                        schedule_id=task["schedule_id"],
                        batch_run_id=run["batch_run_id"],
                        include_items=False,
                    ),
                )
                for run in runs
            ],
            "limit": limit,
            "offset": offset,
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        task = self.schedule_store.get_product_task_for_run(run_id)
        run = self.schedule_store.get_batch_run(
            schedule_id=task["schedule_id"], batch_run_id=run_id,
            include_items=False,
        )
        return self.present_run(product_task=task, run=run)

    def get_run_items(
        self, run_id: str, *, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        task = self.schedule_store.get_product_task_for_run(run_id)
        rows = self.schedule_store.list_batch_run_items(
            schedule_id=task["schedule_id"], batch_run_id=run_id,
            limit=limit, offset=offset,
        )
        return {
            "run_id": run_id,
            "items": [_present_run_item(item) for item in rows],
            "limit": limit,
            "offset": offset,
        }

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if self.schedule_store is None:
            raise RuntimeError("requirement_product_create_unconfigured")
        bindings = self.schedule_store.list_product_run_bindings(
            limit=limit, offset=offset
        )
        return {
            "items": [self.get_run(binding["batch_run_id"]) for binding in bindings],
            "limit": limit,
            "offset": offset,
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

        result = {
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
            "links": {
                "self": _safe_link("v1", "requirement-runs", run_id),
                "items": _safe_link("v1", "requirement-runs", run_id, "items"),
                "artifacts": _safe_link("v1", "requirement-runs", run_id, "artifacts"),
            },
        }
        if "items" in run:
            result["items"] = presented_items
        return result
