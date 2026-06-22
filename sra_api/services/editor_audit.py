# api/services/editor_audit.py
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from config.bootstrap import bootstrap_env

_AUDIT_LOCK = RLock()
_MAX_VALUE_CHARS = 4000


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def audit_log_path() -> Path:
    bootstrap_env()
    configured = (os.getenv("SRA_EDITOR_AUDIT_LOG") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / "logs" / "editor_audit.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return value[:_MAX_VALUE_CHARS] + f"...<truncated {len(value) - _MAX_VALUE_CHARS} chars>"
    if isinstance(value, list):
        return [_summarize_value(v) for v in value[:50]] + ([f"...<truncated {len(value) - 50} items>"] if len(value) > 50 else [])
    if isinstance(value, dict):
        items = list(value.items())[:80]
        out = {str(k): _summarize_value(v) for k, v in items}
        if len(value) > 80:
            out["...truncated_keys"] = len(value) - 80
        return out
    return value


def _join_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def diff_values(before: Any, after: Any, *, path: str = "", limit: int = 200) -> list[dict[str, Any]]:
    """Return a compact, path-based diff suitable for audit logs."""
    changes: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, current_path: str) -> None:
        if len(changes) >= limit:
            return
        if type(left) is not type(right):
            changes.append({"path": current_path or "$", "before": _summarize_value(left), "after": _summarize_value(right)})
            return
        if isinstance(left, dict):
            keys = sorted(set(left.keys()) | set(right.keys()), key=str)
            for key in keys:
                child_path = _join_path(current_path, str(key))
                if key not in left:
                    changes.append({"path": child_path, "before": None, "after": _summarize_value(right[key])})
                elif key not in right:
                    changes.append({"path": child_path, "before": _summarize_value(left[key]), "after": None})
                else:
                    walk(left[key], right[key], child_path)
                if len(changes) >= limit:
                    return
            return
        if isinstance(left, list):
            if left != right:
                changes.append({"path": current_path or "$", "before": _summarize_value(left), "after": _summarize_value(right)})
            return
        if left != right:
            changes.append({"path": current_path or "$", "before": _summarize_value(left), "after": _summarize_value(right)})

    walk(before, after, path)
    if len(changes) >= limit:
        changes.append({"path": "...", "before": None, "after": f"diff truncated at {limit} changes"})
    return changes


def append_audit_event(event: dict[str, Any]) -> None:
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": _utc_now(), **event}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _AUDIT_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def write_audit_snapshot(records: list[dict[str, Any]], target: Path | None = None) -> Path:
    """Utility for exporting audit records in tests or maintenance scripts."""
    path = target or audit_log_path().with_suffix(".snapshot.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".editor_audit.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return path
