from __future__ import annotations

from pathlib import Path
from typing import Any

from data_ingestion.excel_to_sql.dashboard_config import (
    _dashboard_enabled,
    _dashboard_name,
)
from data_ingestion.excel_to_sql.dashboard_sql import _audit_table
from data_ingestion.excel_to_sql.ingest import get_nested, load_json_config
from data_ingestion.excel_to_sql.task_configs import task_review_summary


def discover_dashboard_tasks(
    config_dir: str | Path = "config/excel_to_sql",
) -> list[dict[str, Any]]:
    root = Path(config_dir)
    if not root.exists():
        return []

    tasks: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            cfg = load_json_config(str(path))
        except Exception:
            continue
        if not _dashboard_enabled(cfg):
            continue
        tasks.append(
            {
                "name": _dashboard_name(cfg, path),
                "config_path": str(path),
                "audit_table": _audit_table(cfg),
                "destination_table": str(
                    get_nested(cfg, "destination.table", "") or ""
                ),
                "source_directory": str(get_nested(cfg, "source.directory", "") or ""),
                "enabled": True,
                "status": "active",
                "review_summary": task_review_summary(cfg),
            }
        )
    return tasks

