from __future__ import annotations
from pathlib import Path
import zipfile
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from api.services.report_job_service import DEFAULT_REPORT_MODEL, create_job
from api.services.report_job_store import IdempotencyConflict
from api.security.models import AuthPrincipal
from api.security.principal import require_scopes
from api.security.scopes import REPORT_JOB_ADMIN, REPORT_JOB_CREATE, REPORT_JOB_DOWNLOAD, REPORT_JOB_READ
from api.services.editor_audit import append_audit_event

router = APIRouter(prefix="/v1/report/jobs", tags=["report jobs"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

class ReportJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=180)
    session_id: str | None = Field(default=None, max_length=240)
    model: str = DEFAULT_REPORT_MODEL
    options: dict = Field(default_factory=dict, max_length=0)
    metadata: dict = Field(default_factory=dict)

def _store(request: Request): return request.app.state.report_job_store
def _view(job):
    result = job.to_dict()
    result.pop("prompt", None); result.pop("request_hash", None); result.pop("idempotency_key", None); result.pop("docx_basename", None)
    result["status_url"] = f"/v1/report/jobs/{job.job_id}"
    result["download_url"] = f"/v1/report/jobs/{job.job_id}/word"
    return result

@router.post("", status_code=202, responses={409: {"description": "Idempotency conflict"}})
def submit(payload: ReportJobCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"), principal: AuthPrincipal = Depends(require_scopes(REPORT_JOB_CREATE))):
    try:
        job, _ = create_job(_store(request), idempotency_key=idempotency_key, owner_kind=principal.kind, owner_id=principal.subject, **payload.model_dump())
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status, "status_url": f"/v1/report/jobs/{job.job_id}", "download_url": f"/v1/report/jobs/{job.job_id}/word"}

def _authorized(job, principal):
    return REPORT_JOB_ADMIN in principal.scopes or (job.owner_kind == principal.kind and job.owner_id == principal.subject)

def _audit_admin_cross_owner(job, principal, operation):
    if REPORT_JOB_ADMIN in principal.scopes and (job.owner_kind != principal.kind or job.owner_id != principal.subject):
        append_audit_event({
            "action": "security.report_job_admin_cross_owner_access",
            "principal_kind": principal.kind,
            "subject": principal.subject,
            "job_id": job.job_id,
            "operation": operation,
        })

def _audit_owner_mismatch(job, principal, operation):
    append_audit_event({
        "action": "security.authorization_denied",
        "reason": "job_owner_mismatch",
        "principal_kind": principal.kind,
        "subject": principal.subject,
        "job_id": job.job_id,
        "operation": operation,
    })

@router.get("/{job_id}", responses={404: {"description": "Not found"}})
def status(job_id: str, request: Request, principal: AuthPrincipal = Depends(require_scopes(REPORT_JOB_READ))):
    job = _store(request).get(job_id)
    if not job: raise HTTPException(404, "Report job not found")
    if not _authorized(job, principal):
        _audit_owner_mismatch(job, principal, "read")
        raise HTTPException(404, "Report job not found")
    _audit_admin_cross_owner(job, principal, "read")
    return _view(job)

@router.get("/{job_id}/word", responses={200: {"content": {DOCX: {"schema": {"type": "string", "format": "binary"}}}}, 404: {"description": "Not found"}, 409: {"description": "Not completed"}, 500: {"description": "Artifact unavailable"}})
def download(job_id: str, request: Request, principal: AuthPrincipal = Depends(require_scopes(REPORT_JOB_DOWNLOAD))):
    job = _store(request).get(job_id)
    if not job: raise HTTPException(404, "Report job not found")
    if not _authorized(job, principal):
        _audit_owner_mismatch(job, principal, "download")
        raise HTTPException(404, "Report job not found")
    _audit_admin_cross_owner(job, principal, "download")
    if job.status != "completed": raise HTTPException(409, f"Report job is {job.status}")
    expected = f"{job.job_id}.docx"
    if job.docx_basename != expected: raise HTTPException(500, "Completed report artifact is invalid")
    root = Path(request.app.state.report_jobs_reports_root).resolve()
    path = (root / expected).resolve()
    try:
        path.relative_to(root)
        valid = path.is_file() and zipfile.is_zipfile(path)
    except (ValueError, OSError): valid = False
    if not valid: raise HTTPException(500, "Completed report artifact is unavailable")
    return FileResponse(path, media_type=DOCX, filename=job.filename or "report.docx")
