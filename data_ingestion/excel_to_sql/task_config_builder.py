from __future__ import annotations

import re
from typing import Any

_ALLOWED_FIELD_TYPE_RE = re.compile(r"^[A-Za-z0-9_(),\s]+$")


def _clean_string(
    value: Any, field_name: str, *, required: bool = True, max_length: int = 255
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field_name} 不可空白")
    if len(text) > max_length:
        raise ValueError(f"{field_name} 長度不可超過 {max_length}")
    return text


def _clean_sql_type(value: Any, default: str) -> str:
    text = str(value or default).strip().upper()
    if not _ALLOWED_FIELD_TYPE_RE.fullmatch(text):
        raise ValueError(f"SQL 欄位型別含有不允許字元：{value}")
    return text


def build_task_config(
    payload: dict[str, Any], *, connection_db: dict[str, Any] | None = None
) -> dict[str, Any]:
    mappings_payload = payload.get("mappings") or []
    if not isinstance(mappings_payload, list) or not mappings_payload:
        raise ValueError("至少需要一筆 Excel 欄位對應")

    mappings: list[dict[str, Any]] = []
    seen_dest_fields: set[str] = set()
    for index, item in enumerate(mappings_payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 筆欄位對應格式錯誤")
        source_column = _clean_string(
            item.get("source_column"), f"第 {index} 筆來源欄位"
        )
        dest_field = _clean_string(item.get("dest_field"), f"第 {index} 筆目的欄位")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dest_field):
            raise ValueError(f"第 {index} 筆目的欄位只能使用 SQL 欄位安全命名")
        if dest_field.lower() in seen_dest_fields:
            raise ValueError(f"目的欄位重複：{dest_field}")
        seen_dest_fields.add(dest_field.lower())
        mapping: dict[str, Any] = {
            "source_column": source_column,
            "dest_field": dest_field,
            "required": bool(item.get("required", False)),
            "dest_field_type": _clean_sql_type(
                item.get("dest_field_type"), "NVARCHAR(MAX)"
            ),
        }
        match = str(item.get("match") or "").strip()
        if match:
            if match not in {"exact", "prefix", "contains"}:
                raise ValueError(f"第 {index} 筆 match 僅支援 exact、prefix、contains")
            mapping["match"] = match
        value_type = str(item.get("value_type") or "").strip()
        if value_type:
            if value_type not in {"text", "int", "float", "date", "datetime", "bool"}:
                raise ValueError(f"第 {index} 筆 value_type 不支援：{value_type}")
            mapping["value_type"] = value_type
        mappings.append(mapping)

    composite_payload = payload.get("composite_mappings") or []
    if not isinstance(composite_payload, list):
        raise ValueError("composite_mappings 必須是陣列")
    for index, item in enumerate(composite_payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 筆組合欄位格式錯誤")
        dest_field = _clean_string(item.get("dest_field"), f"第 {index} 筆組合目的欄位")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dest_field):
            raise ValueError(f"第 {index} 筆組合目的欄位只能使用 SQL 欄位安全命名")
        if dest_field.lower() in seen_dest_fields:
            raise ValueError(f"目的欄位重複：{dest_field}")
        source_columns = item.get("source_columns") or []
        if isinstance(source_columns, str):
            source_columns = [part.strip() for part in source_columns.split(",")]
        source_columns = [
            str(part or "").strip()
            for part in source_columns
            if str(part or "").strip()
        ]
        if len(source_columns) < 2:
            raise ValueError(f"第 {index} 筆組合欄位至少需要兩個來源欄位")
        match = str(item.get("match") or "exact").strip()
        if match not in {"exact", "prefix", "contains"}:
            raise ValueError(f"第 {index} 筆組合欄位 match 僅支援 exact、prefix、contains")
        compose_config = {
            "source_columns": source_columns,
            "separator": str(
                item.get("separator") if item.get("separator") is not None else " "
            ),
            "skip_empty": bool(item.get("skip_empty", True)),
        }
        template = str(item.get("template") or "").strip()
        if template:
            compose_config["template"] = template
        seen_dest_fields.add(dest_field.lower())
        mappings.append(
            {
                "dest_field": dest_field,
                "required": bool(item.get("required", False)),
                "dest_field_type": _clean_sql_type(
                    item.get("dest_field_type"), "NVARCHAR(MAX)"
                ),
                "match": match,
                "compose": compose_config,
            }
        )

    table = _clean_string(
        payload.get("destination_table"), "目的資料表", max_length=128
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", table):
        raise ValueError("目的資料表僅支援安全的 table 或 schema.table 命名")

    audit_table = _clean_string(
        payload.get("audit_table") or "dbo.ExcelImportAudit",
        "audit table",
        max_length=128,
    )
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", audit_table
    ):
        raise ValueError("audit table 僅支援安全的 table 或 schema.table 命名")

    source_directory = _clean_string(
        payload.get("source_directory") or "./data/excel_inbox",
        "Excel 來源目錄",
        max_length=500,
    )
    source_sheet = _clean_string(
        payload.get("source_sheet"), "工作表名稱", max_length=128
    )
    header_row = int(payload.get("header_row") or 1)
    start_row = int(payload.get("start_row") or header_row + 1)
    if header_row < 1 or start_row < header_row:
        raise ValueError("header_row / start_row 數值不合法")

    db_config = connection_db or {
        "driver": _clean_string(
            payload.get("db_driver") or "auto", "ODBC driver", max_length=128
        ),
        "server": _clean_string(
            payload.get("db_server"), "資料庫 server", max_length=255
        ),
        "database": _clean_string(
            payload.get("db_database"), "資料庫名稱", max_length=128
        ),
        "trusted_connection": bool(payload.get("db_trusted_connection", False)),
        "encrypt": bool(payload.get("db_encrypt", True)),
        "trust_server_certificate": bool(
            payload.get("db_trust_server_certificate", True)
        ),
    }

    config = {
        "db": db_config,
        "source": {
            "directory": source_directory,
            "file_pattern": _clean_string(
                payload.get("file_pattern") or "*.xlsx", "檔案樣式", max_length=80
            ),
            "recursive": bool(payload.get("recursive", False)),
            "sheet": source_sheet,
            "header_row": header_row,
            "start_row": start_row,
            "end_row": int(payload.get("end_row") or 0),
        },
        "destination": {
            "table": table,
            "auto_create_table": bool(payload.get("auto_create_table", True)),
            "auto_create_missing_fields": bool(
                payload.get("auto_create_missing_fields", True)
            ),
            "default_field_type": _clean_sql_type(
                payload.get("default_field_type"), "NVARCHAR(MAX)"
            ),
            "hash_field": _clean_string(
                payload.get("hash_field") or "hash_value", "hash 欄位", max_length=80
            ),
            "auto_create_hash_field": True,
            "hash_field_type": _clean_sql_type(
                payload.get("hash_field_type"), "CHAR(64)"
            ),
            "create_hash_index": bool(payload.get("create_hash_index", True)),
        },
        "mappings": mappings,
        "import": {
            "batch_size": int(payload.get("batch_size") or 500),
            "skip_empty_rows": bool(payload.get("skip_empty_rows", True)),
            "truncate_before_load": bool(payload.get("truncate_before_load", False)),
            "fast_executemany": bool(payload.get("fast_executemany", True)),
        },
        "retry": {
            "max_attempts": int(payload.get("retry_max_attempts") or 3),
            "interval_seconds": int(payload.get("retry_interval_seconds") or 60),
        },
        "archive": {
            "enabled": bool(payload.get("archive_enabled", True)),
            "success_dir": _clean_string(
                payload.get("archive_success_dir") or "./data/excel_archive/success",
                "成功封存目錄",
                max_length=500,
            ),
            "fail_dir": _clean_string(
                payload.get("archive_fail_dir") or "./data/excel_archive/failed",
                "失敗封存目錄",
                max_length=500,
            ),
            "log_dir": _clean_string(
                payload.get("log_dir") or "./logs/excel_import",
                "log 目錄",
                max_length=500,
            ),
        },
        "audit": {"enabled": True, "table": audit_table},
        "dashboard": {
            "enabled": False,
            "name": _clean_string(payload.get("task_name"), "任務名稱", max_length=120),
            "status": "pending",
        },
    }
    if connection_db is None and not config["db"].get("trusted_connection"):
        config["db"]["user"] = _clean_string(
            payload.get("db_user"), "資料庫使用者", max_length=128
        )
        config["db"]["password"] = _clean_string(
            payload.get("db_password"), "資料庫密碼", max_length=500
        )
    return config

