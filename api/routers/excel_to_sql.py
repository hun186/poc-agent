from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from data_ingestion.excel_to_sql.dashboard import (
    dashboard_payload,
    delete_imported_sql_row,
    discover_dashboard_tasks,
)
from api.services.auth_store import AUTH_STORE, AuthUser, parse_token

router = APIRouter(tags=["excel-to-sql"])


class DeleteImportedRowPayload(BaseModel):
    config: str = Field(default="config/excel_to_sql/vessel_activities.example.json")
    hash_value: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(default="", max_length=500)


def _static_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "static" / filename


@router.get("/excel-to-sql-dashboard", include_in_schema=False)
def excel_to_sql_dashboard_page() -> FileResponse:
    return FileResponse(_static_path("excel_to_sql_dashboard.html"))


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="請先登入。"
        )
    return authorization.split(" ", 1)[1].strip()


def current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    payload = parse_token(_bearer_token(authorization))
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已失效，請重新登入。"
        )
    username = str(payload.get("sub") or "")
    stored = AUTH_STORE.get_user(username)
    if not stored or stored.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="帳號尚未啟用。"
        )
    return AuthUser(
        username=username, role=str(stored.get("role") or "user"), status="active"
    )


@router.get("/v1/excel-to-sql/dashboard-tasks")
def excel_to_sql_dashboard_tasks(
    config_dir: str = Query(
        "config/excel_to_sql", description="掃描 dashboard.enabled=true 的設定檔目錄"
    ),
    _: AuthUser = Depends(current_user),
) -> dict[str, Any]:
    return {"tasks": discover_dashboard_tasks(config_dir)}


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
        100, ge=1, le=1000, description="最近事件每頁筆數與檔案列數上限"
    ),
    page: int = Query(1, ge=1, description="最近 audit 事件頁碼"),
    status_filter: str | None = Query(None, description="最近 audit 事件：狀態篩選"),
    source_file_filter: str | None = Query(
        None, description="最近 audit 事件：來源檔名部分比對"
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
    _: AuthUser = Depends(current_user),
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
            destination_table_filter=destination_table_filter,
            row_no_filter=row_no_filter,
            message_filter=message_filter,
            hash_value_filter=hash_value_filter,
            payload_filter=payload_filter,
            page=page,
            chart_bucket=chart_bucket,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"讀取 Excel 匯入監控資料失敗：{exc}"
        ) from exc


@router.post("/v1/excel-to-sql/delete-row")
def excel_to_sql_delete_row(
    payload: DeleteImportedRowPayload,
    user: AuthUser = Depends(current_user),
) -> dict[str, Any]:
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
