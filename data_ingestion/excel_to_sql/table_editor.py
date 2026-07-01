from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from data_ingestion.excel_to_sql.dashboard_sql import (
    _audit_table,
    _connect,
    _json_safe,
    _row_to_dict,
    _table_exists,
)
from data_ingestion.excel_to_sql.ingest import get_nested, load_json_config, quote_ident, quote_object_path

SYSTEM_COLUMNS = {
    "hash_value",
    "created_at",
    "updated_at",
    "imported_at",
    "processed_at",
    "run_id",
    "source_file",
    "sheet_name",
    "row_no",
}


def _destination_table(cfg: dict[str, Any]) -> str:
    table = str(get_nested(cfg, "destination.table", "") or "").strip()
    if not table:
        raise ValueError("設定檔缺少 destination.table，無法開啟 SQL 來源資料編輯器。")
    return table


def _hash_field(cfg: dict[str, Any]) -> str:
    field = str(get_nested(cfg, "destination.hash_field", "hash_value") or "hash_value").strip()
    if not field:
        raise ValueError("destination.hash_field 不可為空。")
    return field


def _split_table_name(table: str) -> tuple[str, str]:
    parts = [part.strip("[] ") for part in table.split(".") if part.strip()]
    if len(parts) == 1:
        return "dbo", parts[0]
    return parts[-2], parts[-1]


def _load_columns(cursor, table: str) -> list[dict[str, Any]]:
    schema, name = _split_table_name(table)
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        schema,
        name,
    )
    rows = cursor.fetchall()
    columns: list[dict[str, Any]] = []
    for row in rows:
        col = _row_to_dict(cursor, row)
        name_value = str(col.get("COLUMN_NAME") or col.get("column_name") or "")
        data_type = str(col.get("DATA_TYPE") or col.get("data_type") or "")
        nullable = str(col.get("IS_NULLABLE") or col.get("is_nullable") or "").upper() == "YES"
        columns.append({"name": name_value, "data_type": data_type, "nullable": nullable})
    return columns


def _editable_column_names(columns: list[dict[str, Any]], hash_field: str) -> list[str]:
    blocked = {hash_field.lower(), *SYSTEM_COLUMNS}
    return [str(col["name"]) for col in columns if str(col.get("name") or "").lower() not in blocked]


def _write_editor_audit(
    *,
    cursor,
    audit_table: str,
    action: str,
    config_path: str,
    destination_table: str,
    hash_field: str,
    hash_value: str,
    actor: str,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    changes: dict[str, Any] | None = None,
) -> None:
    audit_sql = (
        f"INSERT INTO {quote_object_path(audit_table)} "
        "([run_id], [source_file], [sheet_name], [row_no], [hash_value], "
        "[destination_table], [status], [message], [row_payload]) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    payload = {
        "action": action,
        "actor": actor,
        "reason": reason,
        "config_path": str(Path(config_path)),
        "destination_table": destination_table,
        "hash_field": hash_field,
        "hash_value": hash_value,
        "before": before,
        "after": after,
        "changes": changes or {},
    }
    cursor.execute(
        audit_sql,
        "manual-control",
        "sql-source-editor",
        None,
        None,
        hash_value,
        destination_table,
        action,
        f"user={actor}; action={action}; destination_table={destination_table}; reason={reason}",
        json.dumps(payload, ensure_ascii=False, default=_json_safe),
    )


def _fetch_row_by_hash(cursor, table: str, hash_field: str, hash_value: str) -> dict[str, Any] | None:
    cursor.execute(
        f"SELECT * FROM {quote_object_path(table)} WHERE {quote_ident(hash_field)} = ?",
        hash_value,
    )
    row = cursor.fetchone()
    return _row_to_dict(cursor, row) if row else None


def list_sql_source_rows(
    config_path: str,
    *,
    q: str = "",
    page: int = 1,
    limit: int = 50,
    connect: Callable[[dict[str, Any]], Any] = _connect,
) -> dict[str, Any]:
    cfg = load_json_config(config_path)
    table = _destination_table(cfg)
    hash_field = _hash_field(cfg)
    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 50), 1), 200)
    offset = (page - 1) * limit
    conn = connect(cfg)
    try:
        cursor = conn.cursor()
        try:
            columns = _load_columns(cursor, table)
            if not columns:
                raise ValueError(f"找不到 SQL table 欄位資訊：{table}")
            search_cols = [col["name"] for col in columns[:12]]
            params: list[Any] = []
            where_sql = ""
            clean_q = str(q or "").strip()
            if clean_q:
                like = f"%{clean_q}%"
                where_sql = " WHERE " + " OR ".join(
                    f"CAST({quote_ident(col)} AS NVARCHAR(MAX)) LIKE ?" for col in search_cols
                )
                params = [like for _ in search_cols]
            count_sql = f"SELECT COUNT(*) AS total FROM {quote_object_path(table)}{where_sql}"
            cursor.execute(count_sql, tuple(params))
            count_row = cursor.fetchone()
            total = int(count_row[0] if count_row else 0)
            order_col = hash_field if any(col["name"] == hash_field for col in columns) else columns[0]["name"]
            data_sql = (
                f"SELECT * FROM {quote_object_path(table)}{where_sql} "
                f"ORDER BY {quote_ident(order_col)} OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
            )
            cursor.execute(data_sql, tuple(params + [offset, limit]))
            rows = [_row_to_dict(cursor, row) for row in cursor.fetchall()]
            return {
                "ok": True,
                "config_path": str(Path(config_path)),
                "destination_table": table,
                "hash_field": hash_field,
                "columns": columns,
                "editable_columns": _editable_column_names(columns, hash_field),
                "rows": rows,
                "total": total,
                "page": page,
                "limit": limit,
                "has_more": offset + len(rows) < total,
            }
        finally:
            cursor.close()
    finally:
        conn.close()


def update_sql_source_row(
    config_path: str,
    *,
    hash_value: str,
    changes: dict[str, Any],
    actor: str,
    reason: str,
    connect: Callable[[dict[str, Any]], Any] = _connect,
    table_exists: Callable[[Any, str], bool] = _table_exists,
) -> dict[str, Any]:
    clean_hash = str(hash_value or "").strip()
    if not clean_hash:
        raise ValueError("hash_value 不可為空。")
    if not str(reason or "").strip():
        raise ValueError("編輯 SQL row 需要填寫原因。")
    cfg = load_json_config(config_path)
    table = _destination_table(cfg)
    hash_field = _hash_field(cfg)
    audit_table = _audit_table(cfg)
    conn = connect(cfg)
    try:
        cursor = conn.cursor()
        try:
            columns = _load_columns(cursor, table)
            editable = set(_editable_column_names(columns, hash_field))
            clean_changes = {str(k): v for k, v in (changes or {}).items() if str(k) in editable}
            blocked = sorted(str(k) for k in (changes or {}) if str(k) not in editable)
            if not clean_changes:
                raise ValueError("沒有可更新的欄位；hash/system 欄位不可透過 SQL 來源資料編輯器修改。")
            before = _fetch_row_by_hash(cursor, table, hash_field, clean_hash)
            if before is None:
                raise ValueError("找不到指定 hash_value 的 SQL row。")
            set_sql = ", ".join(f"{quote_ident(col)} = ?" for col in clean_changes)
            cursor.execute(
                f"UPDATE {quote_object_path(table)} SET {set_sql} WHERE {quote_ident(hash_field)} = ?",
                tuple(clean_changes.values()) + (clean_hash,),
            )
            updated_rows = max(int(cursor.rowcount or 0), 0)
            after = _fetch_row_by_hash(cursor, table, hash_field, clean_hash)
            if table_exists(cursor, audit_table):
                _write_editor_audit(
                    cursor=cursor,
                    audit_table=audit_table,
                    action="sql_source_editor.update_row",
                    config_path=config_path,
                    destination_table=table,
                    hash_field=hash_field,
                    hash_value=clean_hash,
                    actor=actor,
                    reason=reason,
                    before=before,
                    after=after,
                    changes=clean_changes,
                )
            conn.commit()
            return {
                "ok": True,
                "status": "sql_source_row_updated" if updated_rows else "sql_source_row_update_not_found",
                "updated_rows": updated_rows,
                "hash_value": clean_hash,
                "config_path": str(Path(config_path)),
                "destination_table": table,
                "hash_field": hash_field,
                "blocked_columns": blocked,
                "row": after,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        conn.close()
