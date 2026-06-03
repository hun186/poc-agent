# data_ingestion/excel_to_sql/ingest.py
# cd /d D:\shared\TopicClassification\poc-agent
# python -m data_ingestion.excel_to_sql.ingest --config config/excel_to_sql/vessel_activities.example.json

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from .audit import ensure_audit_table
from .constants import DEFAULT_AUDIT_TABLE
from .db_ops import insert_batch_with_fallback
from .diagnostics import enable_native_crash_tracebacks
from .file_ops import (
    get_import_retry_config,
    get_log_dir,
    move_to_archive,
    write_log,
)
from .file_processor import process_excel_file
from .models import FileResult
from .sql_utils import build_conn_str_from_config, quote_ident, quote_object_path
from .utils import get_nested, load_json_config, require_nested, resolve_path
from .workbook import discover_excel_files


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
            if file_result.failed:
                print(
                    f"⚠️ 檔案匯入完成但有資料列失敗：{excel_path}；"
                    "資料列層級錯誤不會自動重試，請修正資料後重新匯入"
                )
                if file_result.failure_summary:
                    print("ℹ️ 資料列錯誤種類統計：")
                    for message, count in sorted(
                        file_result.failure_summary.items(),
                        key=lambda item: (-item[1], item[0]),
                    ):
                        print(f"   - {message}：{count} 筆")
                write_log(
                    log_dir,
                    {
                        "event": "file_row_failures_not_retried",
                        "run_id": run_id,
                        "source_file": str(excel_path),
                        "failed": file_result.failed,
                        "failure_summary": file_result.failure_summary,
                    },
                )
            return file_result
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
        for file_index, excel_path in enumerate(files, start=1):
            if file_index > 1:
                print("────────────────────────────────────────")
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
