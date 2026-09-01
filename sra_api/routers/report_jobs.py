from __future__ import annotations
from pathlib import Path
import zipfile
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from api.services.report_job_service import DEFAULT_REPORT_MODEL, create_job
from api.services.report_job_store import IdempotencyConflict

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
def submit(payload: ReportJobCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    try:
        job, _ = create_job(_store(request), idempotency_key=idempotency_key, **payload.model_dump())
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status, "status_url": f"/v1/report/jobs/{job.job_id}", "download_url": f"/v1/report/jobs/{job.job_id}/word"}

@router.get("/{job_id}", responses={404: {"description": "Not found"}})
def status(job_id: str, request: Request):
    job = _store(request).get(job_id)
    if not job: raise HTTPException(404, "Report job not found")
    return _view(job)

@router.get("/{job_id}/word", responses={200: {"content": {DOCX: {"schema": {"type": "string", "format": "binary"}}}}, 404: {"description": "Not found"}, 409: {"description": "Not completed"}, 500: {"description": "Artifact unavailable"}})
def download(job_id: str, request: Request):
    job = _store(request).get(job_id)
    if not job: raise HTTPException(404, "Report job not found")
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
