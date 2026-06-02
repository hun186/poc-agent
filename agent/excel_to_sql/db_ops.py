"""Database batch helpers for Excel-to-SQL ingestion."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from .models import RowResult
from .sql_utils import build_select_existing_hashes_sql
from .utils import chunked


def get_existing_hashes(cursor, *, table: str, hash_field: str, hash_values: Sequence[str]) -> set[str]:
    hashes = sorted({value for value in hash_values if value})
    if not hashes:
        return set()

    existing: set[str] = set()
    for batch in chunked(hashes, 900):
        cursor.execute(build_select_existing_hashes_sql(table, hash_field, len(batch)), batch)
        existing.update(str(row[0]) for row in cursor.fetchall())
    return existing


def insert_batch_with_fallback(
    cursor,
    *,
    insert_sql: str,
    rows: Sequence[Tuple[Any, ...]],
    row_contexts: Sequence[Tuple[int, str, Dict[str, Any]]],
) -> Tuple[List[RowResult], List[Tuple[str, Tuple[Any, ...]]]]:
    try:
        cursor.executemany(insert_sql, rows)
        return [
            RowResult(row_no=row_no, hash_value=hash_value, status="inserted", row_payload=payload)
            for row_no, hash_value, payload in row_contexts
        ], []
    except Exception as exc:
        cursor.connection.rollback()
        results: List[RowResult] = []
        inserted_rows: List[Tuple[str, Tuple[Any, ...]]] = []

        # A failed pyodbc fast_executemany call can leave the cursor in an
        # unsafe state for subsequent single-row execute calls.  Retrying on
        # the same fast cursor has been observed to terminate Python in native
        # code instead of raising a catchable exception.  Use a fresh, non-fast
        # cursor for the slower row-by-row diagnostic fallback so bad rows are
        # reported without risking a process crash.
        fallback_cursor = cursor.connection.cursor()
        try:
            if hasattr(fallback_cursor, "fast_executemany"):
                fallback_cursor.fast_executemany = False

            for row_values, (row_no, hash_value, payload) in zip(rows, row_contexts):
                try:
                    fallback_cursor.execute(insert_sql, row_values)
                    fallback_cursor.connection.commit()
                    inserted_rows.append((hash_value, row_values))
                    results.append(RowResult(row_no=row_no, hash_value=hash_value, status="inserted", row_payload=payload))
                except Exception as row_exc:
                    fallback_cursor.connection.rollback()
                    results.append(
                        RowResult(
                            row_no=row_no,
                            hash_value=hash_value,
                            status="failed",
                            message=f"批次失敗後逐筆重試仍失敗：{row_exc}; 原批次錯誤：{exc}",
                            row_payload=payload,
                        )
                    )
        finally:
            fallback_cursor.close()

        return results, inserted_rows
