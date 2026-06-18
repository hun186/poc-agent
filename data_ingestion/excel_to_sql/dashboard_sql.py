from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from data_ingestion.excel_to_sql.ingest import (
    DEFAULT_AUDIT_TABLE,
    build_conn_str_from_config,
    get_nested,
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


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


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        "SELECT CASE WHEN COL_LENGTH(?, ?) IS NULL THEN 0 ELSE 1 END",
        table,
        column,
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _fetch_all_dicts(
    cursor, sql: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return [_row_to_dict(cursor, row) for row in cursor.fetchall()]
