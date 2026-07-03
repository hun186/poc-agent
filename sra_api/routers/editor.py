# api/routers/editor.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from agent.es import es_client
from api.routers.editor_auth import router as auth_router
from api.routers import editor_usage as editor_usage_routes
from api.routers.editor_usage import router as usage_router
from api.routers.editor_dependencies import current_user, require_data_editor, static_path
from api.routers.editor_models import DeleteDocumentsPayload, SaveDocumentPayload
from api.services.auth_store import AuthUser
from api.services.editor_audit import append_audit_event, diff_values
from api.services.editor_files import extract_text_from_upload
from api.services.editor_form_config import get_editor_schema, public_editor_form_config
from api.services.editor_index_utils import (
    coerce_source_by_mapping,
    current_indexes,
    ensure_allowed_index,
    get_index_field_paths,
    get_index_field_type_map,
    get_index_object_paths,
    make_uuid_from_source,
    normalize_sra_source_shapes,
    pick_source_uuid,
    utc_now_iso_z,
)

router = APIRouter(tags=["editor"])
router.include_router(auth_router)
router.include_router(usage_router)

# Compatibility wrappers for tests and scripts that import these route handlers
# from api.routers.editor directly. The real route registrations live in
# api.routers.editor_usage after the file split.
load_audit_records = editor_usage_routes.load_audit_records


def usage_stats(*args: Any, **kwargs: Any) -> dict[str, Any]:
    editor_usage_routes.load_audit_records = load_audit_records
    return editor_usage_routes.usage_stats(*args, **kwargs)


def list_audit_logs(*args: Any, **kwargs: Any) -> dict[str, Any]:
    editor_usage_routes.load_audit_records = load_audit_records
    return editor_usage_routes.list_audit_logs(*args, **kwargs)


def _ensure_mock_preview_es_access(user: AuthUser) -> None:
    if user.mock_preview and not es_client.using_mock_es():
        raise HTTPException(
            status_code=403,
            detail="Vercel mock preview 帳號只能讀取 mock Elasticsearch 資料。",
        )


EDITOR_STATIC_ASSETS: dict[str, str] = {
    "audit_tools.js": "application/javascript",
    "editor.css": "text/css",
    "editor_core.js": "application/javascript",
    "editor_form.js": "application/javascript",
    "editor_auth_nav.js": "application/javascript",
    "editor_stats.js": "application/javascript",
    "editor_audit.js": "application/javascript",
    "editor_documents.js": "application/javascript",
    "editor_bootstrap.js": "application/javascript",
    "excel_to_sql_dashboard_app.js": "application/javascript",
    "excel_to_sql_import_records.js": "application/javascript",
    "excel_to_sql_source_editor_app.js": "application/javascript",
    "excel_to_sql_source_stats_app.js": "application/javascript",
    "excel_to_sql_import_center.html": "text/html",
}

EDITOR_STATIC_ASSET_ALIASES: dict[str, str] = {
    # Keep old on-premise/cached HTML references working without restoring the
    # physical same-stem file that Vercel rejects.
    "excel_to_sql_dashboard.js": "excel_to_sql_dashboard_app.js",
}



@router.get("/editor", include_in_schema=False)
def editor_page() -> FileResponse:
    return FileResponse(static_path("editor.html"))


@router.get("/static/audit_tools.js", include_in_schema=False)
def audit_tools_script() -> FileResponse:
    return FileResponse(static_path("audit_tools.js"), media_type="application/javascript")


@router.get("/static/{filename}", include_in_schema=False)
def editor_static_asset(filename: str) -> FileResponse:
    asset_filename = EDITOR_STATIC_ASSET_ALIASES.get(filename, filename)
    media_type = EDITOR_STATIC_ASSETS.get(asset_filename)
    if not media_type:
        raise HTTPException(status_code=404, detail="Static asset not found")
    path = static_path(asset_filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Static asset not found")
    return FileResponse(path, media_type=media_type)


@router.post("/v1/editor/extract-text")
async def extract_text_from_file(
    file: UploadFile = File(...),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    content = await file.read()
    text = extract_text_from_upload(file.filename or "", content)
    return {"filename": file.filename, "text": text}


@router.get("/v1/editor/indexes")
def list_indexes(_: AuthUser = Depends(current_user)) -> dict[str, Any]:
    indexes = current_indexes()
    _ensure_mock_preview_es_access(_)
    default_index = es_client.ES_INDEX_DEFAULT or (indexes[0] if indexes else "")
    return {
        "indexes": indexes,
        "default_index": default_index,
        "mock_mode": es_client.using_mock_es(),
    }


@router.get("/v1/editor/form-config")
def editor_form_config(
    index: str | None = Query(None, description="用 index 選擇對應表單 schema"),
    schema: str | None = Query(None, description="明確指定 schema 名稱"),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    _ensure_mock_preview_es_access(user)
    try:
        return public_editor_form_config(index=index, schema_name=schema)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讀取表單設定失敗：{exc}") from exc


@router.get("/v1/editor/search")
def search_documents(
    index: str = Query(..., description="要查詢的 Elasticsearch index"),
    q: str = Query("", description="關鍵字；空白時列出最近文件"),
    size: int = Query(20, ge=1, le=200),
    page: int = Query(1, ge=1),
    start_ts: str = Query("", description="起始時間（ISO8601）"),
    end_ts: str = Query("", description="結束時間（ISO8601）"),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    ensure_allowed_index(index)
    _ensure_mock_preview_es_access(user)
    schema = get_editor_schema(index=index)
    filters: list[dict[str, Any]] = []
    date_field = str(schema.get("search_date_field") or "importDT")
    mapping_field_paths, mapping_ok = get_index_field_paths(index)
    warnings: list[str] = []
    if not mapping_ok:
        warnings.append("無法讀取 index mapping，已略過日期欄位存在性檢查。")
    elif date_field not in mapping_field_paths:
        warnings.append(f"日期篩選欄位 `{date_field}` 不存在於 index mapping；套用日期區間可能查不到結果。")
    range_filter: dict[str, str] = {}
    if start_ts.strip():
        range_filter["gte"] = start_ts.strip()
    if end_ts.strip():
        range_filter["lte"] = end_ts.strip()
    if range_filter:
        filters.append({"range": {date_field: range_filter}})

    text_query: dict[str, Any]
    if q.strip():
        text_query = {
            "simple_query_string": {
                "query": q.strip(),
                "fields": schema.get("search_fields") or ["title^3", "subject^3", "uuid^2", "content", "full_text", "rawInfo.content"],
                "default_operator": "and",
            }
        }
    else:
        text_query = {"match_all": {}}

    query: dict[str, Any] = {"bool": {"must": [text_query]}}
    if filters:
        query["bool"]["filter"] = filters

    offset = (page - 1) * size
    res = es_client.get_es().search(
        index=index,
        body={
            "from": offset,
            "size": size,
            "track_total_hits": True,
            "query": query,
            "sort": [
                {date_field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}},
                {"_score": {"order": "desc"}},
            ],
            "_source": schema.get("search_source_fields") or ["uuid", "title", "subject", "communication.subject", "rawInfo.title", "rawInfo.date", "importDT"],
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
    total_obj = (body.get("hits", {}) or {}).get("total", 0)
    total = total_obj.get("value", 0) if isinstance(total_obj, dict) else int(total_obj or 0)
    return {
        "hits": hits,
        "total": total,
        "size": size,
        "page": page,
        "has_more": (offset + len(hits)) < total,
        "warnings": warnings
        + (["目前使用 Vercel mock Elasticsearch 測試資料，未連線正式 ES。"] if es_client.using_mock_es() else []),
        "mock_mode": es_client.using_mock_es(),
    }


@router.get("/v1/editor/doc")
def get_document(
    index: str = Query(...),
    id: str = Query(...),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    ensure_allowed_index(index)
    _ensure_mock_preview_es_access(user)
    schema = get_editor_schema(index=index)
    try:
        got = es_client.get_es().get(index=index, id=id, _source=True)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="文件不存在或無法讀取。") from exc
    body = es_client._unwrap_es(got)
    mapping_field_paths, mapping_ok = get_index_field_paths(index)
    expected_paths: set[str] = set()
    for sec in (schema.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        sec_path = sec.get("path")
        if isinstance(sec_path, str) and sec_path.strip():
            expected_paths.add(sec_path.strip())
        for field in (sec.get("fields") or []):
            if not isinstance(field, dict):
                continue
            p = field.get("path")
            if isinstance(p, str) and p.strip():
                if isinstance(sec_path, str) and sec.get("type") == "array" and "." not in p:
                    expected_paths.add(f"{sec_path.strip()}.{p.strip()}")
                else:
                    expected_paths.add(p.strip())
    missing_paths = sorted([p for p in expected_paths if p not in mapping_field_paths]) if mapping_ok else []
    warnings: list[str] = []
    if not mapping_ok:
        warnings.append("無法讀取 index mapping，已略過 schema 欄位存在性檢查。")
    elif missing_paths:
        preview = ", ".join(missing_paths[:20])
        suffix = " ..." if len(missing_paths) > 20 else ""
        warnings.append(f"Schema 欄位有 {len(missing_paths)} 個不存在於 index mapping：{preview}{suffix}")
    return {
        "index": body.get("_index", index),
        "id": body.get("_id", id),
        "source": body.get("_source") or {},
        "warnings": warnings,
    }


@router.put("/v1/editor/doc")
def save_document(payload: SaveDocumentPayload, user: AuthUser = Depends(require_data_editor)) -> dict[str, Any]:
    ensure_allowed_index(payload.index)
    is_create = not (payload.id and payload.id.strip())
    if any(k.startswith("_") for k in payload.source.keys()):
        raise HTTPException(status_code=400, detail="source 不可包含 _ 開頭的 Elasticsearch metadata 欄位。")
    es = es_client.get_es()
    before_source: dict[str, Any] = {}
    import_dt = payload.source.get("importDT")
    if is_create and not (isinstance(import_dt, str) and import_dt.strip()):
        payload.source["importDT"] = utc_now_iso_z()
    doc_id = payload.id.strip() if isinstance(payload.id, str) and payload.id.strip() else None
    if not doc_id:
        doc_id = pick_source_uuid(payload.source)
    if not doc_id:
        doc_id = make_uuid_from_source(payload.source)
        payload.source["uuid"] = doc_id

    if doc_id:
        try:
            before = es.get(index=payload.index, id=doc_id, _source=True)
            before_body = es_client._unwrap_es(before)
            before_source = before_body.get("_source") or {}
        except Exception:
            before_source = {}

    field_type_map = get_index_field_type_map(payload.index, ["multidim_event_json", "route_audit_json"])
    normalized_source = normalize_sra_source_shapes(payload.source, field_type_map)
    object_paths = get_index_object_paths(payload.index)
    source_to_save = coerce_source_by_mapping(normalized_source, object_paths)
    changes = diff_values(before_source, source_to_save)
    if not changes:
        return {
            "ok": True,
            "result": "noop",
            "index": payload.index,
            "id": doc_id,
            "updated_by": user.username,
            "changes": [],
            "message": "No changes detected; existing document loaded.",
            "mode": "edit_existing",
        }

    try:
        res = es.index(
            index=payload.index,
            id=doc_id,
            document=source_to_save,
            refresh="wait_for",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"寫入 Elasticsearch 失敗：{exc}") from exc
    body = es_client._unwrap_es(res)
    final_id = body.get("_id") or doc_id or ""
    append_audit_event({
        "action": "editor.create_document" if is_create else "editor.save_document",
        "username": user.username,
        "role": user.role,
        "index": payload.index,
        "id": final_id,
        "result": body.get("result"),
        "changed_paths": [item.get("path") for item in changes],
        "changes": changes,
    })
    return {"ok": True, "result": body.get("result"), "index": payload.index, "id": final_id, "updated_by": user.username, "changed_paths": [item.get("path") for item in changes]}


@router.delete("/v1/editor/doc")
def delete_document(
    index: str = Query(...),
    id: str = Query(...),
    user: AuthUser = Depends(require_data_editor),
) -> dict[str, Any]:
    ensure_allowed_index(index)
    try:
        res = es_client.get_es().delete(index=index, id=id, refresh="wait_for")
    except Exception as exc:
        raise HTTPException(status_code=404, detail="文件不存在或無法刪除。") from exc
    body = es_client._unwrap_es(res)
    append_audit_event({
        "action": "editor.delete_document",
        "username": user.username,
        "role": user.role,
        "index": index,
        "id": id,
        "result": body.get("result"),
        "changed_paths": [],
        "changes": [],
    })
    return {"ok": True, "index": index, "id": id, "result": body.get("result")}


@router.delete("/v1/editor/docs")
def delete_documents(payload: DeleteDocumentsPayload, user: AuthUser = Depends(require_data_editor)) -> dict[str, Any]:
    ensure_allowed_index(payload.index)
    ids = [str(i).strip() for i in payload.ids if str(i).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不可為空。")

    deleted: list[str] = []
    not_found: list[str] = []
    for doc_id in ids:
        try:
            res = es_client.get_es().delete(index=payload.index, id=doc_id, refresh="wait_for")
            body = es_client._unwrap_es(res)
            deleted.append(doc_id)
            append_audit_event({
                "action": "editor.delete_document",
                "username": user.username,
                "role": user.role,
                "index": payload.index,
                "id": doc_id,
                "result": body.get("result"),
                "changed_paths": [],
                "changes": [],
            })
        except Exception:
            not_found.append(doc_id)
    return {"ok": True, "index": payload.index, "deleted_ids": deleted, "not_found_ids": not_found}


