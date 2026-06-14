# api/routers/editor.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from agent.es import es_client
from api.routers.editor_dependencies import bearer_token, current_user, require_data_editor, require_superuser, static_path
from api.routers.editor_models import (
    ApprovePayload,
    AuthPayload,
    ChangePasswordPayload,
    DeleteDocumentsPayload,
    ForgotPasswordPayload,
    RecoverPasswordPayload,
    ResetPasswordPayload,
    SaveDocumentPayload,
)
from api.services.auth_store import AUTH_STORE, AuthUser, create_token, parse_token, public_role_options
from api.services.editor_audit import append_audit_event, diff_values
from api.services.editor_audit_queries import (
    build_audit_time_series,
    build_usage_stats,
    filter_audit_records,
    load_audit_records,
    normalize_chart_bucket,
)
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
AUTH_FAILURE_MESSAGE = "帳號或密碼錯誤，或帳號尚未啟用。"


def _rate_limit_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="登入或密碼重設嘗試次數過多，請稍後再試。",
        headers={"Retry-After": str(max(1, retry_after))},
    )


@router.get("/editor", include_in_schema=False)
def editor_page() -> FileResponse:
    return FileResponse(static_path("editor.html"))


@router.get("/static/audit_tools.js", include_in_schema=False)
def audit_tools_script() -> FileResponse:
    return FileResponse(static_path("audit_tools.js"), media_type="application/javascript")


@router.post("/v1/auth/register")
def register(payload: AuthPayload) -> dict[str, Any]:
    try:
        user = AUTH_STORE.register(
            payload.username,
            payload.password,
            full_name=payload.full_name,
            department=payload.department,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_registered",
        "username": payload.username,
    })
    return {"user": user, "message": "帳號已建立，狀態為 pending；請等待超級使用者審核。"}


@router.post("/v1/auth/login")
def login(payload: AuthPayload, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    retry_after = AUTH_STORE.throttle_retry_after("login", payload.username, client_host)
    if retry_after:
        AUTH_STORE.record_login_audit(
            payload.username,
            success=False,
            reason="rate_limited",
            client_host=client_host,
            user_agent=user_agent,
        )
        append_audit_event({"action": "auth.login", "username": payload.username, "success": False, "reason": "rate_limited"})
        raise _rate_limit_exception(retry_after)

    user = AUTH_STORE.authenticate(payload.username, payload.password)
    if user is None:
        retry_after = AUTH_STORE.record_auth_failure("login", payload.username, client_host)
        AUTH_STORE.record_login_audit(
            payload.username,
            success=False,
            reason="invalid_credentials",
            client_host=client_host,
            user_agent=user_agent,
        )
        append_audit_event({"action": "auth.login", "username": payload.username, "success": False, "reason": "invalid_credentials"})
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_FAILURE_MESSAGE)
    if user.status != "active":
        retry_after = AUTH_STORE.record_auth_failure("login", payload.username, client_host)
        AUTH_STORE.record_login_audit(
            payload.username,
            success=False,
            reason="inactive_account",
            role=user.role,
            status_value=user.status,
            client_host=client_host,
            user_agent=user_agent,
        )
        append_audit_event({"action": "auth.login", "username": payload.username, "success": False, "reason": "inactive_account", "status": user.status})
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTH_FAILURE_MESSAGE)
    AUTH_STORE.clear_auth_failures("login", payload.username, client_host)
    AUTH_STORE.record_login_audit(
        payload.username,
        success=True,
        reason="ok",
        role=user.role,
        status_value=user.status,
        client_host=client_host,
        user_agent=user_agent,
    )
    append_audit_event({"action": "auth.login", "username": payload.username, "success": True, "role": user.role})
    return {"access_token": create_token(user), "token_type": "bearer", "user": user.__dict__}


@router.post("/v1/auth/logout")
def logout(
    user: AuthUser = Depends(current_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    payload = parse_token(bearer_token(authorization))
    if payload:
        AUTH_STORE.deny_token(payload)
    append_audit_event({"action": "auth.logout", "username": user.username})
    return {"message": "已登出；此 token 已失效。"}


@router.post("/v1/auth/change-password")
def change_password(payload: ChangePasswordPayload, user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    try:
        updated = AUTH_STORE.change_password(user.username, payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({"action": "auth.password_changed", "username": user.username})
    return {"user": updated, "message": "密碼已變更，既有 token 已失效；請重新登入。"}


@router.post("/v1/auth/forgot-password")
def forgot_password(payload: ForgotPasswordPayload) -> dict[str, Any]:
    # Do not issue or return a reset token from the public endpoint. Returning a token
    # here would let anyone who knows a username take over that account.
    append_audit_event({"action": "auth.password_reset_requested", "username": payload.username})
    return {"message": "若帳號存在，已收到忘記密碼申請；請聯絡系統管理員核身後取得一次性重設 token。"}


@router.post("/v1/auth/reset-password")
def recover_password(payload: RecoverPasswordPayload, request: Request) -> dict[str, Any]:
    client_host = request.client.host if request.client else None
    retry_after = AUTH_STORE.throttle_retry_after("password_reset", payload.username, client_host)
    if retry_after:
        append_audit_event({"action": "auth.password_recovered", "username": payload.username, "success": False, "reason": "rate_limited"})
        raise _rate_limit_exception(retry_after)
    try:
        updated = AUTH_STORE.recover_password(payload.username, payload.reset_token, payload.new_password)
    except ValueError as exc:
        retry_after = AUTH_STORE.record_auth_failure("password_reset", payload.username, client_host)
        append_audit_event({"action": "auth.password_recovered", "username": payload.username, "success": False, "reason": "invalid_or_expired_token"})
        if retry_after:
            raise _rate_limit_exception(retry_after)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AUTH_STORE.clear_auth_failures("password_reset", payload.username, client_host)
    append_audit_event({"action": "auth.password_recovered", "username": payload.username, "success": True})
    return {"user": updated, "message": "密碼已重設，既有 token 已失效；請重新登入。"}


@router.get("/v1/auth/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    return {"user": user.__dict__, "role_options": public_role_options()}


@router.get("/v1/auth/users")
def list_users(_: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"users": AUTH_STORE.list_users(), "role_options": public_role_options()}


@router.post("/v1/auth/users/{username}/approve")
def approve_user(username: str, payload: ApprovePayload, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        approved = AUTH_STORE.approve_user(username, payload.role, approved_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_approved",
        "username": username,
        "actor": user.username,
        "role": payload.role,
    })
    return {"user": approved}


@router.post("/v1/auth/users/{username}/reject")
def reject_user(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        rejected = AUTH_STORE.reject_user(username, rejected_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_rejected",
        "username": username,
        "actor": user.username,
    })
    return {"user": rejected}


@router.delete("/v1/auth/users/{username}")
def delete_user(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    if username == user.username:
        raise HTTPException(status_code=400, detail="不可刪除目前登入的超級使用者。")
    try:
        deleted = AUTH_STORE.delete_user(username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    append_audit_event({
        "action": "auth.user_deleted",
        "username": username,
        "actor": user.username,
    })
    return {"user": deleted}


@router.post("/v1/auth/users/{username}/password-reset-token")
def issue_password_reset_token(username: str, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    reset_token = AUTH_STORE.request_password_reset(username)
    if not reset_token:
        raise HTTPException(status_code=404, detail="帳號不存在或尚未啟用，無法建立重設 token。")
    append_audit_event({"action": "auth.password_reset_token_issued", "username": username, "actor": user.username})
    return {"username": username, "reset_token": reset_token, "message": "一次性重設 token 已建立；請用安全管道交付給該使用者。"}


@router.post("/v1/auth/users/{username}/reset-password")
def reset_user_password(username: str, payload: ResetPasswordPayload, user: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    try:
        updated = AUTH_STORE.reset_user_password(username, payload.new_password, reset_by=user.username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_audit_event({"action": "auth.password_reset_by_superuser", "username": username, "actor": user.username})
    return {"user": updated, "message": "密碼已由超級使用者重設，該帳號既有 token 已失效。"}


@router.get("/v1/auth/login-audit")
def list_login_audit(limit: int = Query(100, ge=1, le=1000), _: AuthUser = Depends(require_superuser)) -> dict[str, Any]:
    return {"events": AUTH_STORE.list_login_audit(limit)}


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
    default_index = es_client.ES_INDEX_DEFAULT or (indexes[0] if indexes else "")
    return {"indexes": indexes, "default_index": default_index}


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
    size: int = Query(20, ge=1, le=200),
    page: int = Query(1, ge=1),
    start_ts: str = Query("", description="起始時間（ISO8601）"),
    end_ts: str = Query("", description="結束時間（ISO8601）"),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    ensure_allowed_index(index)
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
        "warnings": warnings,
    }


@router.get("/v1/editor/doc")
def get_document(
    index: str = Query(...),
    id: str = Query(...),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    ensure_allowed_index(index)
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




@router.get("/v1/editor/usage-stats")
def usage_stats(
    category: str = Query("all", description="統計類別：all、document、account"),
    username: str | None = Query(None, description="依使用者篩選；非 superuser 一律限定自己"),
    action: str | None = Query(None, description="依操作類型篩選"),
    index: str | None = Query(None, description="依 index 篩選"),
    start_ts: str | None = Query(None, description="起始時間（ISO 8601）"),
    end_ts: str | None = Query(None, description="結束時間（ISO 8601）"),
    chart_bucket: str = Query("day", description="統計曲線區間：hour、6_hours、12_hours、day、week、month"),
    events_limit: int = Query(100, ge=1, le=500, description="回傳套用同一篩選條件的 audit 事件筆數"),
    timezone_offset_minutes: int = 0,
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    records = load_audit_records(limit=20000)
    mine = [r for r in records if str(r.get("username") or "") == user.username]
    out = {"me": build_usage_stats(mine)}
    if user.role == "superuser":
        out["all"] = build_usage_stats(records)

    normalized_bucket, bucket_label = normalize_chart_bucket(chart_bucket)
    category_value = (category or "all").strip().lower()
    action_prefix = ""
    if category_value == "document":
        action_prefix = "editor."
    elif category_value == "account":
        action_prefix = "auth."
    elif category_value != "all":
        raise HTTPException(status_code=400, detail="category 僅支援 all、document、account。")

    filtered_username = username if user.role == "superuser" else user.username
    filtered = filter_audit_records(
        records,
        username=filtered_username,
        action=action,
        action_prefix=action_prefix or None,
        index=index,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    out["filtered"] = {
        "category": category_value,
        "stats": build_usage_stats(filtered),
        "series": build_audit_time_series(filtered, normalized_bucket, timezone_offset_minutes),
        "events": filtered[:events_limit],
        "events_total": len(filtered),
        "events_limit": events_limit,
        "chart_bucket": normalized_bucket,
        "chart_bucket_label": bucket_label,
        "timezone_offset_minutes": timezone_offset_minutes,
        "is_restricted_to_self": user.role != "superuser",
    }
    return out


@router.get("/v1/editor/audit-logs")
def list_audit_logs(
    username: str | None = Query(None, description="依操作者帳號篩選"),
    action: str | None = Query(None, description="依操作類型篩選"),
    action_prefix: str | None = Query(None, description="依操作類型 prefix 篩選，例如 editor. 或 auth."),
    index: str | None = Query(None, description="依 index 篩選"),
    id: str | None = Query(None, description="依文件 ID 篩選"),
    changed_path: str | None = Query(None, description="依異動欄位路徑篩選（部分比對）"),
    start_ts: str | None = Query(None, description="起始時間（ISO 8601）"),
    end_ts: str | None = Query(None, description="結束時間（ISO 8601）"),
    limit: int = Query(100, ge=1, le=500),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    action_prefix_value = (action_prefix or "").strip().lower()
    if user.role != "superuser" and not action_prefix_value.startswith("auth."):
        raise HTTPException(status_code=403, detail="一般使用者只能查詢自己的帳號操作紀錄。")
    effective_username = username if user.role == "superuser" else user.username
    records = load_audit_records(limit=5000)
    filtered = filter_audit_records(
        records,
        username=effective_username,
        action=action,
        action_prefix=action_prefix,
        index=index,
        id=id,
        changed_path=changed_path,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    return {"total": len(filtered), "limit": limit, "hits": filtered[:limit]}
