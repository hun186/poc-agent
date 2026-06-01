from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .models import RowResult
from .sql_utils import quote_object_path
from .utils import json_safe


def _execute_audit_rows_without_fast_mode(cursor, sql: str, params: Sequence[tuple[Any, ...]]):
    """Run audit inserts one row at a time without pyodbc fast mode.

    Some ODBC driver/pyodbc combinations can terminate the interpreter while
    binding Unicode/large-text audit payloads with ``fast_executemany=True`` or
    even when ``executemany`` is called after fast mode was used on the cursor.
    The destination data import can still opt in to fast batching, but audit
    rows are written through a fresh non-fast cursor and individual ``execute``
    calls so driver errors stay in the normal Python exception path instead of
    crashing the process in native code.
    """

    audit_cursor = cursor
    should_close = False
    connection = getattr(cursor, "connection", None)
    if connection is not None and hasattr(connection, "cursor"):
        audit_cursor = connection.cursor()
        should_close = True

    original_fast_executemany = getattr(audit_cursor, "fast_executemany", None)
    should_restore = original_fast_executemany is not None

    if should_restore and original_fast_executemany:
        audit_cursor.fast_executemany = False
    try:
        for row_params in params:
            audit_cursor.execute(sql, row_params)
    finally:
        if should_restore and original_fast_executemany:
            audit_cursor.fast_executemany = original_fast_executemany
        if should_close:
            audit_cursor.close()


def ensure_audit_table(cursor, audit_table: str):
    object_name = audit_table.replace("'", "''")
    sql = f"""
IF OBJECT_ID(N'{object_name}', N'U') IS NULL
BEGIN
    CREATE TABLE {quote_object_path(audit_table)} (
        audit_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        run_id NVARCHAR(64) NOT NULL,
        source_file NVARCHAR(1024) NOT NULL,
        sheet_name NVARCHAR(255) NULL,
        row_no INT NULL,
        hash_value CHAR(64) NULL,
        destination_table NVARCHAR(512) NOT NULL,
        status NVARCHAR(32) NOT NULL,
        message NVARCHAR(MAX) NULL,
        row_payload NVARCHAR(MAX) NULL,
        processed_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
"""
    cursor.execute(sql)


def insert_audit_rows(
    cursor,
    *,
    audit_table: str,
    run_id: str,
    source_file: Path,
    sheet_name: str,
    destination_table: str,
    row_results: Sequence[RowResult],
):
    if not row_results:
        return
    sql = f"""
INSERT INTO {quote_object_path(audit_table)}
(run_id, source_file, sheet_name, row_no, hash_value, destination_table, status, message, row_payload)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
    params = [
        (
            run_id,
            str(source_file),
            sheet_name,
            result.row_no,
            result.hash_value or None,
            destination_table,
            result.status,
            result.message,
            json.dumps(result.row_payload, ensure_ascii=False, default=json_safe),
        )
        for result in row_results
    ]
    _execute_audit_rows_without_fast_mode(cursor, sql, params)


def build_header_audit_results(mappings: Sequence[Dict[str, Any]], header_row: int) -> List[RowResult]:
    results: List[RowResult] = []
    for mapping in mappings:
        match_type = str(mapping.get("match_type", ""))
        if match_type in {"exact", "index", "letter"}:
            continue

        expected = str(mapping.get("source_label", ""))
        actual = str(mapping.get("actual_source_label", ""))
        message = mapping.get("header_message") or f"設定欄名 {expected} 智慧比對到 Excel 欄名 {actual}"
        results.append(
            RowResult(
                row_no=header_row,
                hash_value="",
                status="header_smart_match",
                message=str(message),
                row_payload={
                    "expected_source_column": expected,
                    "actual_source_column": actual,
                    "dest_field": mapping.get("dest_field"),
                    "match_type": match_type,
                    "source_index": mapping.get("source_index"),
                },
            )
        )
    return results
