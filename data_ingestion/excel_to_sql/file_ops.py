"""Filesystem, logging, and retry configuration helpers for ingestion."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from .utils import get_nested, json_safe, resolve_path


def write_log(log_dir: Path, event: Dict[str, Any]):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"excel_import_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    payload = {"logged_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", **event}
    with log_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False, default=json_safe) + "\n")


def unique_archive_path(target_dir: Path, source_file: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    candidate = target_dir / f"{source_file.stem}_{timestamp}{source_file.suffix}"
    counter = 1
    while candidate.exists():
        candidate = target_dir / f"{source_file.stem}_{timestamp}_{counter}{source_file.suffix}"
        counter += 1
    return candidate


def move_to_archive(source_file: Path, target_dir: Path) -> Path:
    target = unique_archive_path(target_dir, source_file)
    shutil.move(str(source_file), str(target))
    return target


def get_log_dir(config_path: str, cfg: Dict[str, Any]) -> Path:
    raw = str(get_nested(cfg, "archive.log_dir", "logs/excel_import") or "logs/excel_import")
    return resolve_path(config_path, raw)


def get_import_retry_config(cfg: Dict[str, Any]) -> Tuple[int, float]:
    max_attempts = int(
        get_nested(
            cfg,
            "retry.max_attempts",
            get_nested(cfg, "import.retry_max_attempts", get_nested(cfg, "import.max_attempts", 1)),
        )
        or 1
    )
    interval_seconds = float(
        get_nested(
            cfg,
            "retry.interval_seconds",
            get_nested(cfg, "import.retry_interval_seconds", get_nested(cfg, "import.retry_delay_seconds", 0)),
        )
        or 0
    )
    if max_attempts <= 0:
        raise ValueError("retry.max_attempts 必須大於 0")
    if interval_seconds < 0:
        raise ValueError("retry.interval_seconds 不可小於 0")
    return max_attempts, interval_seconds
