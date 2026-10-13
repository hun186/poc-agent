"""Public read/preview Product façade over the existing Requirement authorities.

P2.1 deliberately does not expose create, update, input replacement, activation,
run triggering, artifact or service-key routes before their separate safety gates.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api.routers.editor_dependencies import current_user, require_db_operator
from api.services.auth_store import AuthUser
from data_ingestion.requirements.readers import read_json_rows

router = APIRouter(tags=["requirement-tasks"])
_MAX_INPUT_BYTES = 10 * 1024 * 1024
_MAX_DIRECT_JSON_BYTES = 1024 * 1024  # Starlette's max_part_size for form fields
_MAX_PREVIEW_TASK_METADATA_BYTES = 4096  # Two small declared fields; bound before json.loads
_ALLOWED_EXTENSIONS = (".xlsx", ".csv", ".json")

# Never echo arbitrary SQL/ODBC/adapter exceptions or file content through HTTP.
_VALIDATION_CODES = {
    "requirement_preview_input_invalid", "requirement_preview_profile_invalid",
    "requirement_preview_profile_not_approved", "requirement_preview_profile_not_active",
    "requirement_input_invalid", "source_format_invalid", "source_config_invalid",
    "source_type_invalid", "source_input_invalid", "source_file_invalid",
    "source_file_extension_invalid", "source_file_too_large",
    "requirement_preview_too_large", "requirement_preview_archive_invalid",
}
_CONFLICT_CODES = {
    "requirement_input_conflict", "requirement_idempotency_conflict",
    "requirement_task_conflict", "requirement_task_disabled",
    "requirement_task_provisioning", "requirement_product_owned_schedule",
    "requirement_product_owned_source",
}
_UNAVAILABLE_CODES = {
    "requirement_product_create_unconfigured", "requirement_preview_unconfigured",
    "requirement_dependency_unavailable",
}
_NOT_FOUND_CODES = {
    "requirement_task_not_found", "requirement_run_unavailable", "batch_run_not_found",
}


class PreviewTaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_version_id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=240)


def product_service(request: Request):
    service = getattr(request.app.state, "requirement_product_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "requirement_dependency_unavailable"})
    return service


def _error(exc: Exception) -> HTTPException:
    raw = str(exc.args[0] if exc.args else exc).strip("'").split(":", 1)[0]
    if isinstance(exc, KeyError):
        # A missing presenter/store column is a backend invariant failure, not
        # evidence that a requested Product Task or Run was absent.
        if raw in _NOT_FOUND_CODES:
            return HTTPException(404, detail={"code": raw})
        return HTTPException(500, detail={"code": "persistence_error"})
    if raw in _CONFLICT_CODES:
        return HTTPException(409, detail={"code": raw})
    if raw in _NOT_FOUND_CODES:
        return HTTPException(404, detail={"code": raw})
    if raw in _UNAVAILABLE_CODES:
        return HTTPException(503, detail={"code": "requirement_dependency_unavailable"})
    if raw in _VALIDATION_CODES:
        return HTTPException(422, detail={"code": raw})
    return HTTPException(500, detail={"code": "persistence_error"})


@router.post("/v1/requirement-task-previews")
async def preview_product_input(
    task: str = Form(...),
    file: UploadFile | None = File(None),
    requirements_json: str | None = Form(None),
    service=Depends(product_service),
    user: AuthUser = Depends(require_db_operator),
):
    try:
        try:
            # Metadata only declares profile_version_id (128 chars) and an
            # optional name (240 chars). Reject large nested JSON before
            # json.loads allocates an untrusted object graph.
            if len(task.encode("utf-8")) > _MAX_PREVIEW_TASK_METADATA_BYTES:
                raise ValueError("requirement_preview_input_invalid")
            task_data = json.loads(task)
            parsed = PreviewTaskBody.model_validate(task_data)
        except (UnicodeError, ValueError, TypeError, ValidationError) as exc:
            raise ValueError("requirement_preview_input_invalid") from exc
        if (file is None) == (requirements_json is None):
            raise ValueError("requirement_preview_input_invalid")
        if file is not None:
            filename = file.filename or ""
            if not filename.lower().endswith(_ALLOWED_EXTENSIONS):
                raise ValueError("source_file_extension_invalid")
            data = await file.read(_MAX_INPUT_BYTES + 1)
            if not data or len(data) > _MAX_INPUT_BYTES:
                raise ValueError("requirement_preview_input_invalid")
            return service.preview_input(
                profile_version_id=parsed.profile_version_id,
                upload_bytes=data,
                upload_filename=filename,
                max_rows=5000, max_result_rows=100,
            )
        assert requirements_json is not None
        try:
            direct_json_bytes = requirements_json.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("requirement_preview_input_invalid") from exc
        if not direct_json_bytes or len(direct_json_bytes) > _MAX_DIRECT_JSON_BYTES:
            raise ValueError("requirement_preview_input_invalid")
        try:
            # Use the exact same bounded decoder as JSON file uploads before
            # materializing any nested objects from the direct form field.
            requirements, _ = read_json_rows(direct_json_bytes, max_rows=5000)
        except ValueError as exc:
            if str(exc) == "requirement_preview_too_large":
                raise
            raise ValueError("requirement_preview_input_invalid") from exc
        return service.preview_input(
            profile_version_id=parsed.profile_version_id,
            requirements=requirements,
            max_rows=5000, max_result_rows=100,
        )
    except Exception as exc:
        raise _error(exc) from exc
    finally:
        if file is not None:
            await file.close()


@router.get("/v1/requirement-tasks")
def list_product_tasks(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service=Depends(product_service),
    user: AuthUser = Depends(current_user),
):
    try:
        return service.list_tasks(limit=limit, offset=offset)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/v1/requirement-tasks/{task_id}")
def get_product_task(
    task_id: str,
    service=Depends(product_service),
    user: AuthUser = Depends(current_user),
):
    try:
        return service.get_task(task_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/v1/requirement-tasks/{task_id}/runs")
def list_product_task_runs(
    task_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service=Depends(product_service),
    user: AuthUser = Depends(current_user),
):
    try:
        return service.list_task_runs(task_id, limit=limit, offset=offset)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/v1/requirement-runs")
def list_product_runs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service=Depends(product_service),
    user: AuthUser = Depends(current_user),
):
    try:
        return service.list_runs(limit=limit, offset=offset)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/v1/requirement-runs/{run_id}")
def get_product_run(
    run_id: str,
    service=Depends(product_service),
    user: AuthUser = Depends(current_user),
):
    try:
        return service.get_run(run_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/v1/requirement-runs/{run_id}/items")
def get_product_run_items(
    run_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service=Depends(product_service),
    user: AuthUser = Depends(current_user),
):
    try:
        return service.get_run_items(run_id, limit=limit, offset=offset)
    except Exception as exc:
        raise _error(exc) from exc
