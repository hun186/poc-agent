# data_ingestion/excel_to_sql/file_processor.py
"""Per-file Excel ingestion workflow.

This module owns sheet/header resolution, destination-schema preparation,
row de-duplication, SQL inserts, and audit/log writes for a single Excel file.
The CLI/run-level orchestration remains in :mod:`data_ingestion.excel_to_sql.ingest`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from .audit import build_header_audit_results, insert_audit_rows
from .constants import (
    DEFAULT_AUDIT_TABLE,
    DEFAULT_HASH_ALGORITHM,
    DEFAULT_HASH_FIELD,
    DEFAULT_HASH_FIELD_TYPE,
    DEFAULT_HASH_HEX_LENGTH,
)
from .db_ops import get_existing_hashes, insert_batch_with_fallback
from .file_ops import write_log
from .models import FileResult, RowResult
from .sql_utils import (
    build_insert_sql,
    destination_column_exists,
    destination_hash_field_exists,
    ensure_destination_columns,
    ensure_destination_hash_field,
    ensure_destination_table,
    quote_ident,
    sql_string_literal,
    validate_hash_field_type,
)
from .utils import chunked, get_nested, normalize_header_key, require_nested
from .workbook import (
    iter_excel_rows,
    make_hash_value,
    open_workbook_headers,
    parse_excel_column_ref,
    read_column_mappings,
    read_header_map,
    resolve_header_candidate,
)


def _attach_audit_metadata(row_results: list[RowResult], cfg: dict[str, Any]) -> None:
    actor = str(cfg.get("_audit_actor") or "").strip()
    if not actor:
        return
    for result in row_results:
        result.row_payload.setdefault("audit_actor", actor)


def _write_sheet_smart_match_audit(
    *,
    cursor,
    audit_enabled: bool,
    audit_table: str,
    run_id: str,
    excel_path: Path,
    sheet_name: str,
    table: str,
    message: str,
    match_type: str,
    log_dir: Path,
    cfg: dict[str, Any],
):
    if not message:
        return

    print(f"⚠️ 工作表智慧比對：{message}")
    payload = {
        "event": "sheet_smart_match",
        "run_id": run_id,
        "source_file": str(excel_path),
        "sheet_name": sheet_name,
        "match_type": match_type,
        "message": message,
    }
    write_log(log_dir, payload)
    if audit_enabled:
        row_results = [
            RowResult(
                row_no=0,
                hash_value="",
                status="sheet_smart_match",
                message=message,
                row_payload={
                    "actual_sheet_name": sheet_name,
                    "match_type": match_type,
                },
            )
        ]
        _attach_audit_metadata(row_results, cfg)
        insert_audit_rows(
            cursor,
            audit_table=audit_table,
            run_id=run_id,
            source_file=excel_path,
            sheet_name=sheet_name,
            destination_table=table,
            row_results=row_results,
        )
        conn = getattr(cursor, "connection", None)
        if conn is not None:
            conn.commit()


def process_excel_file(
    *,
    config_path: str,
    cfg: Dict[str, Any],
    excel_path: Path,
    conn,
    run_id: str,
    log_dir: Path,
) -> FileResult:
    result = FileResult(file_path=excel_path)
    sheet_headers = open_workbook_headers(config_path, cfg, excel_path)
    first_sheet = sheet_headers[0]
    first_mappings = read_column_mappings(cfg, first_sheet.header_map)

    table = str(require_nested(cfg, "destination.table"))
    hash_field = str(get_nested(cfg, "destination.hash_field", DEFAULT_HASH_FIELD) or DEFAULT_HASH_FIELD)
    auto_create_hash_field = bool(get_nested(cfg, "destination.auto_create_hash_field", True))
    auto_create_missing_fields = bool(get_nested(cfg, "destination.auto_create_missing_fields", True))
    auto_create_table = bool(get_nested(cfg, "destination.auto_create_table", True))
    default_field_type = str(get_nested(cfg, "destination.default_field_type", "NVARCHAR(MAX)") or "NVARCHAR(MAX)")
    hash_field_type = str(
        get_nested(cfg, "destination.hash_field_type", DEFAULT_HASH_FIELD_TYPE)
        or DEFAULT_HASH_FIELD_TYPE
    )
    create_hash_index = bool(get_nested(cfg, "destination.create_hash_index", True))
    dest_fields = [mapping["dest_field"] for mapping in first_mappings]
    if hash_field not in dest_fields:
        dest_fields.append(hash_field)
    insert_sql = build_insert_sql(table, dest_fields)

    batch_size = int(get_nested(cfg, "import.batch_size", 500) or 500)
    if batch_size <= 0:
        raise ValueError("import.batch_size 必須大於 0")

    header_row = first_sheet.header_row
    start_row = int(get_nested(cfg, "source.start_row", header_row + 1) or (header_row + 1))
    end_row = int(get_nested(cfg, "source.end_row", 0) or 0)
    if start_row <= header_row:
        raise ValueError("source.start_row 必須大於 source.header_row")
    if end_row and end_row < start_row:
        raise ValueError("source.end_row 必須大於或等於 source.start_row，或設為 0 表示讀到最後")

    skip_empty_rows = bool(get_nested(cfg, "import.skip_empty_rows", True))
    fast_executemany = bool(get_nested(cfg, "import.fast_executemany", True))
    audit_enabled = bool(get_nested(cfg, "audit.enabled", True))
    audit_table = str(get_nested(cfg, "audit.table", DEFAULT_AUDIT_TABLE) or DEFAULT_AUDIT_TABLE)

    cursor = conn.cursor()
    if fast_executemany:
        cursor.fast_executemany = True

    if auto_create_table:
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
            created_text = ", ".join(f"{field} {field_type}" for field, field_type in created_table_fields.items())
            index_message = "，並建立去重唯一索引" if create_hash_index and hash_field in created_table_fields else ""
            print(f"🛠️ 已自動建立目的資料表：{table}；{created_text}{index_message}")

    if auto_create_missing_fields:
        created_fields = ensure_destination_columns(
            cursor,
            table=table,
            mappings=first_mappings,
            default_field_type=default_field_type,
        )
        if created_fields:
            conn.commit()
            created_text = ", ".join(f"{field} {field_type}" for field, field_type in created_fields.items())
            print(f"🛠️ 已自動新增目的欄位：{table}；{created_text}")
    else:
        missing_fields = [
            field
            for field in dest_fields
            if field != hash_field and not destination_column_exists(cursor, table=table, field=field)
        ]
        if missing_fields:
            raise ValueError(
                f"目的資料表 {table} 缺少欄位：{', '.join(missing_fields)}；"
                "請手動新增，或在設定檔 destination.auto_create_missing_fields 設為 true。"
            )

    if auto_create_hash_field:
        created_hash_field = ensure_destination_hash_field(
            cursor,
            table=table,
            hash_field=hash_field,
            field_type=hash_field_type,
            create_unique_index=create_hash_index,
        )
        if created_hash_field:
            conn.commit()
            index_message = "，並建立唯一索引" if create_hash_index else ""
            print(
                f"🛠️ 已自動新增去重欄位：{table}.{hash_field} "
                f"{validate_hash_field_type(hash_field_type)}{index_message}"
            )
    elif not destination_hash_field_exists(cursor, table=table, hash_field=hash_field):
        raise ValueError(
            f"目的資料表 {table} 缺少去重欄位 {hash_field}；"
            "請手動新增，或在設定檔 destination.auto_create_hash_field 設為 true。"
        )

    print(f"ℹ️ Excel: {excel_path}")
    print(f"ℹ️ Sheets: {', '.join(sheet.sheet_name for sheet in sheet_headers)}")
    print(f"ℹ️ SQL: {insert_sql}")
    print(
        f"ℹ️ 去重機制：以來源欄名與內容組成字串後計算 {DEFAULT_HASH_ALGORITHM} "
        f"hex digest（固定 {DEFAULT_HASH_HEX_LENGTH} 字元 / 256-bit），寫入 {hash_field}，"
        "匯入前會檢查避免重複導入。"
    )
    if audit_enabled:
        print(
            f"ℹ️ Audit table：{audit_table}（由 audit.table 設定；"
            f"未設定時使用預設值 {DEFAULT_AUDIT_TABLE}）"
        )
    else:
        print("ℹ️ Audit table：已停用（audit.enabled=false）")

    try:
        seen_in_run: set[str] = set()
        for sheet in sheet_headers:
            sheet_name = sheet.sheet_name
            header_row = sheet.header_row
            mappings = read_column_mappings(cfg, sheet.header_map)

            _write_sheet_smart_match_audit(
                cursor=cursor,
                audit_enabled=audit_enabled,
                audit_table=audit_table,
                run_id=run_id,
                excel_path=excel_path,
                sheet_name=sheet_name,
                table=table,
                message=sheet.match_message,
                match_type=sheet.match_type,
                log_dir=log_dir,
                cfg=cfg,
            )

            print(f"ℹ️ Sheet: {sheet_name}")
            header_audit_results = build_header_audit_results(mappings, header_row)
            if header_audit_results:
                for header_result in header_audit_results:
                    print(f"⚠️ 欄名智慧比對：{header_result.message}")
                    write_log(
                        log_dir,
                        {
                            "event": "header_smart_match",
                            "run_id": run_id,
                            "source_file": str(excel_path),
                            "sheet_name": sheet_name,
                            "message": header_result.message,
                            "payload": header_result.row_payload,
                        },
                    )
                if audit_enabled:
                    print("ℹ️ 準備寫入欄名智慧比對 audit rows", flush=True)
                    _attach_audit_metadata(header_audit_results, cfg)
                    insert_audit_rows(
                        cursor,
                        audit_table=audit_table,
                        run_id=run_id,
                        source_file=excel_path,
                        sheet_name=sheet_name,
                        destination_table=table,
                        row_results=header_audit_results,
                    )
                    conn.commit()
                    print("ℹ️ 欄名智慧比對 audit rows 寫入完成", flush=True)

            row_iter = iter_excel_rows(
                excel_path=excel_path,
                sheet_name=sheet_name,
                header_row=header_row,
                start_row=start_row,
                end_row=end_row,
                mappings=mappings,
                skip_empty_rows=skip_empty_rows,
            )

            for raw_batch in chunked(row_iter, batch_size):
                batch_results: List[RowResult] = []
                candidates: List[Tuple[int, Dict[str, Any], str]] = []

                existing_hashes = get_existing_hashes(
                    cursor,
                    table=table,
                    hash_field=hash_field,
                    hash_values=[hash_value for _row_no, _record, _source_values, hash_value, _invalid in raw_batch],
                )

                for row_no, record, source_values, hash_value, invalid_message in raw_batch:
                    payload = {"source": source_values, "destination": record}
                    if invalid_message:
                        batch_results.append(
                            RowResult(
                                row_no=row_no,
                                hash_value=hash_value,
                                status="failed",
                                message=invalid_message,
                                row_payload=payload,
                            )
                        )
                        continue
                    if hash_value in existing_hashes:
                        batch_results.append(
                            RowResult(
                                row_no=row_no,
                                hash_value=hash_value,
                                status="duplicate",
                                message=f"hash_value 已存在於 {table}.{hash_field}，略過匯入",
                                row_payload=payload,
                            )
                        )
                        continue
                    if hash_value in seen_in_run:
                        batch_results.append(
                            RowResult(
                                row_no=row_no,
                                hash_value=hash_value,
                                status="duplicate",
                                message="同次執行中已有相同來源欄名與內容的資料列，略過匯入",
                                row_payload=payload,
                            )
                        )
                        continue
                    seen_in_run.add(hash_value)
                    record[hash_field] = hash_value
                    candidates.append((row_no, record, hash_value))

                if candidates:
                    rows = [tuple(record.get(field) for field in dest_fields) for _row_no, record, _hash_value in candidates]
                    contexts = [
                        (row_no, hash_value, {"destination": record})
                        for row_no, record, hash_value in candidates
                    ]
                    insert_results, _inserted_rows = insert_batch_with_fallback(
                        cursor,
                        insert_sql=insert_sql,
                        rows=rows,
                        row_contexts=contexts,
                    )
                    batch_results.extend(insert_results)

                if audit_enabled:
                    print(f"ℹ️ 準備寫入批次 audit rows：{len(batch_results)} 筆", flush=True)
                    _attach_audit_metadata(batch_results, cfg)
                    insert_audit_rows(
                        cursor,
                        audit_table=audit_table,
                        run_id=run_id,
                        source_file=excel_path,
                        sheet_name=sheet_name,
                        destination_table=table,
                        row_results=batch_results,
                    )
                    print("ℹ️ 批次 audit rows 寫入完成", flush=True)

                conn.commit()

                inserted = sum(1 for item in batch_results if item.status == "inserted")
                duplicate = sum(1 for item in batch_results if item.status == "duplicate")
                failed = sum(1 for item in batch_results if item.status == "failed")
                result.success += inserted
                result.duplicate += duplicate
                result.failed += failed
                for item in batch_results:
                    if item.status == "failed":
                        result.record_failure(item.message)
                print(
                    f"✅ 批次完成：{sheet_name} 新增 {inserted} 筆，重複略過 {duplicate} 筆，"
                    f"失敗 {failed} 筆，累計新增 {result.success} 筆"
                )
                write_log(
                    log_dir,
                    {
                        "event": "batch_done",
                        "run_id": run_id,
                        "source_file": str(excel_path),
                        "sheet_name": sheet_name,
                        "inserted": inserted,
                        "duplicate": duplicate,
                        "failed": failed,
                    },
                )
    finally:
        cursor.close()

    print(
        f"🎯 檔案完成：{excel_path.name}，已處理工作表 {len(sheet_headers)} 個，"
        f"成功新增 {result.success} 筆，重複略過 {result.duplicate} 筆，失敗 {result.failed} 筆"
    )
    return result
