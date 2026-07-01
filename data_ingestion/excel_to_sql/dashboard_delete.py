from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from data_ingestion.excel_to_sql.dashboard_sql import _json_safe, _row_to_dict
from data_ingestion.excel_to_sql.ingest import (
    get_nested,
    quote_ident,
    quote_object_path,
)


def delete_imported_sql_row_with_config(
    *,
    cfg: dict[str, Any],
    config_path: str,
    hash_value: str,
    actor: str,
    reason: str = "",
    audit_table: str,
    connect: Callable[[dict[str, Any]], Any],
    table_exists: Callable[[Any, str], bool],
) -> dict[str, Any]:
    destination_table = str(get_nested(cfg, "destination.table", "") or "").strip()
    if not destination_table:
        raise ValueError("設定檔缺少 destination.table，無法刪除 SQL 資料列。")

    hash_field = str(
        get_nested(cfg, "destination.hash_field", "hash_value") or "hash_value"
    ).strip()
    if not hash_field:
        raise ValueError("destination.hash_field 不可為空。")

    clean_hash = str(hash_value or "").strip()
    if not clean_hash:
        raise ValueError("hash_value 不可為空。")

    conn = connect(cfg)
    try:
        cursor = conn.cursor()
        try:
            select_sql = (
                f"SELECT * FROM {quote_object_path(destination_table)} "
                f"WHERE {quote_ident(hash_field)} = ?"
            )
            cursor.execute(select_sql, clean_hash)
            deleted_row_payloads = [
                _row_to_dict(cursor, row) for row in cursor.fetchall()
            ]

            delete_sql = (
                f"DELETE FROM {quote_object_path(destination_table)} "
                f"WHERE {quote_ident(hash_field)} = ?"
            )
            cursor.execute(delete_sql, clean_hash)
            deleted_rows = max(int(cursor.rowcount or 0), 0)

            status = "sql_deleted" if deleted_rows else "sql_delete_not_found"
            message = (
                f"user={actor}; deleted_rows={deleted_rows}; "
                f"config_path={Path(config_path)}; destination_table={destination_table}; "
                f"hash_field={hash_field}; reason={reason or '(empty)'}"
            )

            if table_exists(cursor, audit_table):
                _write_delete_audit(
                    cursor=cursor,
                    audit_table=audit_table,
                    config_path=config_path,
                    destination_table=destination_table,
                    hash_field=hash_field,
                    clean_hash=clean_hash,
                    actor=actor,
                    reason=reason,
                    deleted_rows=deleted_rows,
                    deleted_row_payloads=deleted_row_payloads,
                    status=status,
                    message=message,
                )

            conn.commit()
            return {
                "ok": True,
                "status": status,
                "deleted_rows": deleted_rows,
                "hash_value": clean_hash,
                "config_path": str(Path(config_path)),
                "destination_table": destination_table,
                "hash_field": hash_field,
                "deleted_row_payloads": deleted_row_payloads,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        conn.close()


def _write_delete_audit(
    *,
    cursor,
    audit_table: str,
    config_path: str,
    destination_table: str,
    hash_field: str,
    clean_hash: str,
    actor: str,
    reason: str,
    deleted_rows: int,
    deleted_row_payloads: list[dict[str, Any]],
    status: str,
    message: str,
) -> None:
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
        "deleted_row_payloads": deleted_row_payloads,
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
