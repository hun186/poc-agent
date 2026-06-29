from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from data_ingestion.excel_to_sql.ingest import load_json_config
from data_ingestion.excel_to_sql.task_config_builder import (
    _clean_string,
    build_task_config,
)

CONFIG_ROOT = Path("config/excel_to_sql")
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


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


def _sanitize_db_config_for_display(db_cfg: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(db_cfg)
    for key in ("server", "database", "user", "password"):
        if key in sanitized and sanitized.get(key) not in {None, ""}:
            sanitized[key] = "********"
    return sanitized


def _sanitized_config_for_review(cfg: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(cfg, ensure_ascii=False))
    db_cfg = sanitized.get("db")
    if isinstance(db_cfg, dict):
        sanitized["db"] = _sanitize_db_config_for_display(db_cfg)
    return sanitized


def task_review_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    db_cfg = cfg.get("db") if isinstance(cfg.get("db"), dict) else {}
    source = cfg.get("source") if isinstance(cfg.get("source"), dict) else {}
    destination = (
        cfg.get("destination") if isinstance(cfg.get("destination"), dict) else {}
    )
    audit = cfg.get("audit") if isinstance(cfg.get("audit"), dict) else {}
    import_cfg = cfg.get("import") if isinstance(cfg.get("import"), dict) else {}
    retry = cfg.get("retry") if isinstance(cfg.get("retry"), dict) else {}
    archive = cfg.get("archive") if isinstance(cfg.get("archive"), dict) else {}
    mappings = cfg.get("mappings") if isinstance(cfg.get("mappings"), list) else []
    return {
        "db": {
            "driver": db_cfg.get("driver"),
            "server": "********" if db_cfg.get("server") else None,
            "database": "********" if db_cfg.get("database") else None,
            "trusted_connection": bool(db_cfg.get("trusted_connection")),
            "user": "********" if db_cfg.get("user") else None,
            "password": "********" if db_cfg.get("password") else None,
            "encrypt": db_cfg.get("encrypt"),
            "trust_server_certificate": db_cfg.get("trust_server_certificate"),
        },
        "source": {
            "directory": source.get("directory"),
            "file_pattern": source.get("file_pattern"),
            "recursive": bool(source.get("recursive")),
            "sheet": source.get("sheet"),
            "header_row": source.get("header_row"),
            "start_row": source.get("start_row"),
            "end_row": source.get("end_row"),
        },
        "destination": {
            "table": destination.get("table"),
            "auto_create_table": bool(destination.get("auto_create_table")),
            "auto_create_missing_fields": bool(
                destination.get("auto_create_missing_fields")
            ),
            "default_field_type": destination.get("default_field_type"),
            "hash_field": destination.get("hash_field"),
            "hash_field_type": destination.get("hash_field_type"),
            "create_hash_index": bool(destination.get("create_hash_index")),
        },
        "audit": {"enabled": bool(audit.get("enabled")), "table": audit.get("table")},
        "mappings": [
            {
                "source_column": item.get("source_column")
                or ", ".join((item.get("compose") or {}).get("source_columns", [])),
                "dest_field": item.get("dest_field"),
                "dest_field_type": item.get("dest_field_type"),
                "required": bool(item.get("required")),
                "match": item.get("match") or "exact",
                "value_type": item.get("value_type"),
                "compose": item.get("compose"),
            }
            for item in mappings
            if isinstance(item, dict)
        ],
        "import": {
            "batch_size": import_cfg.get("batch_size"),
            "skip_empty_rows": bool(import_cfg.get("skip_empty_rows")),
            "truncate_before_load": bool(import_cfg.get("truncate_before_load")),
            "fast_executemany": bool(import_cfg.get("fast_executemany")),
        },
        "retry": {
            "max_attempts": retry.get("max_attempts"),
            "interval_seconds": retry.get("interval_seconds"),
        },
        "archive": {
            "enabled": bool(archive.get("enabled")),
            "success_dir": archive.get("success_dir"),
            "fail_dir": archive.get("fail_dir"),
            "log_dir": archive.get("log_dir"),
        },
    }


def list_task_configs(
    *, root: Path = CONFIG_ROOT, created_by: str | None = None
) -> list[dict[str, Any]]:
    root_path = root.resolve()
    if not root_path.exists():
        return []
    tasks: list[dict[str, Any]] = []
    for path in sorted(root_path.rglob("*.json")):
        try:
            cfg = load_json_config(str(path))
        except Exception:
            continue
        dashboard = cfg.get("dashboard") if isinstance(cfg, dict) else None
        if not isinstance(dashboard, dict):
            continue
        display_path = (
            str(CONFIG_ROOT / path.resolve().relative_to(root_path))
            if root == CONFIG_ROOT
            else str(path)
        )
        if created_by is not None and dashboard.get("created_by") != created_by:
            continue
        status = (
            "active"
            if dashboard.get("enabled")
            else (dashboard.get("status") or "pending")
        )
        tasks.append(
            {
                "config_path": display_path,
                "name": dashboard.get("name") or path.stem,
                "status": status,
                "enabled": bool(dashboard.get("enabled")),
                "created_by": dashboard.get("created_by"),
                "approved_by": dashboard.get("approved_by"),
                "review_summary": task_review_summary(cfg),
                "config_preview": _sanitized_config_for_review(cfg),
            }
        )
    return tasks


def set_task_config_enabled(
    config_path: str, *, enabled: bool, actor: str, root: Path = CONFIG_ROOT
) -> dict[str, Any]:
    target = resolve_task_config_path(config_path, root=root)
    if not target.exists():
        raise FileNotFoundError(f"任務設定檔不存在：{target}")
    cfg = load_json_config(str(target))
    dashboard = cfg.setdefault("dashboard", {})
    if not isinstance(dashboard, dict):
        raise ValueError("任務設定檔 dashboard 區塊格式錯誤")
    dashboard["enabled"] = bool(enabled)
    dashboard["status"] = "active" if enabled else "pending"
    if enabled:
        dashboard["approved_by"] = actor
    else:
        dashboard["disabled_by"] = actor
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
        "status": dashboard["status"],
        "enabled": bool(enabled),
        "approved_by": dashboard.get("approved_by"),
        "disabled_by": dashboard.get("disabled_by"),
    }


def approve_task_config(
    config_path: str, *, actor: str, root: Path = CONFIG_ROOT
) -> dict[str, Any]:
    return set_task_config_enabled(config_path, enabled=True, actor=actor, root=root)


def delete_task_config(
    config_path: str,
    *,
    actor: str,
    is_superuser: bool = False,
    root: Path = CONFIG_ROOT,
) -> dict[str, Any]:
    target = resolve_task_config_path(config_path, root=root)
    if not target.exists():
        raise FileNotFoundError(f"任務設定檔不存在：{target}")
    cfg = load_json_config(str(target))
    dashboard = cfg.get("dashboard") if isinstance(cfg, dict) else None
    if not isinstance(dashboard, dict):
        raise ValueError("任務設定檔 dashboard 區塊格式錯誤")
    created_by = dashboard.get("created_by")
    if not is_superuser and created_by != actor:
        raise PermissionError("只能刪除自己建立的任務設定檔")
    display_path = (
        str(CONFIG_ROOT / target.relative_to(root.resolve()))
        if root == CONFIG_ROOT
        else str(target)
    )
    target.unlink()
    return {
        "config_path": display_path,
        "deleted": True,
        "created_by": created_by,
        "deleted_by": actor,
    }
