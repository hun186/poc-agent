from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from api.routers.editor_dependencies import authorize_role, current_user, require_db_operator, require_superuser
from api.services.auth_store import ROLE_DB_OPERATOR, ROLE_SUPERUSER, AuthUser
from api.services.editor_audit import append_audit_event
from requirement_scheduler.models import RecurrenceSpec, RunPolicy, ScheduleVersionCreate

router = APIRouter(tags=["requirement-schedules"])


class ScheduleCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    requirement_set_id: str = Field(min_length=1, max_length=64)


class SchedulePatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=240)
    enabled: bool | None = None


class ScheduleVersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str
    recurrence: dict[str, Any]
    run_policy: RunPolicy
    model: str = Field(min_length=1, max_length=240)


def schedule_service(request: Request):
    service = getattr(request.app.state, "requirement_schedule_service", None)
    if service is None: raise HTTPException(503, detail={"code": "requirement_scheduler_disabled"})
    return service


def _error(exc: Exception) -> HTTPException:
    code = str(exc.args[0] if exc.args else exc).strip("'").split(":", 1)[0]
    if isinstance(exc, KeyError): status = 404
    elif code in {"schedule_enabled", "schedule_version_not_approved", "schedule_version_conflict"}: status = 409
    elif code == "persistence_error": status = 500
    elif isinstance(exc, ValueError): status = 400
    else: status, code = 500, "persistence_error"
    return HTTPException(status, detail={"code": code})


def _audit(action: str, user: AuthUser, **evidence): append_audit_event({"action": action, "username": user.username, **evidence})


@router.get("/v1/requirement-schedules")
def list_schedules(
    enabled: bool | None = None,
    requirement_set_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service=Depends(schedule_service), user: AuthUser = Depends(current_user),
):
    try:
        items = service.store.list_schedules(enabled=enabled, requirement_set_id=requirement_set_id, limit=limit, offset=offset)
        return {"items": items, "limit": limit, "offset": offset}
    except Exception as exc: raise _error(exc) from exc


@router.get("/v1/requirement-schedules/{schedule_id}")
def get_schedule(schedule_id: str, service=Depends(schedule_service), user: AuthUser = Depends(current_user)):
    try: return service.store.get_schedule(schedule_id)
    except Exception as exc: raise _error(exc) from exc


@router.post("/v1/requirement-schedules", status_code=201)
def create_schedule(payload: ScheduleCreateBody, service=Depends(schedule_service), user: AuthUser = Depends(require_db_operator)):
    try: result = service.store.create_schedule(**payload.model_dump(), actor=user.username)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement_schedule.created", user, schedule_id=result["schedule_id"]); return result


@router.patch("/v1/requirement-schedules/{schedule_id}")
def patch_schedule(schedule_id: str, payload: SchedulePatchBody, service=Depends(schedule_service), user: AuthUser = Depends(current_user)):
    authorize_role(user, ROLE_DB_OPERATOR, "requirement_schedule_mutation", "Only a database operator may change schedules")
    if payload.enabled is not None:
        authorize_role(user, ROLE_SUPERUSER, "requirement_schedule_enablement", "Only a superuser may change schedule enablement")
    try:
        result = service.store.get_schedule(schedule_id)
        if payload.name is not None: result = service.store.rename_schedule(schedule_id, payload.name, user.username)
        if payload.enabled is not None: result = service.set_enabled(schedule_id=schedule_id, enabled=payload.enabled, actor=user.username, now_utc=datetime.now(timezone.utc).replace(microsecond=0))
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement_schedule.updated", user, schedule_id=schedule_id); return result


@router.post("/v1/requirement-schedules/{schedule_id}/versions", status_code=201)
def create_version(schedule_id: str, payload: ScheduleVersionBody, service=Depends(schedule_service), user: AuthUser = Depends(require_db_operator)):
    try:
        config = ScheduleVersionCreate(payload.timezone, RecurrenceSpec.validate(payload.recurrence), payload.run_policy, payload.model)
        result = service.store.create_version(schedule_id=schedule_id, config=config, actor=user.username)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement_schedule.version_created", user, schedule_id=schedule_id, version_number=result["version_number"]); return result


@router.post("/v1/requirement-schedules/{schedule_id}/versions/{version_number}/approve")
def approve_version(schedule_id: str, version_number: int, service=Depends(schedule_service), user: AuthUser = Depends(require_superuser)):
    try: result = service.approve_version(schedule_id=schedule_id, version_number=version_number, actor=user.username, now_utc=datetime.now(timezone.utc).replace(microsecond=0))
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement_schedule.version_approved", user, schedule_id=schedule_id, version_number=version_number); return result
