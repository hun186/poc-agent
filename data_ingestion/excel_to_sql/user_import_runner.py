from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any

from .file_ops import get_log_dir
from .file_processor import process_excel_file
from .ingest import load_json_config
from .sql_utils import build_conn_str_from_config
from .user_import_storage import public_record, read_registry, utc_now, write_registry


def import_record(
    record_id: str, *, username: str, is_superuser: bool
) -> dict[str, Any]:
    data = read_registry()
    for record in data["records"]:
        if record.get("id") == record_id:
            if not is_superuser and record.get("username") != username:
                raise PermissionError("不可匯入其他使用者的 Excel。")
            if record.get("status") == "deleted":
                raise ValueError("已刪除的匯入記錄不可匯入。")
            cfg = copy.deepcopy(load_json_config(str(record["config_path"])))
            cfg.setdefault("source", {})["excel_path"] = str(
                Path(str(record["stored_path"])).resolve()
            )
            cfg["source"].pop("directory", None)
            cfg.setdefault("archive", {})["enabled"] = False
            run_id = uuid.uuid4().hex

            import pyodbc

            conn = pyodbc.connect(build_conn_str_from_config(cfg))
            try:
                result = process_excel_file(
                    config_path=str(record["config_path"]),
                    cfg=cfg,
                    excel_path=Path(str(record["stored_path"])),
                    conn=conn,
                    run_id=run_id,
                    log_dir=get_log_dir(str(record["config_path"]), cfg),
                )
            finally:
                conn.close()
            payload = {
                "run_id": run_id,
                "inserted_rows": result.success,
                "duplicate_rows": result.duplicate,
                "failed_rows": result.failed,
                "ok": result.ok,
                "failure_summary": result.failure_summary,
                "imported_at": utc_now(),
            }
            record["import_result"] = payload
            record["status"] = "imported" if result.ok else "imported_with_errors"
            record["updated_at"] = utc_now()
            write_registry(data)
            return {"record": public_record(record), "import_result": payload}
    raise FileNotFoundError(f"找不到匯入記錄：{record_id}")
