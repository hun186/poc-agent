from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from api.routers.editor_dependencies import require_superuser
from api.services.auth_support import AuthUser
import api.security.service_key_store as store_module
from api.services.editor_audit import append_audit_event

router = APIRouter(prefix="/v1/auth/service-keys", tags=["auth"])
class CreateKey(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str]
    expires_at: str | None = None

@router.post("")
def create_key(payload: CreateKey, user: AuthUser = Depends(require_superuser)):
    try: item, raw = store_module.SERVICE_KEY_STORE.create(payload.name, payload.scopes, user.username, payload.expires_at)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    append_audit_event({
        "action": "security.service_key_created", "username": user.username,
        "key_id": item["key_id"], "name": item["name"], "scopes": item["scopes"],
    })
    return {**item, "key": raw}

@router.get("")
def list_keys(user: AuthUser = Depends(require_superuser)):
    return {"items": store_module.SERVICE_KEY_STORE.list_keys()}

@router.post("/{key_id}/revoke")
def revoke_key(key_id: str, user: AuthUser = Depends(require_superuser)):
    try: item = store_module.SERVICE_KEY_STORE.revoke(key_id, user.username)
    except KeyError as exc: raise HTTPException(404, "Service key not found") from exc
    append_audit_event({
        "action": "security.service_key_revoked", "username": user.username,
        "key_id": item["key_id"], "name": item["name"], "scopes": item["scopes"],
    })
    return item
