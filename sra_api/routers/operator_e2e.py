from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response

from api.routers.editor_dependencies import require_superuser
from api.services.auth_store import AuthUser
from sra_api.routers.requirement_schedules import schedule_service
from sra_api.services.requirement_e2e_runtime_evidence import (
    ArtifactEvidenceError, configured_published_artifact, configured_runtime_evidence,
)

router = APIRouter(prefix="/v1/operator-e2e", tags=["operator-e2e"])


@router.get("/runtime-evidence")
def runtime_evidence(
    verification: Literal["release", "functional"] = "release",
    user: AuthUser = Depends(require_superuser),
) -> dict:
    """Return bounded verified facts; never paths, process details, or secrets."""
    try: return configured_runtime_evidence(Path(__file__).resolve().parents[2], verification)
    except RuntimeError as exc: raise HTTPException(503, detail={"code": str(exc)}) from exc


@router.get("/batches/{batch_run_id}/items/{run_item_id}/artifact")
def published_artifact(
    batch_run_id: str,
    run_item_id: str,
    user: AuthUser = Depends(require_superuser),
    service=Depends(schedule_service),
) -> Response:
    """Download the exact durable Handoff-published artifact after fail-closed validation."""
    try:
        data = configured_published_artifact(service.store, batch_run_id, run_item_id)
    except ArtifactEvidenceError as exc:
        code = str(exc)
        status = 404 if code == "artifact_missing" else 409 if code.endswith("mismatch") else 422
        raise HTTPException(status, detail={"code": code}) from exc
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="requirement-artifact.docx"'},
    )
