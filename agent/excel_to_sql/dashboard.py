from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from agent.excel_to_sql.ingest import (
    DEFAULT_AUDIT_TABLE,
    build_conn_str_from_config,
    get_nested,
    load_json_config,
    quote_ident,
    quote_object_path,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(cursor, row) -> dict[str, Any]:
    columns = [col[0] for col in cursor.description]
    return {name: _json_safe(value) for name, value in zip(columns, row)}


def _connect(cfg: dict[str, Any]):
    import pyodbc

    return pyodbc.connect(build_conn_str_from_config(cfg))


def _audit_table(cfg: dict[str, Any]) -> str:
    return str(
        get_nested(cfg, "audit.table", DEFAULT_AUDIT_TABLE) or DEFAULT_AUDIT_TABLE
    )


def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        "SELECT CASE WHEN OBJECT_ID(?, N'U') IS NULL THEN 0 ELSE 1 END", table
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _fetch_all_dicts(
    cursor, sql: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def _coerce_utc_datetime(
    value: str | datetime | date | None, *, end_of_day: bool = False
) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.max if end_of_day else time.min)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            if len(text) == 10:
                dt = datetime.combine(
                    date.fromisoformat(text), time.max if end_of_day else time.min
                )
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("時間格式錯誤，請使用 ISO 8601 或 YYYY-MM-DD。") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _audit_time_window(
    days: int,
    start_ts: str | datetime | date | None,
    end_ts: str | datetime | date | None,
) -> tuple[int, datetime | None, datetime | None]:
    days = max(1, min(int(days), 365))
    start_dt = _coerce_utc_datetime(start_ts)
    end_dt = _coerce_utc_datetime(end_ts, end_of_day=True)
    if start_dt and end_dt and start_dt > end_dt:
        raise ValueError("起始時間不可晚於結束時間。")
    return days, start_dt, end_dt


def _append_time_filters(
    conditions: list[str],
    params: list[Any],
    *,
    days: int,
    start_dt: datetime | None,
    end_dt: datetime | None,
):
    if start_dt or end_dt:
        if start_dt:
            conditions.append("processed_at >= ?")
            params.append(start_dt)
        if end_dt:
            conditions.append("processed_at <= ?")
            params.append(end_dt)
    else:
        conditions.append("processed_at >= DATEADD(day, -?, SYSUTCDATETIME())")
        params.append(days)


def _where_clause(conditions: list[str]) -> str:
    if not conditions:
        return ""
    return "WHERE " + " AND ".join(conditions)


def _contains_filter(value: str | None) -> str:
    return f"%{str(value or '').strip()}%"


def _parse_payload(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _dashboard_enabled(cfg: dict[str, Any]) -> bool:
    return bool(get_nested(cfg, "dashboard.enabled", False))


def _dashboard_name(cfg: dict[str, Any], config_path: Path) -> str:
    configured = str(get_nested(cfg, "dashboard.name", "") or "").strip()
    if configured:
        return configured
    table = str(get_nested(cfg, "destination.table", "") or "").strip()
    return table or config_path.stem


def discover_dashboard_tasks(
    config_dir: str | Path = "config/excel_to_sql",
) -> list[dict[str, Any]]:
    root = Path(config_dir)
    if not root.exists():
        return []

    tasks: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            cfg = load_json_config(str(path))
        except Exception:
            continue
        if not _dashboard_enabled(cfg):
            continue
        tasks.append(
            {
                "name": _dashboard_name(cfg, path),
                "config_path": str(path),
                "audit_table": _audit_table(cfg),
                "destination_table": str(
                    get_nested(cfg, "destination.table", "") or ""
                ),
                "source_directory": str(get_nested(cfg, "source.directory", "") or ""),
            }
        )
    return tasks


def dashboard_payload(
    config_path: str,
    *,
    days: int = 14,
    limit: int = 100,
    start_ts: str | datetime | date | None = None,
    end_ts: str | datetime | date | None = None,
    status_filter: str | None = None,
    source_file_filter: str | None = None,
    row_no_filter: int | None = None,
    message_filter: str | None = None,
    hash_value_filter: str | None = None,
    payload_filter: str | None = None,
    page: int = 1,
) -> dict[str, Any]:
    cfg = load_json_config(config_path)
    task_name = _dashboard_name(cfg, Path(config_path))
    table = _audit_table(cfg)
    quoted_table = quote_object_path(table)
    days, start_dt, end_dt = _audit_time_window(days, start_ts, end_ts)
    limit = max(1, min(int(limit), 1000))
    page = max(1, int(page))

    conn = _connect(cfg)
    try:
        cursor = conn.cursor()
        try:
            if not _table_exists(cursor, table):
                return {
                    "config_path": str(Path(config_path)),
                    "audit_table": table,
                    "task_name": task_name,
                    "days": days,
                    "start_ts": start_dt.isoformat() if start_dt else None,
                    "end_ts": end_dt.isoformat() if end_dt else None,
                    "audit_time_basis": "UTC (SQL Server SYSUTCDATETIME)",
                    "exists": False,
                    "summary": [],
                    "daily": [],
                    "files": [],
                    "recent": [],
                    "recent_paging": {"page": page, "page_size": limit, "total": 0},
                }

            time_conditions: list[str] = []
            time_params: list[Any] = []
            _append_time_filters(
                time_conditions,
                time_params,
                days=days,
                start_dt=start_dt,
                end_dt=end_dt,
            )
            time_where = _where_clause(time_conditions)

            summary = _fetch_all_dicts(
                cursor,
                f"""
SELECT status, COUNT(1) AS count
FROM {quoted_table}
{time_where}
GROUP BY status
ORDER BY status
""",
                tuple(time_params),
            )

            daily = _fetch_all_dicts(
                cursor,
                f"""
SELECT CONVERT(date, processed_at) AS day, status, COUNT(1) AS count
FROM {quoted_table}
{time_where}
GROUP BY CONVERT(date, processed_at), status
ORDER BY day DESC, status
""",
                tuple(time_params),
            )

            files = _fetch_all_dicts(
                cursor,
                f"""
SELECT TOP (?)
    source_file,
    MAX(processed_at) AS last_processed_at,
    COUNT(1) AS total_rows,
    SUM(CASE WHEN status = 'inserted' THEN 1 ELSE 0 END) AS inserted_rows,
    SUM(CASE WHEN status = 'duplicate' THEN 1 ELSE 0 END) AS duplicate_rows,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_rows,
    SUM(CASE WHEN status = 'header_smart_match' THEN 1 ELSE 0 END) AS header_smart_matches
FROM {quoted_table}
{time_where}
GROUP BY source_file
ORDER BY MAX(processed_at) DESC
""",
                (limit, *time_params),
            )

            recent_conditions = list(time_conditions)
            recent_params = list(time_params)
            clean_status = str(status_filter or "").strip()
            clean_source_file = str(source_file_filter or "").strip()
            clean_message = str(message_filter or "").strip()
            clean_hash = str(hash_value_filter or "").strip()
            clean_payload = str(payload_filter or "").strip()
            if clean_status:
                recent_conditions.append("status = ?")
                recent_params.append(clean_status)
            if clean_source_file:
                recent_conditions.append("source_file LIKE ?")
                recent_params.append(_contains_filter(clean_source_file))
            if row_no_filter is not None:
                recent_conditions.append("row_no = ?")
                recent_params.append(int(row_no_filter))
            if clean_message:
                recent_conditions.append("message LIKE ?")
                recent_params.append(_contains_filter(clean_message))
            if clean_hash:
                recent_conditions.append("hash_value LIKE ?")
                recent_params.append(_contains_filter(clean_hash))
            if clean_payload:
                recent_conditions.append("row_payload LIKE ?")
                recent_params.append(_contains_filter(clean_payload))
            recent_where = _where_clause(recent_conditions)

            filtered_daily = _fetch_all_dicts(
                cursor,
                f"""
SELECT CONVERT(date, processed_at) AS day, COUNT(1) AS count
FROM {quoted_table}
{recent_where}
GROUP BY CONVERT(date, processed_at)
ORDER BY day ASC
""",
                tuple(recent_params),
            )

            total_rows = _fetch_all_dicts(
                cursor,
                f"""
SELECT COUNT(1) AS total
FROM {quoted_table}
{recent_where}
""",
                tuple(recent_params),
            )
            recent_total = int(total_rows[0].get("total") or 0) if total_rows else 0
            max_page = max(1, (recent_total + limit - 1) // limit)
            page = min(page, max_page)
            offset = (page - 1) * limit

            recent = _fetch_all_dicts(
                cursor,
                f"""
WITH ordered_recent AS (
    SELECT
        audit_id,
        run_id,
        source_file,
        sheet_name,
        row_no,
        hash_value,
        destination_table,
        status,
        message,
        row_payload,
        processed_at,
        ROW_NUMBER() OVER (ORDER BY processed_at DESC, audit_id DESC) AS rn
    FROM {quoted_table}
    {recent_where}
)
SELECT
    audit_id,
    run_id,
    source_file,
    sheet_name,
    row_no,
    hash_value,
    destination_table,
    status,
    message,
    row_payload,
    processed_at
FROM ordered_recent
WHERE rn > ? AND rn <= ?
ORDER BY rn
""",
                (*recent_params, offset, offset + limit),
            )
            for item in recent:
                item["row_payload"] = _parse_payload(item.get("row_payload"))

            return {
                "config_path": str(Path(config_path)),
                "audit_table": table,
                "task_name": task_name,
                "days": days,
                "start_ts": start_dt.isoformat() if start_dt else None,
                "end_ts": end_dt.isoformat() if end_dt else None,
                "audit_time_basis": "UTC (SQL Server SYSUTCDATETIME)",
                "recent_filters": {
                    "status": clean_status,
                    "source_file": clean_source_file,
                    "row_no": row_no_filter,
                    "message": clean_message,
                    "hash_value": clean_hash,
                    "payload": clean_payload,
                },
                "filtered_daily": filtered_daily,
                "recent_paging": {"page": page, "page_size": limit, "total": recent_total},
                "exists": True,
                "summary": summary,
                "daily": daily,
                "files": files,
                "recent": recent,
            }
        finally:
            cursor.close()
    finally:
        conn.close()


def delete_imported_sql_row(
    config_path: str,
    *,
    hash_value: str,
    actor: str,
    reason: str = "",
) -> dict[str, Any]:
    cfg = load_json_config(config_path)
    destination_table = str(get_nested(cfg, "destination.table", "") or "").strip()
    if not destination_table:
        raise ValueError("設定檔缺少 destination.table，無法刪除 SQL 資料列。")

    hash_field = str(
        get_nested(cfg, "destination.hash_field", "hash_value") or "hash_value"
    ).strip()
    if not hash_field:
        raise ValueError("destination.hash_field 不可為空。")

    audit_table = _audit_table(cfg)
    clean_hash = str(hash_value or "").strip()
    if not clean_hash:
        raise ValueError("hash_value 不可為空。")

    conn = _connect(cfg)
    try:
        cursor = conn.cursor()
        try:
            delete_sql = (
                f"DELETE FROM {quote_object_path(destination_table)} "
                f"WHERE {quote_ident(hash_field)} = ?"
            )
            cursor.execute(delete_sql, clean_hash)
            deleted_rows = max(int(cursor.rowcount or 0), 0)

            status = "sql_deleted" if deleted_rows else "sql_delete_not_found"
            message = (
                f"user={actor}; deleted_rows={deleted_rows}; "
                f"hash_field={hash_field}; reason={reason or '(empty)'}"
            )

            if _table_exists(cursor, audit_table):
                audit_sql = (
                    f"INSERT INTO {quote_object_path(audit_table)} "
                    "([run_id], [source_file], [sheet_name], [row_no], [hash_value], "
                    "[destination_table], [status], [message], [row_payload]) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                payload = {
                    "action": "delete_imported_sql_row",
                    "actor": actor,
                    "reason": reason,
                    "config_path": str(Path(config_path)),
                    "destination_table": destination_table,
                    "hash_field": hash_field,
                    "deleted_rows": deleted_rows,
                }
                cursor.execute(
                    audit_sql,
                    "manual-control",
                    "dashboard",
                    None,
                    None,
                    clean_hash,
                    destination_table,
                    status,
                    message,
                    json.dumps(payload, ensure_ascii=False, default=_json_safe),
                )

            conn.commit()
            return {
                "ok": True,
                "status": status,
                "deleted_rows": deleted_rows,
                "hash_value": clean_hash,
                "destination_table": destination_table,
                "hash_field": hash_field,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        conn.close()
