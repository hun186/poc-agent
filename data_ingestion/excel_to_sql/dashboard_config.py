from __future__ import annotations

from pathlib import Path
from typing import Any

from data_ingestion.excel_to_sql.ingest import get_nested


def _dashboard_enabled(cfg: dict[str, Any]) -> bool:
    return bool(get_nested(cfg, "dashboard.enabled", False))


def _dashboard_name(cfg: dict[str, Any], config_path: Path) -> str:
    configured = str(get_nested(cfg, "dashboard.name", "") or "").strip()
    if configured:
        return configured
    table = str(get_nested(cfg, "destination.table", "") or "").strip()
    return table or config_path.stem
