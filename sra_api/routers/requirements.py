from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from api.routers.editor_dependencies import authorize_role, current_user, require_db_operator, require_superuser
from api.services.auth_store import ROLE_SUPERUSER, AuthUser
from api.services.editor_audit import append_audit_event
from .requirement_models import ProfileCreate, ProfilePatch, ProfileVersionCreate, SourceCreate, SourcePatch

router = APIRouter(tags=["requirements"])


def requirement_service(request: Request):
    service = getattr(request.app.state, "requirement_import_service", None)
    if service is None: raise HTTPException(status_code=503, detail={"code": "requirement_pipeline_disabled"})
    return service


def _error(exc: Exception) -> HTTPException:
    code = str(exc.args[0] if exc.args else exc).split(":", 1)[0]
    if isinstance(exc, KeyError): status = 404
    elif code == "source_path_outside_allowed_root": status = 403
    elif code in {"stale_source_version", "source_version_anomaly", "requirement_product_owned_source"}: status = 409
    elif code in {"source_unavailable", "sql_read_error"}: status = 503
    elif code == "persistence_error": status = 500
    elif isinstance(exc, (ValueError, PermissionError, FileNotFoundError)): status = 400
    else:
        status, code = 500, "persistence_error"
    return HTTPException(status_code=status, detail={"code": code})


def _audit(action: str, user: AuthUser, **values: Any) -> None:
    append_audit_event({"action": action, "username": user.username, **values})


def _require_activation_privilege(user: AuthUser, resource: str) -> None:
    authorize_role(
        user,
        ROLE_SUPERUSER,
        f"requirement_{resource}_enablement",
        f"Only a superuser may change {resource} enablement",
    )


@router.get("/v1/requirement-sources")
def list_sources(service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return {"items": service.store.list_sources()}
    except Exception as exc: raise _error(exc) from exc
@router.get("/v1/requirement-sources/{source_id}")
def get_source(source_id: str, service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return service.store.get_source(source_id)
    except Exception as exc: raise _error(exc) from exc
@router.post("/v1/requirement-sources", status_code=201)
def create_source(payload: SourceCreate, service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    if payload.enabled: _require_activation_privilege(user, "source")
    try: result = service.store.create_source(**payload.model_dump(mode="json"), actor=user.username)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.source.created", user, source_id=result["source_id"]); return result
@router.patch("/v1/requirement-sources/{source_id}")
def patch_source(source_id: str, payload: SourcePatch, service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    if payload.enabled is not None: _require_activation_privilege(user, "source")
    try: result = service.store.guarded_patch_source(source_id, user.username, **payload.model_dump(exclude_none=True, mode="json"))
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.source.updated", user, source_id=source_id); return result

@router.get("/v1/requirement-import-profiles")
def list_profiles(service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return {"items": service.store.list_profiles()}
    except Exception as exc: raise _error(exc) from exc
@router.get("/v1/requirement-import-profiles/{profile_id}")
def get_profile(profile_id: str, service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return service.store.get_profile(profile_id)
    except Exception as exc: raise _error(exc) from exc
@router.post("/v1/requirement-import-profiles", status_code=201)
def create_profile(payload: ProfileCreate, service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    if payload.enabled: _require_activation_privilege(user, "profile")
    try: result = service.store.create_profile(**payload.model_dump(), actor=user.username)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.profile.created", user, profile_id=result["profile_id"]); return result
@router.patch("/v1/requirement-import-profiles/{profile_id}")
def patch_profile(profile_id: str, payload: ProfilePatch, service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    if payload.enabled is not None: _require_activation_privilege(user, "profile")
    try: result = service.store.patch_profile(profile_id, user.username, **payload.model_dump(exclude_none=True))
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.profile.updated", user, profile_id=profile_id); return result
@router.post("/v1/requirement-import-profiles/{profile_id}/versions", status_code=201)
def create_version(profile_id: str, payload: ProfileVersionCreate, service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    try: result = service.store.create_profile_version(profile_id, payload.profile.model_dump(mode="json"), user.username)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.profile.version_created", user, profile_id=profile_id, profile_version_id=result["profile_version_id"]); return {k: v for k, v in result.items() if k != "profile"}
@router.post("/v1/requirement-import-profiles/{profile_id}/versions/{version_number}/approve")
def approve_version(profile_id: str, version_number: int, service=Depends(requirement_service), user: AuthUser = Depends(require_superuser)):
    try: result = service.store.approve_profile_version(profile_id, version_number, user.username)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.profile.version_approved", user, profile_id=profile_id, profile_version_id=result["profile_version_id"]); return {k: v for k, v in result.items() if k != "profile"}

async def _upload(file: UploadFile | None) -> tuple[bytes | None, str | None]: return (await file.read(), file.filename) if file else (None, None)
@router.post("/v1/requirement-sources/{source_id}/preview")
async def preview(source_id: str, profile_version_id: str | None = Query(None), file: UploadFile | None = File(None), service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    content, filename = await _upload(file)
    try: result = service.preview(source_id, profile_version_id=profile_version_id, upload_bytes=content, upload_filename=filename)
    except Exception as exc: raise _error(exc) from exc
    _audit("requirement.import.previewed", user, source_id=source_id, accepted_count=result["accepted_count"], rejected_count=result["rejected_count"]); return result
@router.post("/v1/requirement-sources/{source_id}/import")
async def commit(source_id: str, file: UploadFile | None = File(None), service=Depends(requirement_service), user: AuthUser = Depends(require_db_operator)):
    content, filename = await _upload(file)
    try: result = service.commit_low_level(source_id, actor=user.username, upload_bytes=content, upload_filename=filename)
    except Exception as exc:
        _audit("requirement.import.failed", user, source_id=source_id, reason_code=str(exc).split(":", 1)[0]); raise _error(exc) from exc
    _audit("requirement.import.committed" if result["status"] == "committed" else "requirement.import.failed", user, source_id=source_id, import_run_id=result["import_run_id"]); return result

@router.get("/v1/requirement-import-runs/{run_id}")
def get_run(run_id: str, service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return service.store.get_import_run(run_id)
    except Exception as exc: raise _error(exc) from exc
@router.get("/v1/requirement-sets")
def sets(service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return {"items": service.store.list_requirement_sets()}
    except Exception as exc: raise _error(exc) from exc
@router.get("/v1/requirement-sets/{set_id}/snapshots")
def snapshots(set_id: str, service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return {"items": service.store.list_snapshots(set_id)}
    except Exception as exc: raise _error(exc) from exc
@router.get("/v1/requirement-snapshots/{snapshot_id}")
def snapshot(snapshot_id: str, service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return service.store.get_snapshot(snapshot_id)
    except Exception as exc: raise _error(exc) from exc
@router.get("/v1/requirement-snapshots/{snapshot_id}/items")
def snapshot_items(snapshot_id: str, service=Depends(requirement_service), user: AuthUser = Depends(current_user)):
    try: return {"items": service.store.list_snapshot_items(snapshot_id)}
    except Exception as exc: raise _error(exc) from exc
