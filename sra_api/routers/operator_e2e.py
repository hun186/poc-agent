from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from api.routers.editor_dependencies import require_superuser
from api.services.auth_store import AuthUser
from sra_api.services.requirement_e2e_runtime_evidence import configured_runtime_evidence

router = APIRouter(prefix="/v1/operator-e2e", tags=["operator-e2e"])


@router.get("/runtime-evidence")
def runtime_evidence(user: AuthUser = Depends(require_superuser)) -> dict:
    """Return bounded verified facts; never paths, process details, or secrets."""
    try: return configured_runtime_evidence(Path(__file__).resolve().parents[2])
    except RuntimeError as exc: raise HTTPException(503, detail={"code": str(exc)}) from exc
