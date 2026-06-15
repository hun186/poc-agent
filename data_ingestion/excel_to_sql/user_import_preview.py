from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import DEFAULT_HASH_FIELD, DEFAULT_HASH_FIELD_TYPE
from .db_ops import get_existing_hashes
from .ingest import load_json_config
from .sql_utils import build_conn_str_from_config, ensure_destination_table
from .user_import_storage import public_record, read_registry, utc_now, write_registry
from .utils import get_nested, require_nested
from .workbook import iter_excel_rows, open_workbook_headers, read_column_mappings


def _preview_file(
    config_path: str, cfg: dict[str, Any], excel_path: Path
) -> dict[str, Any]:
    table = str(require_nested(cfg, "destination.table"))
    hash_field = str(
        get_nested(cfg, "destination.hash_field", DEFAULT_HASH_FIELD)
        or DEFAULT_HASH_FIELD
    )
    batch_size = max(1, int(get_nested(cfg, "import.batch_size", 500) or 500))
    skip_empty_rows = bool(get_nested(cfg, "import.skip_empty_rows", True))
    auto_create_table = bool(get_nested(cfg, "destination.auto_create_table", True))
    default_field_type = str(
        get_nested(cfg, "destination.default_field_type", "NVARCHAR(MAX)")
        or "NVARCHAR(MAX)"
    )
    hash_field_type = str(
        get_nested(cfg, "destination.hash_field_type", DEFAULT_HASH_FIELD_TYPE)
        or DEFAULT_HASH_FIELD_TYPE
    )
    create_hash_index = bool(get_nested(cfg, "destination.create_hash_index", True))
    sheet_headers = open_workbook_headers(config_path, cfg, excel_path)
    header_row = sheet_headers[0].header_row
    start_row = int(
        get_nested(cfg, "source.start_row", header_row + 1) or (header_row + 1)
    )
    end_row = int(get_nested(cfg, "source.end_row", 0) or 0)

    import pyodbc

    conn = pyodbc.connect(build_conn_str_from_config(cfg))
    cursor = conn.cursor()
    if auto_create_table:
        first_mappings = read_column_mappings(cfg, sheet_headers[0].header_map)
        created_table_fields = ensure_destination_table(
            cursor,
            table=table,
            mappings=first_mappings,
            default_field_type=default_field_type,
            hash_field=hash_field,
            hash_field_type=hash_field_type,
            create_hash_index=create_hash_index,
        )
        if created_table_fields:
            conn.commit()
    totals = {"will_insert": 0, "duplicate": 0, "failed": 0, "total_rows": 0}
    samples: list[dict[str, Any]] = []
    failure_summary: dict[str, int] = {}
    seen: set[str] = set()
    try:
        for sheet in sheet_headers:
            mappings = read_column_mappings(cfg, sheet.header_map)
            row_iter = iter_excel_rows(
                excel_path=excel_path,
                sheet_name=sheet.sheet_name,
                header_row=sheet.header_row,
                start_row=start_row,
                end_row=end_row,
                mappings=mappings,
                skip_empty_rows=skip_empty_rows,
            )
            batch: list[Any] = []
            for row in row_iter:
                batch.append(row)
                if len(batch) >= batch_size:
                    _scan_batch(
                        cursor,
                        table,
                        hash_field,
                        batch,
                        seen,
                        totals,
                        samples,
                        failure_summary,
                        sheet.sheet_name,
                    )
                    batch = []
            if batch:
                _scan_batch(
                    cursor,
                    table,
                    hash_field,
                    batch,
                    seen,
                    totals,
                    samples,
                    failure_summary,
                    sheet.sheet_name,
                )
    finally:
        cursor.close()
        conn.close()
    return {
        **totals,
        "sheets": [s.sheet_name for s in sheet_headers],
        "failure_summary": failure_summary,
        "samples": samples[:50],
        "scanned_at": utc_now(),
    }


def _scan_batch(
    cursor,
    table: str,
    hash_field: str,
    batch: list[Any],
    seen: set[str],
    totals: dict[str, int],
    samples: list[dict[str, Any]],
    failure_summary: dict[str, int],
    sheet_name: str,
) -> None:
    existing = get_existing_hashes(
        cursor,
        table=table,
        hash_field=hash_field,
        hash_values=[item[3] for item in batch],
    )
    for row_no, record, source_values, hash_value, invalid_message in batch:
        totals["total_rows"] += 1
        status = "will_insert"
        message = ""
        if invalid_message:
            status = "failed"
            message = invalid_message
        elif hash_value in existing or hash_value in seen:
            status = "duplicate"
            message = "hash_value 已存在或同次預掃描重複，實際匯入會略過"
        else:
            seen.add(hash_value)
        totals[status] += 1
        if status == "failed":
            failure_summary[message] = failure_summary.get(message, 0) + 1
        if len(samples) < 50 and status != "will_insert":
            samples.append(
                {
                    "sheet_name": sheet_name,
                    "row_no": row_no,
                    "status": status,
                    "message": message,
                    "hash_value": hash_value,
                    "source": source_values,
                    "destination": record,
                }
            )


def preview_record(
    record_id: str, *, username: str, is_superuser: bool
) -> dict[str, Any]:
    data = read_registry()
    for record in data["records"]:
        if record.get("id") == record_id:
            if not is_superuser and record.get("username") != username:
                raise PermissionError("不可檢視其他使用者的匯入記錄。")
            if record.get("status") == "deleted":
                raise ValueError("已刪除的匯入記錄不可預掃描。")
            cfg = load_json_config(str(record["config_path"]))
            preview = _preview_file(
                str(record["config_path"]), cfg, Path(str(record["stored_path"]))
            )
            record["preview"] = preview
            record["status"] = "previewed"
            record["updated_at"] = utc_now()
            write_registry(data)
            return {"record": public_record(record), "preview": preview}
    raise FileNotFoundError(f"找不到匯入記錄：{record_id}")
