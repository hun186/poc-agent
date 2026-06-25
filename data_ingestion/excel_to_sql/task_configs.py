from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from data_ingestion.excel_to_sql.ingest import load_json_config

CONFIG_ROOT = Path("config/excel_to_sql")
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
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


def resolve_task_config_path(filename: str, *, root: Path = CONFIG_ROOT) -> Path:
    safe_path = _clean_string(filename, "設定檔檔名", max_length=240).replace("\\", "/")
    prefixes = [root.as_posix().rstrip("/"), CONFIG_ROOT.as_posix().rstrip("/")]
    if safe_path in prefixes:
        raise ValueError("設定檔檔名必須包含 JSON 檔名")
    for prefix in prefixes:
        root_prefix = prefix + "/"
        if safe_path.startswith(root_prefix):
            safe_path = safe_path[len(root_prefix) :]
            break
    candidate = Path(safe_path)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise ValueError("設定檔檔名必須是 config/excel_to_sql 底下的相對 JSON 路徑")
    if candidate.suffix.lower() != ".json":
        raise ValueError("設定檔檔名必須以 .json 結尾")
    for part in candidate.parts:
        if not _SAFE_PATH_SEGMENT_RE.fullmatch(part):
            raise ValueError("設定檔路徑每一層只能使用英數、底線、連字號與句點")
    root_path = root.resolve()
    target = (root_path / candidate).resolve()
    if root_path not in target.parents:
        raise ValueError("設定檔路徑必須位於 config/excel_to_sql")
    return target


def _resolve_connection_source_config(
    payload: dict[str, Any], *, root: Path = CONFIG_ROOT
) -> dict[str, Any] | None:
    source = str(payload.get("connection_source_config") or "").strip()
    if not source:
        return None
    source_path = resolve_task_config_path(source, root=root)
    if not source_path.exists():
        raise FileNotFoundError(f"資料庫連線來源設定檔不存在：{source_path}")
    cfg = load_json_config(str(source_path))
    db_cfg = cfg.get("db")
    if not isinstance(db_cfg, dict) or not db_cfg:
        raise ValueError("資料庫連線來源設定檔缺少 db 區塊")
    return dict(db_cfg)


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


def create_task_config(
    payload: dict[str, Any],
    *,
    actor: str,
    root: Path = CONFIG_ROOT,
    overwrite: bool = False,
) -> dict[str, Any]:
    target = resolve_task_config_path(str(payload.get("filename") or ""), root=root)
    if target.exists() and not overwrite:
        raise FileExistsError(f"設定檔已存在：{target}")
    connection_db = _resolve_connection_source_config(payload, root=root)
    config = build_task_config(payload, connection_db=connection_db)
    config["dashboard"]["created_by"] = actor
    config["dashboard"]["approved_by"] = None
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(target)
    display_path = (
        str(CONFIG_ROOT / target.relative_to(root.resolve()))
        if root == CONFIG_ROOT
        else str(target)
    )
    return {
        "config_path": display_path,
        "name": config["dashboard"]["name"],
        "created_by": actor,
        "status": config["dashboard"].get("status", "pending"),
        "enabled": bool(config["dashboard"].get("enabled")),
    }


def approve_task_config(
    config_path: str, *, actor: str, root: Path = CONFIG_ROOT
) -> dict[str, Any]:
    target = resolve_task_config_path(config_path, root=root)
    if not target.exists():
        raise FileNotFoundError(f"任務設定檔不存在：{target}")
    cfg = load_json_config(str(target))
    dashboard = cfg.setdefault("dashboard", {})
    if not isinstance(dashboard, dict):
        raise ValueError("任務設定檔 dashboard 區塊格式錯誤")
    dashboard["enabled"] = True
    dashboard["status"] = "active"
    dashboard["approved_by"] = actor
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(target)
    display_path = (
        str(CONFIG_ROOT / target.relative_to(root.resolve()))
        if root == CONFIG_ROOT
        else str(target)
    )
    return {
        "config_path": display_path,
        "name": dashboard.get("name") or target.stem,
        "status": "active",
        "enabled": True,
        "approved_by": actor,
    }
