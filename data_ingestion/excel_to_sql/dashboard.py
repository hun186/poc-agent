from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from api.services.vercel_mock_runtime import should_prefer_mock_runtime
from data_ingestion.excel_to_sql.dashboard_config import (
    _dashboard_enabled,
    _dashboard_name,
)
from data_ingestion.excel_to_sql.dashboard_delete import (
    delete_imported_sql_row_with_config,
)
from data_ingestion.excel_to_sql.dashboard_filters import (
    _audit_chart_bucket,
    _audit_time_window,
    _append_time_filters,
    _contains_filter,
    _normalize_destination_table_filters,
    _parse_payload,
    _where_clause,
)
from data_ingestion.excel_to_sql.mock_sql import (
    mock_dashboard_payload,
    mock_delete_imported_sql_row,
)
from data_ingestion.excel_to_sql.dashboard_sql import (
    _audit_table,
    _column_exists,
    _connect,
    _fetch_all_dicts,
    _table_exists,
)
from data_ingestion.excel_to_sql.ingest import (
    get_nested,
    load_json_config,
    quote_object_path,
)


def discover_dashboard_tasks(
    config_dir: str | Path = "config/excel_to_sql",
) -> list[dict[str, Any]]:
    root = Path(config_dir)
    if not root.exists():
        return []

    tasks: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
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
    username_filter: str | list[str] | None = None,
    destination_table_filter: str | list[str] | None = None,
    row_no_filter: int | None = None,
    message_filter: str | None = None,
    hash_value_filter: str | None = None,
    payload_filter: str | None = None,
    page: int = 1,
    chart_bucket: str | None = "day",
) -> dict[str, Any]:
    if should_prefer_mock_runtime():
        return mock_dashboard_payload(
            config_path,
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
        )

    cfg = load_json_config(config_path)
    task_name = _dashboard_name(cfg, Path(config_path))
    table = _audit_table(cfg)
    quoted_table = quote_object_path(table)
    days, start_dt, end_dt = _audit_time_window(days, start_ts, end_ts)
    chart_bucket, chart_bucket_label, chart_bucket_sql = _audit_chart_bucket(
        chart_bucket
    )
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
                    "chart_bucket": chart_bucket,
                    "chart_bucket_label": chart_bucket_label,
                    "exists": False,
                    "summary": [],
                    "daily": [],
                    "files": [],
                    "destination_table_options": [],
                    "username_options": [],
                    "recent": [],
                    "recent_paging": {"page": page, "page_size": limit, "total": 0},
                }
            has_username_column = _column_exists(cursor, table, "username")

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

            destination_table_option_conditions = list(time_conditions)
            destination_table_option_conditions.extend(
                [
                    "destination_table IS NOT NULL",
                    "LTRIM(RTRIM(destination_table)) <> ''",
                ]
            )
            destination_table_options = [
                str(row.get("destination_table") or "").strip()
                for row in _fetch_all_dicts(
                    cursor,
                    f"""
SELECT DISTINCT TOP (200) destination_table
FROM {quoted_table}
{_where_clause(destination_table_option_conditions)}
ORDER BY destination_table
""",
                    tuple(time_params),
                )
                if str(row.get("destination_table") or "").strip()
            ]
            user_expr_parts = []
            if has_username_column:
                user_expr_parts.append("NULLIF(username, '')")
            user_expr_parts.extend(
                [
                    "NULLIF(JSON_VALUE(row_payload, '$.audit_actor'), '')",
                    "NULLIF(JSON_VALUE(row_payload, '$.audit_user'), '')",
                    "NULLIF(JSON_VALUE(row_payload, '$.actor'), '')",
                ]
            )
            user_expr = f"COALESCE({', '.join(user_expr_parts)})"
            user_option_conditions = list(time_conditions)
            user_option_conditions.append(f"{user_expr} IS NOT NULL")
            user_options = [
                str(row.get("username") or "").strip()
                for row in _fetch_all_dicts(
                    cursor,
                    f"""
SELECT DISTINCT TOP (200) {user_expr} AS username
FROM {quoted_table}
{_where_clause(user_option_conditions)}
ORDER BY username
""",
                    tuple(time_params),
                )
                if str(row.get("username") or "").strip()
            ]

            recent_conditions = list(time_conditions)
            recent_params = list(time_params)
            clean_status = str(status_filter or "").strip()
            clean_source_file = str(source_file_filter or "").strip()
            clean_usernames = _normalize_destination_table_filters(username_filter)
            clean_destination_tables = _normalize_destination_table_filters(
                destination_table_filter
            )
            clean_message = str(message_filter or "").strip()
            clean_hash = str(hash_value_filter or "").strip()
            clean_payload = str(payload_filter or "").strip()
            if clean_status:
                recent_conditions.append("status = ?")
                recent_params.append(clean_status)
            if clean_source_file:
                recent_conditions.append("source_file LIKE ?")
                recent_params.append(_contains_filter(clean_source_file))
            if clean_usernames:
                placeholders = ", ".join("?" for _ in clean_usernames)
                recent_conditions.append(f"{user_expr} IN ({placeholders})")
                recent_params.extend(clean_usernames)
            if clean_destination_tables:
                placeholders = ", ".join("?" for _ in clean_destination_tables)
                recent_conditions.append(f"destination_table IN ({placeholders})")
                recent_params.extend(clean_destination_tables)
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
SELECT {chart_bucket_sql} AS bucket_start, COUNT(1) AS count
FROM {quoted_table}
{recent_where}
GROUP BY {chart_bucket_sql}
ORDER BY bucket_start ASC
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
        {user_expr} AS username,
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
    username,
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
                "chart_bucket": chart_bucket,
                "chart_bucket_label": chart_bucket_label,
                "recent_filters": {
                    "status": clean_status,
                    "source_file": clean_source_file,
                    "username": clean_usernames,
                    "destination_table": clean_destination_tables,
                    "row_no": row_no_filter,
                    "message": clean_message,
                    "hash_value": clean_hash,
                    "payload": clean_payload,
                },
                "filtered_daily": filtered_daily,
                "filtered_series": filtered_daily,
                "recent_paging": {
                    "page": page,
                    "page_size": limit,
                    "total": recent_total,
                },
                "exists": True,
                "summary": summary,
                "daily": daily,
                "files": files,
                "destination_table_options": destination_table_options,
                "username_options": user_options,
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
    if should_prefer_mock_runtime():
        return mock_delete_imported_sql_row(
            config_path, hash_value=hash_value, actor=actor, reason=reason
        )

    cfg = load_json_config(config_path)
    return delete_imported_sql_row_with_config(
        cfg=cfg,
        config_path=config_path,
        hash_value=hash_value,
        actor=actor,
        reason=reason,
        audit_table=_audit_table(cfg),
        connect=_connect,
        table_exists=_table_exists,
    )
