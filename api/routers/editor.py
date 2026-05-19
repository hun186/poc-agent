# api/routers/editor.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.es import es_client
from api.services.auth_store import AUTH_STORE, AuthUser, create_token, parse_token
from api.services.editor_audit import append_audit_event, diff_values
from api.services.editor_form_config import get_editor_schema, public_editor_form_config

router = APIRouter(tags=["editor"])


class AuthPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class ApprovePayload(BaseModel):
    role: str = Field(...)


class SaveDocumentPayload(BaseModel):
    index: str = Field(..., min_length=1)
    id: str = Field(..., min_length=1)
    source: dict[str, Any]


def _static_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "static" / filename


@router.get("/editor", include_in_schema=False)
def editor_page() -> FileResponse:
    return FileResponse(_static_path("editor.html"))


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="請先登入。")
    return authorization.split(" ", 1)[1].strip()


def current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    payload = parse_token(_bearer_token(authorization))
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已失效，請重新登入。")
    username = str(payload.get("sub") or "")
    stored = AUTH_STORE.get_user(username)
    if not stored or stored.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="帳號尚未啟用。")
    return AuthUser(username=username, role=str(stored.get("role") or "user"), status="active")


def require_superuser(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "superuser":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要超級使用者權限。")
    return user


@router.post("/v1/auth/register")
def register(payload: AuthPayload) -> dict[str, Any]:
    try:
        user = AUTH_STORE.register(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user, "message": "帳號已建立，狀態為 pending；請等待超級使用者審核。"}


@router.post("/v1/auth/login")
def login(payload: AuthPayload) -> dict[str, Any]:
    user = AUTH_STORE.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="帳號或密碼錯誤。")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"帳號狀態為 {user.status}，尚不可使用。")
    return {"access_token": create_token(user), "token_type": "bearer", "user": user.__dict__}


@router.get("/v1/auth/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"user": user.__dict__}


@router.get("/v1/auth/users")
def list_users(_: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"users": AUTH_STORE.list_users()}


@router.post("/v1/auth/users/{username}/approve")
def approve_user(username: str, payload: ApprovePayload, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        approved = AUTH_STORE.approve_user(username, payload.role, approved_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": approved}


@router.post("/v1/auth/users/{username}/reject")
def reject_user(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        rejected = AUTH_STORE.reject_user(username, rejected_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user": rejected}


def _current_indexes() -> list[str]:
    es_client.init_index_cache(live_check=True, force=True)
    return list(es_client.ALL_INDEXES)


def _ensure_allowed_index(index: str) -> None:
    indexes = _current_indexes()
    if index not in indexes:
        raise HTTPException(status_code=400, detail=f"不允許或不存在的 index：{index}")


@router.get("/v1/editor/indexes")
def list_indexes(_: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"indexes": _current_indexes(), "default_index": es_client.ES_INDEX_DEFAULT}


@router.get("/v1/editor/form-config")
def editor_form_config(
    index: str | None = Query(None, description="用 index 選擇對應表單 schema"),
    schema: str | None = Query(None, description="明確指定 schema 名稱"),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    try:
        return public_editor_form_config(index=index, schema_name=schema)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讀取表單設定失敗：{exc}") from exc


@router.get("/v1/editor/search")
def search_documents(
    index: str = Query(..., description="要查詢的 Elasticsearch index"),
    q: str = Query("", description="關鍵字；空白時列出最近文件"),
    size: int = Query(10, ge=1, le=50),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    _ensure_allowed_index(index)
    schema = get_editor_schema(index=index)
    query: dict[str, Any]
    if q.strip():
        query = {
            "simple_query_string": {
                "query": q.strip(),
                "fields": schema.get("search_fields") or ["title^3", "subject^3", "uuid^2", "content", "full_text", "rawInfo.content"],
                "default_operator": "and",
            }
        }
    else:
        query = {"match_all": {}}

    res = es_client.get_es().search(
        index=index,
        body={
            "size": size,
            "query": query,
            "sort": ["_score"],
            "_source": schema.get("search_source_fields") or ["uuid", "title", "subject", "communication.subject", "rawInfo.title", "rawInfo.date"],
        },
    )
    body = es_client._unwrap_es(res)
    hits = []
    for hit in body.get("hits", {}).get("hits", []) or []:
        src = hit.get("_source") or {}
        hits.append({
            "id": hit.get("_id"),
            "index": hit.get("_index"),
            "score": hit.get("_score"),
            "source": src,
        })
    return {"hits": hits}


@router.get("/v1/editor/doc")
def get_document(
    index: str = Query(...),
    id: str = Query(...),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    _ensure_allowed_index(index)
    try:
        got = es_client.get_es().get(index=index, id=id, _source=True)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="文件不存在或無法讀取。") from exc
    body = es_client._unwrap_es(got)
    return {"index": body.get("_index", index), "id": body.get("_id", id), "source": body.get("_source") or {}}


@router.put("/v1/editor/doc")
def save_document(payload: SaveDocumentPayload, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    _ensure_allowed_index(payload.index)
    if any(k.startswith("_") for k in payload.source.keys()):
        raise HTTPException(status_code=400, detail="source 不可包含 _ 開頭的 Elasticsearch metadata 欄位。")
    es = es_client.get_es()
    before_source: dict[str, Any] = {}
    try:
        before = es.get(index=payload.index, id=payload.id, _source=True)
        before_body = es_client._unwrap_es(before)
        before_source = before_body.get("_source") or {}
    except Exception:
        before_source = {}

    changes = diff_values(before_source, payload.source)
    if not changes:
        return {"ok": True, "result": "noop", "index": payload.index, "id": payload.id, "updated_by": user.username, "changes": []}

    try:
        res = es.index(
            index=payload.index,
            id=payload.id,
            document=payload.source,
            refresh="wait_for",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"寫入 Elasticsearch 失敗：{exc}") from exc
    body = es_client._unwrap_es(res)
    append_audit_event({
        "action": "editor.save_document",
        "username": user.username,
        "role": user.role,
        "index": payload.index,
        "id": payload.id,
        "result": body.get("result"),
        "changed_paths": [item.get("path") for item in changes],
        "changes": changes,
    })
    return {"ok": True, "result": body.get("result"), "index": payload.index, "id": payload.id, "updated_by": user.username, "changed_paths": [item.get("path") for item in changes]}
