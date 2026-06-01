from __future__ import annotations

import json
from datetime import date, datetime
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
    return str(get_nested(cfg, "audit.table", DEFAULT_AUDIT_TABLE) or DEFAULT_AUDIT_TABLE)


def _table_exists(cursor, table: str) -> bool:
    cursor.execute("SELECT CASE WHEN OBJECT_ID(?, N'U') IS NULL THEN 0 ELSE 1 END", table)
    row = cursor.fetchone()
    return bool(row and row[0])


def _fetch_all_dicts(cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


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


def discover_dashboard_tasks(config_dir: str | Path = "config/excel_to_sql") -> list[dict[str, Any]]:
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
                "destination_table": str(get_nested(cfg, "destination.table", "") or ""),
                "source_directory": str(get_nested(cfg, "source.directory", "") or ""),
            }
        )
    return tasks


def dashboard_payload(config_path: str, *, days: int = 14, limit: int = 100) -> dict[str, Any]:
    cfg = load_json_config(config_path)
    task_name = _dashboard_name(cfg, Path(config_path))
    table = _audit_table(cfg)
    quoted_table = quote_object_path(table)
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), 1000))

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
                    "exists": False,
                    "summary": [],
                    "daily": [],
                    "files": [],
                    "recent": [],
                }

            summary = _fetch_all_dicts(
                cursor,
                f"""
SELECT status, COUNT(1) AS count
FROM {quoted_table}
WHERE processed_at >= DATEADD(day, -?, SYSUTCDATETIME())
GROUP BY status
ORDER BY status
""",
                (days,),
            )

            daily = _fetch_all_dicts(
                cursor,
                f"""
SELECT CONVERT(date, processed_at) AS day, status, COUNT(1) AS count
FROM {quoted_table}
WHERE processed_at >= DATEADD(day, -?, SYSUTCDATETIME())
GROUP BY CONVERT(date, processed_at), status
ORDER BY day DESC, status
""",
                (days,),
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
WHERE processed_at >= DATEADD(day, -?, SYSUTCDATETIME())
GROUP BY source_file
ORDER BY MAX(processed_at) DESC
""",
                (limit, days),
            )

            recent = _fetch_all_dicts(
                cursor,
                f"""
SELECT TOP (?)
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
FROM {quoted_table}
WHERE processed_at >= DATEADD(day, -?, SYSUTCDATETIME())
ORDER BY processed_at DESC, audit_id DESC
""",
                (limit, days),
            )
            for item in recent:
                item["row_payload"] = _parse_payload(item.get("row_payload"))

            return {
                "config_path": str(Path(config_path)),
                "audit_table": table,
                "task_name": task_name,
                "days": days,
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

    hash_field = str(get_nested(cfg, "destination.hash_field", "hash_value") or "hash_value").strip()
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
