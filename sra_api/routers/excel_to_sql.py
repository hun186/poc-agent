from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from data_ingestion.excel_to_sql.dashboard import (
    dashboard_payload,
    delete_imported_sql_row,
    delete_imported_sql_rows,
    discover_dashboard_tasks,
)
from data_ingestion.excel_to_sql.table_editor import (
    list_sql_source_rows,
    sql_source_stats,
    update_sql_source_row,
)
from data_ingestion.excel_to_sql.task_configs import (
    approve_task_config,
    create_task_config,
    delete_task_config,
    list_task_configs,
    set_task_config_enabled,
)
from data_ingestion.excel_to_sql.user_imports import (
    import_record,
    list_import_records,
    preview_record,
    save_upload,
)
from api.routers.editor_dependencies import (
    current_user,
    require_data_editor,
    require_db_operator,
    require_superuser,
)
from api.services.auth_store import ROLE_DATA_EDITOR, ROLE_DB_OPERATOR, ROLE_SUPERUSER, AuthUser, has_role_at_least

router = APIRouter(tags=["excel-to-sql"])


class DeleteImportedRowPayload(BaseModel):
    config: str = Field(default="config/excel_to_sql/vessel_activities.example.json")
    hash_value: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(default="", max_length=500)


class DeleteImportedRowsPayload(BaseModel):
    config: str = Field(default="config/excel_to_sql/vessel_activities.example.json")
    hash_values: list[str] = Field(..., min_length=1, max_length=500)
    reason: str = Field(default="", max_length=500)


class UpdateSqlSourceRowPayload(BaseModel):
    config: str = Field(default="config/excel_to_sql/vessel_activities.example.json")
    hash_value: str = Field(..., min_length=1, max_length=128)
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(..., min_length=1, max_length=500)


class ApproveTaskConfigPayload(BaseModel):
    config: str = Field(..., min_length=6, max_length=240)


class TaskConfigStatusPayload(BaseModel):
    config: str = Field(..., min_length=6, max_length=240)
    enabled: bool


class DeleteTaskConfigPayload(BaseModel):
    config: str = Field(..., min_length=6, max_length=240)


class ExcelToSqlTaskConfigPayload(BaseModel):
    filename: str = Field(..., min_length=6, max_length=240)
    task_name: str = Field(..., min_length=1, max_length=120)
    connection_source_config: str = Field(default="", max_length=240)
    db_driver: str = Field(default="auto", max_length=128)
    db_server: str = Field(default="", max_length=255)
    db_database: str = Field(default="", max_length=128)
    db_trusted_connection: bool = False
    db_user: str = Field(default="", max_length=128)
    db_password: str = Field(default="", max_length=500)
    db_encrypt: bool = True
    db_trust_server_certificate: bool = True
    source_directory: str = Field(default="./data/excel_inbox", max_length=500)
    file_pattern: str = Field(default="*.xlsx", max_length=80)
    recursive: bool = False
    source_sheet: str = Field(..., min_length=1, max_length=128)
    header_row: int = Field(default=1, ge=1, le=100)
    start_row: int = Field(default=2, ge=1, le=1000000)
    end_row: int = Field(default=0, ge=0, le=1000000)
    destination_table: str = Field(..., min_length=1, max_length=128)
    auto_create_table: bool = True
    auto_create_missing_fields: bool = True
    default_field_type: str = Field(default="NVARCHAR(MAX)", max_length=80)
    hash_field: str = Field(default="hash_value", max_length=80)
    hash_field_type: str = Field(default="CHAR(64)", max_length=80)
    create_hash_index: bool = True
    mappings: list[dict[str, Any]] = Field(default_factory=list)
    composite_mappings: list[dict[str, Any]] = Field(default_factory=list)
    batch_size: int = Field(default=500, ge=1, le=10000)
    skip_empty_rows: bool = True
    truncate_before_load: bool = False
    fast_executemany: bool = True
    retry_max_attempts: int = Field(default=3, ge=1, le=20)
    retry_interval_seconds: int = Field(default=60, ge=0, le=86400)
    archive_enabled: bool = True
    archive_success_dir: str = Field(
        default="./data/excel_archive/success", max_length=500
    )
    archive_fail_dir: str = Field(default="./data/excel_archive/failed", max_length=500)
    log_dir: str = Field(default="./logs/excel_import", max_length=500)
    audit_table: str = Field(default="dbo.ExcelImportAudit", max_length=128)
    overwrite: bool = False


def _is_superuser(user: AuthUser) -> bool:
    return user.role == ROLE_SUPERUSER


def _can_review_task_mappings(user: AuthUser) -> bool:
    return has_role_at_least(user.role, ROLE_DB_OPERATOR)


def _dashboard_tasks_for_user(user: AuthUser, config_dir: str) -> list[dict[str, Any]]:
    tasks = discover_dashboard_tasks(config_dir)
    if _can_review_task_mappings(user):
        return tasks
    return [
        {key: value for key, value in task.items() if key != "review_summary"}
        for task in tasks
    ]


def _normalize_config_path(value: str) -> str:
    return str(Path(str(value or "")).as_posix())


def _ensure_source_editor_config_allowed(user: AuthUser, config: str, config_dir: str) -> None:
    requested = _normalize_config_path(config)
    allowed = {
        _normalize_config_path(str(task.get("config_path") or ""))
        for task in _dashboard_tasks_for_user(user, config_dir)
    }
    if requested not in allowed:
        raise HTTPException(
            status_code=403,
            detail="SQL 來源資料編輯器只能操作已啟用 Excel→SQL 任務清單中的 destination.table。",
        )


def _static_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "static" / filename


@router.get("/excel-to-sql-dashboard", include_in_schema=False)
def excel_to_sql_dashboard_page() -> FileResponse:
    return FileResponse(_static_path("excel_to_sql_dashboard.html"))


@router.get("/excel-to-sql-import-center", include_in_schema=False)
def excel_to_sql_import_center_page() -> FileResponse:
    return FileResponse(_static_path("excel_to_sql_import_center.html"))


@router.get("/excel-to-sql-task-configs", include_in_schema=False)
def excel_to_sql_task_configs_page() -> FileResponse:
    return FileResponse(_static_path("excel_to_sql_task_configs.html"))


@router.get("/excel-to-sql-source-editor", include_in_schema=False)
def excel_to_sql_source_editor_page() -> FileResponse:
    return FileResponse(_static_path("excel_to_sql_source_editor.html"))


@router.get("/excel-to-sql-source-dashboard", include_in_schema=False)
def excel_to_sql_source_dashboard_page() -> FileResponse:
    return FileResponse(_static_path("excel_to_sql_source_dashboard.html"))


@router.get("/v1/excel-to-sql/dashboard-tasks")
def excel_to_sql_dashboard_tasks(
    config_dir: str = Query(
        "config/excel_to_sql", description="掃描 dashboard.enabled=true 的設定檔目錄"
    ),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    return {"tasks": _dashboard_tasks_for_user(user, config_dir)}


@router.get("/v1/excel-to-sql/dashboard")
def excel_to_sql_dashboard_data(
    config: str = Query(
        "config/excel_to_sql/vessel_activities.example.json",
        description="Excel 匯入設定檔路徑",
    ),
    days: int = Query(14, ge=1, le=365, description="未提供起迄時間時的回看天數"),
    start_ts: str | None = Query(
        None, description="起始時間（ISO 8601；會以 UTC 比對 audit.processed_at）"
    ),
    end_ts: str | None = Query(
        None, description="結束時間（ISO 8601；會以 UTC 比對 audit.processed_at）"
    ),
    limit: int = Query(
        50000, ge=1, le=400000, description="最近事件載入列數上限"
    ),
    page: int = Query(1, ge=1, description="最近 audit 事件頁碼"),
    status_filter: str | None = Query(None, description="最近 audit 事件：狀態篩選"),
    source_file_filter: str | None = Query(
        None, description="最近 audit 事件：來源檔名部分比對"
    ),
    username_filter: list[str] | None = Query(
        None, description="最近 audit 事件：使用者，可重複提供以複選"
    ),
    destination_table_filter: list[str] | None = Query(
        None, description="最近 audit 事件：目的地 table，可重複提供以複選"
    ),
    row_no_filter: int | None = Query(
        None, ge=1, description="最近 audit 事件：Excel 列號"
    ),
    message_filter: str | None = Query(
        None, description="最近 audit 事件：訊息部分比對"
    ),
    hash_value_filter: str | None = Query(
        None, description="最近 audit 事件：hash 部分比對"
    ),
    payload_filter: str | None = Query(
        None, description="最近 audit 事件：payload JSON 文字部分比對"
    ),
    chart_bucket: str = Query(
        "day",
        description="audit 統計曲線區間：hour、6_hours、12_hours、day、week、month",
    ),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    try:
        return dashboard_payload(
            config,
            days=days,
            limit=limit,
            start_ts=start_ts,
            end_ts=end_ts,
            status_filter=status_filter,
            source_file_filter=source_file_filter,
            username_filter=username_filter,
            destination_table_filter=destination_table_filter,
            row_no_filter=row_no_filter,
            message_filter=message_filter,
            hash_value_filter=hash_value_filter,
            payload_filter=payload_filter,
            page=page,
            chart_bucket=chart_bucket,
            expose_operational_metadata=has_role_at_least(user.role, ROLE_DB_OPERATOR),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"讀取 Excel 匯入監控資料失敗：{exc}"
        ) from exc


@router.get("/v1/excel-to-sql/source-stats")
def excel_to_sql_source_stats(
    config: str = Query("config/excel_to_sql/vessel_activities.example.json"),
    q: str = Query("", max_length=200),
    source_file_filter: str = Query("", max_length=200),
    row_no_filter: int | None = Query(None, ge=1),
    hash_value_filter: str = Query("", max_length=200),
    payload_filter: str = Query("", max_length=200),
    username_filter: list[str] | None = Query(None),
    import_start_ts: str = Query("", max_length=80),
    import_end_ts: str = Query("", max_length=80),
    group_by: list[str] | None = Query(None, description="分群欄位，可重複提供"),
    top_n: int = Query(20, ge=1, le=100),
    chart_bucket: str = Query("day", max_length=40),
    config_dir: str = Query("config/excel_to_sql"),
    user: AuthUser = Depends(require_data_editor),
) -> dict[str, Any]:
    _ensure_source_editor_config_allowed(user, config, config_dir)
    try:
        return sql_source_stats(config, q=q, source_file_filter=source_file_filter, row_no_filter=row_no_filter, hash_value_filter=hash_value_filter, payload_filter=payload_filter, username_filter=username_filter, import_start_ts=import_start_ts, import_end_ts=import_end_ts, group_by=group_by, top_n=top_n, chart_bucket=chart_bucket)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讀取 SQL 來源資料統計失敗：{exc}") from exc


@router.get("/v1/excel-to-sql/source-rows")
def excel_to_sql_source_rows(
    config: str = Query(
        "config/excel_to_sql/vessel_activities.example.json",
        description="Excel 匯入設定檔路徑；只能讀取該任務的 destination.table",
    ),
    q: str = Query("", max_length=200, description="跨欄位關鍵字搜尋"),
    source_file_filter: str = Query("", max_length=200, description="來源檔名部分比對"),
    row_no_filter: int | None = Query(None, ge=1, description="Excel 列號"),
    hash_value_filter: str = Query("", max_length=200, description="hash 部分比對"),
    payload_filter: str = Query("", max_length=200, description="資料欄位文字部分比對"),
    username_filter: list[str] | None = Query(None, description="使用者，可重複提供以複選"),
    import_start_ts: str = Query("", max_length=80, description="當初匯入執行起始時間（ISO 8601；以 audit.processed_at 比對）"),
    import_end_ts: str = Query("", max_length=80, description="當初匯入執行結束時間（ISO 8601；以 audit.processed_at 比對）"),
    page: int = Query(1, ge=1),
    limit: int = Query(5000, ge=1, le=50000),
    config_dir: str = Query(
        "config/excel_to_sql", description="白名單來源：已啟用 Excel→SQL 任務設定檔目錄"
    ),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    _ensure_source_editor_config_allowed(user, config, config_dir)
    try:
        try:
            payload = list_sql_source_rows(config, q=q, source_file_filter=source_file_filter, row_no_filter=row_no_filter, hash_value_filter=hash_value_filter, payload_filter=payload_filter, username_filter=username_filter, import_start_ts=import_start_ts, import_end_ts=import_end_ts, page=page, limit=limit)
            payload["can_edit"] = has_role_at_least(user.role, ROLE_DATA_EDITOR)
            payload["can_delete"] = has_role_at_least(user.role, ROLE_DATA_EDITOR)
            payload["can_batch_delete"] = has_role_at_least(user.role, ROLE_DB_OPERATOR)
            return payload
        except TypeError:
            if any([source_file_filter, row_no_filter, hash_value_filter, payload_filter, username_filter, import_start_ts, import_end_ts]):
                raise
            payload = list_sql_source_rows(config, q=q, page=page, limit=limit)
            payload["can_edit"] = has_role_at_least(user.role, ROLE_DATA_EDITOR)
            payload["can_delete"] = has_role_at_least(user.role, ROLE_DATA_EDITOR)
            payload["can_batch_delete"] = has_role_at_least(user.role, ROLE_DB_OPERATOR)
            return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讀取 SQL 來源資料列失敗：{exc}") from exc


@router.patch("/v1/excel-to-sql/source-row")
def excel_to_sql_update_source_row(
    payload: UpdateSqlSourceRowPayload,
    config_dir: str = Query(
        "config/excel_to_sql", description="白名單來源：已啟用 Excel→SQL 任務設定檔目錄"
    ),
    user: AuthUser = Depends(require_data_editor),
) -> dict[str, Any]:
    _ensure_source_editor_config_allowed(user, payload.config, config_dir)
    try:
        return update_sql_source_row(
            payload.config,
            hash_value=payload.hash_value,
            changes=payload.changes,
            actor=user.username,
            reason=payload.reason,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新 SQL 來源資料列失敗：{exc}") from exc


@router.post("/v1/excel-to-sql/delete-row")
def excel_to_sql_delete_row(
    payload: DeleteImportedRowPayload,
    user: AuthUser = Depends(require_data_editor),
) -> dict[str, Any]:
    _ensure_source_editor_config_allowed(user, payload.config, "config/excel_to_sql")
    try:
        return delete_imported_sql_row(
            payload.config,
            hash_value=payload.hash_value,
            actor=user.username,
            reason=payload.reason,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"刪除已匯入 SQL 資料列失敗：{exc}"
        ) from exc




@router.post("/v1/excel-to-sql/delete-rows")
def excel_to_sql_delete_rows(
    payload: DeleteImportedRowsPayload,
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    try:
        return delete_imported_sql_rows(
            payload.config,
            hash_values=payload.hash_values,
            actor=user.username,
            reason=payload.reason,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"批次刪除已匯入 SQL 資料列失敗：{exc}"
        ) from exc


@router.get("/v1/excel-to-sql/task-configs")
def excel_to_sql_list_task_configs(
    scope: str = Query(
        "mine", description="mine 只列出自己建立的任務；all 僅 superuser 可用"
    ),
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    if scope == "all":
        if not _is_superuser(user):
            raise HTTPException(
                status_code=403, detail="只有 superuser 可以查看全部任務設定檔"
            )
        return {"tasks": list_task_configs()}
    if scope != "mine":
        raise HTTPException(status_code=400, detail="scope 僅支援 mine 或 all")
    return {"tasks": list_task_configs(created_by=user.username)}


@router.post("/v1/excel-to-sql/task-configs")
def excel_to_sql_create_task_config(
    payload: ExcelToSqlTaskConfigPayload,
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    try:
        created = create_task_config(
            payload.model_dump(), actor=user.username, overwrite=payload.overwrite
        )
        return {"task": created}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"建立 Excel→SQL 任務設定檔失敗：{exc}"
        ) from exc


@router.post("/v1/excel-to-sql/task-configs/approve")
def excel_to_sql_approve_task_config(
    payload: ApproveTaskConfigPayload,
    user: AuthUser = Depends(require_superuser),
) -> dict[str, Any]:
    try:
        approved = approve_task_config(payload.config, actor=user.username)
        return {"task": approved}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"啟用 Excel→SQL 任務設定檔失敗：{exc}"
        ) from exc


@router.post("/v1/excel-to-sql/task-configs/status")
def excel_to_sql_set_task_config_status(
    payload: TaskConfigStatusPayload,
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    if payload.enabled and not _is_superuser(user):
        raise HTTPException(status_code=403, detail="只有 superuser 可以啟用任務設定檔")
    if not _is_superuser(user):
        mine = {
            item["config_path"] for item in list_task_configs(created_by=user.username)
        }
        if payload.config not in mine:
            raise HTTPException(status_code=404, detail="找不到自己建立的任務設定檔")
    try:
        task = set_task_config_enabled(
            payload.config, enabled=payload.enabled, actor=user.username
        )
        return {"task": task}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"更新 Excel→SQL 任務設定檔狀態失敗：{exc}"
        ) from exc


@router.delete("/v1/excel-to-sql/task-configs")
def excel_to_sql_delete_task_config(
    payload: DeleteTaskConfigPayload,
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    try:
        deleted = delete_task_config(
            payload.config, actor=user.username, is_superuser=_is_superuser(user)
        )
        return {"task": deleted}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"刪除 Excel→SQL 任務設定檔失敗：{exc}"
        ) from exc


@router.post("/v1/excel-to-sql/import-records")
def excel_to_sql_upload_import_record(
    config: str = Query("config/excel_to_sql/vessel_activities.example.json"),
    file: UploadFile = File(...),
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    try:
        record = save_upload(
            fileobj=file.file,
            filename=file.filename or "upload.xlsx",
            username=user.username,
            config_path=config,
        )
        return {"record": record}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"上傳 Excel 匯入檔失敗：{exc}"
        ) from exc


@router.post("/v1/excel-to-sql/import-records/{record_id}/preview")
def excel_to_sql_preview_import_record(
    record_id: str,
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    try:
        return preview_record(
            record_id, username=user.username, is_superuser=_is_superuser(user)
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Excel 匯入預掃描失敗：{exc}"
        ) from exc


@router.post("/v1/excel-to-sql/import-records/{record_id}/confirm")
def excel_to_sql_confirm_import_record(
    record_id: str,
    user: AuthUser = Depends(require_db_operator),
) -> dict[str, Any]:
    try:
        return import_record(
            record_id, username=user.username, is_superuser=_is_superuser(user)
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Excel 匯入 SQL 失敗：{exc}"
        ) from exc


@router.get("/v1/excel-to-sql/import-records")
def excel_to_sql_import_records(
    config: str = Query(""),
    status: str = Query(""),
    filename: str = Query(""),
    actor: str = Query(""),
    start_ts: str = Query(""),
    end_ts: str = Query(""),
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    return {
        "records": list_import_records(
            username=user.username,
            is_superuser=_is_superuser(user),
            config=config,
            status=status,
            filename=filename,
            actor=actor,
            start_ts=start_ts,
            end_ts=end_ts,
        )
    }
