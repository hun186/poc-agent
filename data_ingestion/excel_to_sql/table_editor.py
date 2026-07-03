from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from data_ingestion.excel_to_sql.dashboard_filters import _coerce_utc_datetime
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
    "_import_username",
    "_imported_at",
    "_source_excel",
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


def _normalize_filter_values(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for raw in raw_values:
        for part in str(raw or "").split(","):
            clean = part.strip()
            if clean and clean not in result:
                result.append(clean)
    return result


def _audit_username_expr(alias: str = '') -> str:
    prefix = f'{alias}.' if alias else ''
    return (
        f"COALESCE(NULLIF({prefix}username, ''), "
        f"NULLIF(JSON_VALUE({prefix}row_payload, '$.audit_actor'), ''), "
        f"NULLIF(JSON_VALUE({prefix}row_payload, '$.audit_user'), ''), "
        f"NULLIF(JSON_VALUE({prefix}row_payload, '$.actor'), ''))"
    )


def _load_audit_username_options(cursor, audit_table: str, destination_table: str) -> list[str]:
    expr = _audit_username_expr()
    cursor.execute(
        f"SELECT DISTINCT TOP (200) {expr} AS username "
        f"FROM {quote_object_path(audit_table)} "
        "WHERE destination_table = ? AND " + expr + " IS NOT NULL ORDER BY username",
        destination_table,
    )
    values: list[str] = []
    for row in cursor.fetchall():
        data = _row_to_dict(cursor, row)
        username = str(data.get("username") or "").strip()
        if username and username not in values:
            values.append(username)
    return values


def _audit_metadata_by_hash(cursor, audit_table: str, destination_table: str, hash_values: list[str]) -> dict[str, dict[str, Any]]:
    clean_hashes = [str(value or "").strip() for value in hash_values if str(value or "").strip()]
    if not clean_hashes:
        return {}
    expr = _audit_username_expr("aud")
    placeholders = ", ".join("?" for _ in clean_hashes)
    cursor.execute(
        f"""
WITH ranked_audit AS (
    SELECT
        aud.hash_value,
        {expr} AS username,
        aud.source_file,
        aud.processed_at,
        ROW_NUMBER() OVER (
            PARTITION BY aud.hash_value
            ORDER BY
                CASE WHEN aud.source_file IN ('dashboard', 'sql-source-editor') THEN 1 ELSE 0 END,
                aud.processed_at DESC
        ) AS rn
    FROM {quote_object_path(audit_table)} aud
    WHERE aud.destination_table = ? AND aud.hash_value IN ({placeholders})
)
SELECT hash_value, username, source_file, processed_at
FROM ranked_audit
WHERE rn = 1
""",
        destination_table,
        *clean_hashes,
    )
    result: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall():
        data = _row_to_dict(cursor, row)
        hash_value = str(data.get("hash_value") or "").strip()
        if hash_value:
            result[hash_value] = {
                "username": str(data.get("username") or "").strip(),
                "source_file": str(data.get("source_file") or "").strip(),
                "processed_at": data.get("processed_at"),
            }
    return result


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



def _sql_source_filter_conditions(
    *,
    table: str,
    audit_table: str,
    hash_field: str,
    columns: list[dict[str, Any]],
    q: str = "",
    source_file_filter: str = "",
    row_no_filter: int | None = None,
    hash_value_filter: str = "",
    payload_filter: str = "",
    username_filter: str | list[str] | None = None,
    import_start_ts: str | None = None,
    import_end_ts: str | None = None,
) -> tuple[str, list[Any]]:
    search_cols = [col["name"] for col in columns[:12]]
    params: list[Any] = []
    conditions: list[str] = []
    available = {str(col["name"]).lower(): str(col["name"]) for col in columns}
    table_sql = quote_object_path(table)
    audit_sql = quote_object_path(audit_table)
    clean_q = str(q or "").strip()
    if clean_q:
        like = f"%{clean_q}%"
        conditions.append("(" + " OR ".join(
            f"CAST({quote_ident(col)} AS NVARCHAR(MAX)) LIKE ?" for col in search_cols
        ) + ")")
        params.extend([like for _ in search_cols])
    clean_source_file = str(source_file_filter or "").strip()
    if clean_source_file:
        conditions.append(
            f"EXISTS (SELECT 1 FROM {audit_sql} aud "
            f"WHERE aud.destination_table = ? AND aud.hash_value = {table_sql}.{quote_ident(hash_field)} "
            "AND aud.source_file LIKE ?)"
        )
        params.extend([table, f"%{clean_source_file}%"])
    start_dt = _coerce_utc_datetime(import_start_ts)
    end_dt = _coerce_utc_datetime(import_end_ts, end_of_day=True)
    if start_dt and end_dt and start_dt > end_dt:
        raise ValueError("匯入執行起始時間不可晚於結束時間。")
    if start_dt:
        conditions.append(
            f"EXISTS (SELECT 1 FROM {audit_sql} aud "
            f"WHERE aud.destination_table = ? AND aud.hash_value = {table_sql}.{quote_ident(hash_field)} "
            "AND aud.processed_at >= ?)"
        )
        params.extend([table, start_dt])
    if end_dt:
        conditions.append(
            f"EXISTS (SELECT 1 FROM {audit_sql} aud "
            f"WHERE aud.destination_table = ? AND aud.hash_value = {table_sql}.{quote_ident(hash_field)} "
            "AND aud.processed_at <= ?)"
        )
        params.extend([table, end_dt])
    if row_no_filter is not None and "row_no" in available:
        conditions.append(f"{quote_ident(available['row_no'])} = ?")
        params.append(int(row_no_filter))
    clean_hash_filter = str(hash_value_filter or "").strip()
    if clean_hash_filter and hash_field.lower() in available:
        conditions.append(f"CAST({quote_ident(available[hash_field.lower()])} AS NVARCHAR(MAX)) LIKE ?")
        params.append(f"%{clean_hash_filter}%")
    clean_usernames = _normalize_filter_values(username_filter)
    if clean_usernames:
        audit_user_expr = _audit_username_expr("aud")
        placeholders = ", ".join("?" for _ in clean_usernames)
        conditions.append(
            f"EXISTS (SELECT 1 FROM {audit_sql} aud "
            f"WHERE aud.destination_table = ? AND aud.hash_value = {table_sql}.{quote_ident(hash_field)} "
            f"AND {audit_user_expr} IN ({placeholders}))"
        )
        params.append(table)
        params.extend(clean_usernames)
    clean_payload = str(payload_filter or "").strip()
    if clean_payload:
        payload_cols = [col["name"] for col in columns if str(col.get("name") or "").lower() not in {"source_file", "row_no", hash_field.lower(), *SYSTEM_COLUMNS}]
        if payload_cols:
            conditions.append("(" + " OR ".join(f"CAST({quote_ident(col)} AS NVARCHAR(MAX)) LIKE ?" for col in payload_cols[:24]) + ")")
            params.extend([f"%{clean_payload}%" for _ in payload_cols[:24]])
    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where_sql, params


def _numeric_columns(columns: list[dict[str, Any]], hash_field: str) -> list[str]:
    numeric_types = {"bigint", "int", "smallint", "tinyint", "decimal", "numeric", "float", "real", "money", "smallmoney"}
    blocked = {hash_field.lower(), *SYSTEM_COLUMNS}
    result = []
    for col in columns:
        name = str(col.get("name") or "")
        data_type = str(col.get("data_type") or "").lower()
        if name and name.lower() not in blocked and data_type in numeric_types:
            result.append(name)
    return result

def list_sql_source_rows(
    config_path: str,
    *,
    q: str = "",
    source_file_filter: str = "",
    row_no_filter: int | None = None,
    hash_value_filter: str = "",
    payload_filter: str = "",
    username_filter: str | list[str] | None = None,
    import_start_ts: str | None = None,
    import_end_ts: str | None = None,
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
            audit_table = _audit_table(cfg)
            username_options = _load_audit_username_options(cursor, audit_table, table)
            where_sql, params = _sql_source_filter_conditions(
                table=table,
                audit_table=audit_table,
                hash_field=hash_field,
                columns=columns,
                q=q,
                source_file_filter=source_file_filter,
                row_no_filter=row_no_filter,
                hash_value_filter=hash_value_filter,
                payload_filter=payload_filter,
                username_filter=username_filter,
                import_start_ts=import_start_ts,
                import_end_ts=import_end_ts,
            )
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
            audit_metadata = _audit_metadata_by_hash(cursor, audit_table, table, [row.get(hash_field) for row in rows])
            for row in rows:
                meta = audit_metadata.get(str(row.get(hash_field) or "").strip(), {})
                row["_import_username"] = meta.get("username") or str(row.get("_import_username") or "")
                row["_imported_at"] = meta.get("processed_at") or str(row.get("_imported_at") or "")
                row["_source_excel"] = meta.get("source_file") or str(row.get("_source_excel") or "")
            virtual_columns = [
                ("_import_username", "nvarchar"),
                ("_imported_at", "datetime2"),
                ("_source_excel", "nvarchar"),
            ]
            existing_column_names = {str(col.get("name") or "").lower() for col in columns}
            for name, data_type in virtual_columns:
                if name.lower() not in existing_column_names:
                    columns.append({"name": name, "data_type": data_type, "nullable": True})
            return {
                "ok": True,
                "config_path": str(Path(config_path)),
                "destination_table": table,
                "hash_field": hash_field,
                "columns": columns,
                "editable_columns": _editable_column_names(columns, hash_field),
                "username_options": username_options,
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




def _audit_attribute_groups(
    cursor,
    *,
    table: str,
    audit_table: str,
    hash_field: str,
    where_sql: str,
    params: list[Any],
    top: int,
) -> list[dict[str, Any]]:
    table_sql = quote_object_path(table)
    audit_sql = quote_object_path(audit_table)
    hash_sql = quote_ident(hash_field)
    username_expr = _audit_username_expr("aud")
    base_cte = f"""
WITH filtered_rows AS (
    SELECT CAST({hash_sql} AS NVARCHAR(128)) AS hash_value
    FROM {table_sql}{where_sql}
), ranked_audit AS (
    SELECT
        aud.hash_value,
        {username_expr} AS username,
        aud.source_file,
        aud.processed_at,
        ROW_NUMBER() OVER (
            PARTITION BY aud.hash_value
            ORDER BY
                CASE WHEN aud.source_file IN ('dashboard', 'sql-source-editor') THEN 1 ELSE 0 END,
                aud.processed_at DESC
        ) AS rn
    FROM {audit_sql} aud
    INNER JOIN filtered_rows fr ON fr.hash_value = aud.hash_value
    WHERE aud.destination_table = ?
), latest_audit AS (
    SELECT hash_value, username, source_file, processed_at
    FROM ranked_audit
    WHERE rn = 1
)
"""
    dimensions = [
        ("import_username", "依匯入使用者", "COALESCE(NULLIF(CAST(la.username AS NVARCHAR(4000)), ''), '-')"),
        ("source_excel", "依來源 Excel", "COALESCE(NULLIF(CAST(la.source_file AS NVARCHAR(4000)), ''), '-')"),
        ("import_date", "依匯入日期", "COALESCE(CONVERT(NVARCHAR(10), la.processed_at, 23), '-')"),
    ]
    groups: list[dict[str, Any]] = []
    query_params = tuple(params + [table])
    for key, label, value_expr in dimensions:
        cursor.execute(
            base_cte
            + f"""
SELECT TOP ({top}) {value_expr} AS value, COUNT(*) AS count
FROM filtered_rows fr
LEFT JOIN latest_audit la ON la.hash_value = fr.hash_value
GROUP BY {value_expr}
ORDER BY COUNT(*) DESC, value
""",
            query_params,
        )
        groups.append({
            "key": key,
            "label": label,
            "items": [_row_to_dict(cursor, row) for row in cursor.fetchall()],
        })
    return groups

def sql_source_stats(
    config_path: str,
    *,
    q: str = "",
    source_file_filter: str = "",
    row_no_filter: int | None = None,
    hash_value_filter: str = "",
    payload_filter: str = "",
    username_filter: str | list[str] | None = None,
    import_start_ts: str | None = None,
    import_end_ts: str | None = None,
    group_by: str = "",
    top: int = 20,
    connect: Callable[[dict[str, Any]], Any] = _connect,
) -> dict[str, Any]:
    cfg = load_json_config(config_path)
    table = _destination_table(cfg)
    hash_field = _hash_field(cfg)
    top = min(max(int(top or 20), 1), 100)
    conn = connect(cfg)
    try:
        cursor = conn.cursor()
        try:
            columns = _load_columns(cursor, table)
            if not columns:
                raise ValueError(f"找不到 SQL table 欄位資訊：{table}")
            audit_table = _audit_table(cfg)
            where_sql, params = _sql_source_filter_conditions(
                table=table, audit_table=audit_table, hash_field=hash_field, columns=columns,
                q=q, source_file_filter=source_file_filter, row_no_filter=row_no_filter,
                hash_value_filter=hash_value_filter, payload_filter=payload_filter,
                username_filter=username_filter, import_start_ts=import_start_ts, import_end_ts=import_end_ts,
            )
            table_sql = quote_object_path(table)
            cursor.execute(f"SELECT COUNT(*) AS total FROM {table_sql}{where_sql}", tuple(params))
            count_row = cursor.fetchone()
            total = int(count_row[0] if count_row else 0)
            allowed_group_columns = [str(col.get("name") or "") for col in columns if str(col.get("name") or "").lower() not in {hash_field.lower(), *SYSTEM_COLUMNS}]
            selected_group = str(group_by or "").strip()
            if selected_group not in allowed_group_columns:
                selected_group = allowed_group_columns[0] if allowed_group_columns else ""
            groups: list[dict[str, Any]] = []
            if selected_group:
                group_expr = quote_ident(selected_group)
                cursor.execute(
                    f"SELECT TOP ({top}) CAST({group_expr} AS NVARCHAR(4000)) AS value, COUNT(*) AS count "
                    f"FROM {table_sql}{where_sql} GROUP BY CAST({group_expr} AS NVARCHAR(4000)) ORDER BY COUNT(*) DESC, value",
                    tuple(params),
                )
                groups = [_row_to_dict(cursor, row) for row in cursor.fetchall()]
            numeric_summaries: list[dict[str, Any]] = []
            for col in _numeric_columns(columns, hash_field)[:12]:
                col_sql = quote_ident(col)
                cursor.execute(
                    f"SELECT COUNT({col_sql}) AS count, MIN({col_sql}) AS min, MAX({col_sql}) AS max, AVG(CAST({col_sql} AS FLOAT)) AS avg, SUM(CAST({col_sql} AS FLOAT)) AS sum "
                    f"FROM {table_sql}{where_sql}",
                    tuple(params),
                )
                row = _row_to_dict(cursor, cursor.fetchone())
                row["column"] = col
                numeric_summaries.append(row)
            attribute_groups = _audit_attribute_groups(
                cursor,
                table=table,
                audit_table=audit_table,
                hash_field=hash_field,
                where_sql=where_sql,
                params=params,
                top=top,
            )
            if selected_group:
                attribute_groups.append({
                    "key": "selected_data_column",
                    "label": f"依資料欄位：{selected_group}",
                    "items": groups,
                })
            return {
                "ok": True,
                "config_path": str(Path(config_path)),
                "destination_table": table,
                "hash_field": hash_field,
                "total": total,
                "columns": columns,
                "groupable_columns": allowed_group_columns,
                "group_by": selected_group,
                "groups": groups,
                "attribute_groups": attribute_groups,
                "numeric_summaries": numeric_summaries,
                "username_options": _load_audit_username_options(cursor, audit_table, table),
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
