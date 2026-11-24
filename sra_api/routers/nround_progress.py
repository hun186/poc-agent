"""Authenticated, exact-owner read-only N-round progress."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.security.models import AuthPrincipal
from api.security.principal import require_scopes
from api.security.scopes import REPORT_JOB_READ
from api.services.sraf_deep_scope_policy import binding_for_principal
from api.services.sraf_nround_owned_progress import (
    NroundOwnedProgressError, get_owned_nround_progress,
)
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore

router = APIRouter(prefix="/v1/report/jobs", tags=["report jobs"])
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@router.get("/{job_id}/nround-progress", responses={
    404: {"description": "Not found"},
    503: {"description": "Progress unavailable"},
})
def owned_nround_progress(
    job_id: str, request: Request,
    principal: AuthPrincipal = Depends(require_scopes(REPORT_JOB_READ)),
):
    """Never grant cross-owner access, even with Report Job admin scope."""
    store = request.app.state.report_job_store
    try:
        result = get_owned_nround_progress(
            report_store=store, checkpoint_store=NroundCheckpointStore(store.db_path),
            job_id=job_id, owner_kind=principal.kind, owner_id=principal.subject,
            deep_owner_binding=binding_for_principal(principal),
        )
    except NroundOwnedProgressError:
        return JSONResponse({"detail": "Report progress unavailable"}, status_code=503,
                            headers=_HEADERS)
    if result is None:
        return JSONResponse({"detail": "Report progress not found"}, status_code=404,
                            headers=_HEADERS)
    return JSONResponse(result, headers=_HEADERS)
