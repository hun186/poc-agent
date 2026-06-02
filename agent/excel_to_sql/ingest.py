# agent/excel_to_sql/ingest.py
# cd /d D:\shared\TopicClassification\poc-agent
# python -m agent.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .audit import build_header_audit_results, ensure_audit_table, insert_audit_rows
from .constants import (
    DEFAULT_AUDIT_TABLE,
    DEFAULT_HASH_ALGORITHM,
    DEFAULT_HASH_FIELD,
    DEFAULT_HASH_FIELD_TYPE,
    DEFAULT_HASH_HEX_LENGTH,
    EXCEL_SUFFIXES,
)
from .db_ops import get_existing_hashes, insert_batch_with_fallback
from .diagnostics import enable_native_crash_tracebacks
from .file_ops import (
    get_import_retry_config,
    get_log_dir,
    move_to_archive,
    unique_archive_path,
    write_log,
)
from .models import FileResult, RowResult
from .sql_utils import (
    build_conn_str_from_config,
    build_insert_sql,
    build_select_existing_hashes_sql,
    destination_column_exists,
    destination_hash_field_exists,
    detect_odbc_driver,
    ensure_destination_columns,
    ensure_destination_hash_field,
    ensure_destination_table,
    quote_ident,
    quote_object_path,
    sql_string_literal,
    validate_hash_field_type,
)
from .utils import (
    chunked,
    get_nested,
    load_json_config,
    normalize_header_key,
    require_nested,
    resolve_path,
)
from .workbook import (
    discover_excel_files,
    iter_excel_rows,
    make_hash_value,
    open_workbook_header,
    parse_excel_column_ref,
    read_column_mappings,
    read_header_map,
    resolve_header_candidate,
)

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
    excel_path, sheet_name, header_row, header_map = open_workbook_header(config_path, cfg, excel_path)
    mappings = read_column_mappings(cfg, header_map)

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
    dest_fields = [mapping["dest_field"] for mapping in mappings]
    if hash_field not in dest_fields:
        dest_fields.append(hash_field)
    insert_sql = build_insert_sql(table, dest_fields)

    batch_size = int(get_nested(cfg, "import.batch_size", 500) or 500)
    if batch_size <= 0:
        raise ValueError("import.batch_size 必須大於 0")

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
            mappings=mappings,
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
            mappings=mappings,
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
    print(f"ℹ️ Sheet: {sheet_name}")
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
                    "message": header_result.message,
                    "payload": header_result.row_payload,
                },
            )
        if audit_enabled:
            print("ℹ️ 準備寫入欄名智慧比對 audit rows", flush=True)
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

    try:
        row_iter = iter_excel_rows(
            excel_path=excel_path,
            sheet_name=sheet_name,
            header_row=header_row,
            start_row=start_row,
            end_row=end_row,
            mappings=mappings,
            skip_empty_rows=skip_empty_rows,
        )

        seen_in_run: set[str] = set()
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

            print(
                f"✅ 批次完成：新增 {inserted} 筆，重複略過 {duplicate} 筆，"
                f"失敗 {failed} 筆，累計新增 {result.success} 筆"
            )
            write_log(
                log_dir,
                {
                    "event": "batch_done",
                    "run_id": run_id,
                    "source_file": str(excel_path),
                    "inserted": inserted,
                    "duplicate": duplicate,
                    "failed": failed,
                },
            )
    finally:
        cursor.close()

    print(
        f"🎯 檔案完成：{excel_path.name}，成功新增 {result.success} 筆，"
        f"重複略過 {result.duplicate} 筆，失敗 {result.failed} 筆"
    )
    return result



def process_excel_file_with_retries(
    *,
    config_path: str,
    cfg: Dict[str, Any],
    excel_path: Path,
    conn,
    run_id: str,
    log_dir: Path,
    max_attempts: int,
    interval_seconds: float,
) -> FileResult:
    last_result = FileResult(file_path=excel_path)
    for attempt in range(1, max_attempts + 1):
        try:
            if attempt > 1:
                print(f"🔁 第 {attempt}/{max_attempts} 次重試匯入：{excel_path}")
            file_result = process_excel_file(
                config_path=config_path,
                cfg=cfg,
                excel_path=excel_path,
                conn=conn,
                run_id=run_id,
                log_dir=log_dir,
            )
            if file_result.ok or attempt >= max_attempts:
                return file_result

            last_result = file_result
            print(
                f"⚠️ 檔案匯入仍有失敗列：{excel_path}；"
                f"第 {attempt}/{max_attempts} 次，{interval_seconds:g} 秒後重試"
            )
            write_log(
                log_dir,
                {
                    "event": "file_retry_scheduled",
                    "run_id": run_id,
                    "source_file": str(excel_path),
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "interval_seconds": interval_seconds,
                    "failed": file_result.failed,
                    "error": file_result.error,
                },
            )
        except Exception as exc:
            conn.rollback()
            last_result = FileResult(file_path=excel_path, failed=1, error=str(exc))
            if attempt >= max_attempts:
                return last_result

            print(
                f"⚠️ 檔案處理失敗：{excel_path}；第 {attempt}/{max_attempts} 次；"
                f"{interval_seconds:g} 秒後重試；錯誤：{exc}"
            )
            write_log(
                log_dir,
                {
                    "event": "file_retry_scheduled",
                    "run_id": run_id,
                    "source_file": str(excel_path),
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "interval_seconds": interval_seconds,
                    "error": str(exc),
                },
            )

        if interval_seconds > 0:
            time.sleep(interval_seconds)

    return last_result



def bulk_insert_excel_to_sql_from_config(config_path: str, cfg: Dict[str, Any]) -> tuple[int, int, int]:
    enable_native_crash_tracebacks()
    run_id = uuid.uuid4().hex
    files = discover_excel_files(config_path, cfg)
    log_dir = get_log_dir(config_path, cfg)
    if not files:
        print("ℹ️ 沒有找到可匯入的 Excel 檔案")
        write_log(log_dir, {"event": "run_done", "run_id": run_id, "message": "no files"})
        return 0, 0, 0

    import pyodbc

    conn = pyodbc.connect(build_conn_str_from_config(cfg))
    cursor = conn.cursor()
    try:
        audit_enabled = bool(get_nested(cfg, "audit.enabled", True))
        audit_table = str(get_nested(cfg, "audit.table", DEFAULT_AUDIT_TABLE) or DEFAULT_AUDIT_TABLE)
        if audit_enabled:
            ensure_audit_table(cursor, audit_table)
            conn.commit()

        truncate_before_load = bool(get_nested(cfg, "import.truncate_before_load", False))
        if truncate_before_load:
            table = str(require_nested(cfg, "destination.table"))
            truncate_sql = f"TRUNCATE TABLE {quote_object_path(table)}"
            cursor.execute(truncate_sql)
            conn.commit()
            print(f"⚠️ 已先清空目的資料表：{table}")
    finally:
        cursor.close()

    archive_enabled = bool(get_nested(cfg, "archive.enabled", bool(get_nested(cfg, "source.directory", ""))))
    success_dir = resolve_path(config_path, str(get_nested(cfg, "archive.success_dir", "archive/success") or "archive/success"))
    fail_dir = resolve_path(config_path, str(get_nested(cfg, "archive.fail_dir", "archive/failed") or "archive/failed"))

    retry_max_attempts, retry_interval_seconds = get_import_retry_config(cfg)
    if retry_max_attempts > 1:
        print(
            f"ℹ️ 匯入重試：最多嘗試 {retry_max_attempts} 次；"
            f"每次間隔 {retry_interval_seconds:g} 秒"
        )

    totals = {"success": 0, "duplicate": 0, "failed": 0}
    try:
        for excel_path in files:
            file_result = process_excel_file_with_retries(
                config_path=config_path,
                cfg=cfg,
                excel_path=excel_path,
                conn=conn,
                run_id=run_id,
                log_dir=log_dir,
                max_attempts=retry_max_attempts,
                interval_seconds=retry_interval_seconds,
            )
            if not file_result.ok:
                print(f"❌ 檔案達重試上限後仍失敗：{excel_path}；{file_result.error}")
                write_log(
                    log_dir,
                    {
                        "event": "file_failed",
                        "run_id": run_id,
                        "source_file": str(excel_path),
                        "attempts": retry_max_attempts,
                        "failed": file_result.failed,
                        "error": file_result.error,
                    },
                )

            totals["success"] += file_result.success
            totals["duplicate"] += file_result.duplicate
            totals["failed"] += file_result.failed

            if archive_enabled:
                target_dir = success_dir if file_result.ok else fail_dir
                moved_to = move_to_archive(excel_path, target_dir)
                print(f"📦 已移動檔案到：{moved_to}")
                write_log(
                    log_dir,
                    {
                        "event": "file_archived",
                        "run_id": run_id,
                        "source_file": str(excel_path),
                        "target_file": str(moved_to),
                        "status": "success" if file_result.ok else "failed",
                        "inserted": file_result.success,
                        "duplicate": file_result.duplicate,
                        "failed": file_result.failed,
                        "error": file_result.error,
                    },
                )
    finally:
        conn.close()

    print(
        f"🎯 全部完成：成功新增 {totals['success']} 筆，"
        f"重複略過 {totals['duplicate']} 筆，失敗 {totals['failed']} 筆"
    )
    write_log(log_dir, {"event": "run_done", "run_id": run_id, **totals})
    return totals["success"], totals["duplicate"], totals["failed"]


def main():
    enable_native_crash_tracebacks()

    parser = argparse.ArgumentParser(description="依設定檔從 Excel 或來源目錄匯入資料到 SQL Server")
    parser.add_argument("--config", required=True, help="JSON 設定檔路徑")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    cfg = load_json_config(args.config)
    bulk_insert_excel_to_sql_from_config(args.config, cfg)


if __name__ == "__main__":
    main()
