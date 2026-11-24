"""Explicit authenticated deep report admission, disabled until composed at startup."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.routers.report_jobs import _browser_status_url
from api.security.models import AuthPrincipal
from api.security.principal import require_scopes
from api.security.scopes import (
    DOCUMENT_READ, MODEL_INVOKE, REPORT_JOB_CREATE, REPORT_JOB_READ, REPORT_JOB_DOWNLOAD,
)
from api.services.report_job_store import IdempotencyConflict, ReportJobAdmissionFull
from api.services.sraf_deep_scope_policy import DeepScopeDenied, DeepQuestionUnsupported
from api.services.sraf_chat_deep_turn import resolve_deep_admission, DeepRuntimeUnavailable

router = APIRouter(prefix="/v1/report/jobs", tags=["report jobs"])


class DeepReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4096)
    filename: str | None = Field(default=None, max_length=180)


@router.post("/deep", status_code=202, responses={
    403: {"description": "Deep report denied"},
    409: {"description": "Idempotency conflict"},
    422: {"description": "Unsupported deep question"},
    429: {"description": "Queue full"},
    503: {"description": "Deep reports unavailable"},
})
def submit_deep_report(
    payload: DeepReportCreate, request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthPrincipal = Depends(require_scopes(
        DOCUMENT_READ, MODEL_INVOKE, REPORT_JOB_CREATE, REPORT_JOB_READ, REPORT_JOB_DOWNLOAD)),
):
    if principal.kind != "user":
        raise HTTPException(403, "Deep reports require an authenticated user")
    if (type(idempotency_key) is not str or not 1 <= len(idempotency_key) <= 128
            or idempotency_key != idempotency_key.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in idempotency_key)):
        raise HTTPException(400, "Valid Idempotency-Key required")
    try:
        policy, store = resolve_deep_admission(request.app.state)
    except DeepRuntimeUnavailable:
        raise HTTPException(503, "Deep reports unavailable") from None
    try:
        job, _ = policy.admit(store, principal=principal, prompt=payload.prompt,
                              idempotency_key=idempotency_key, filename=payload.filename)
    except DeepScopeDenied:
        raise HTTPException(403, "Deep report denied") from None
    except DeepQuestionUnsupported:
        raise HTTPException(422, "Unsupported deep question") from None
    except IdempotencyConflict:
        raise HTTPException(409, "Idempotency conflict") from None
    except ReportJobAdmissionFull:
        raise HTTPException(429, "Report job queue is full", headers={"Retry-After": "30"}) from None
    except Exception:
        raise HTTPException(503, "Deep reports unavailable") from None
    return JSONResponse({
        "job_id": job.job_id, "status": job.status, "execution_mode": "adaptive_multiround",
        "status_url": f"/v1/report/jobs/{job.job_id}",
        "download_url": f"/v1/report/jobs/{job.job_id}/word",
        "browser_status_url": _browser_status_url(job.job_id),
    }, status_code=202, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
