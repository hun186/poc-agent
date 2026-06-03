from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException


def load_audit_records(limit: int = 5000) -> list[dict[str, Any]]:
    from api.services.editor_audit import audit_log_path

    path = audit_log_path()
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    if len(records) > limit:
        return records[-limit:]
    return records


def build_usage_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    by_index: dict[str, int] = {}
    by_user: dict[str, int] = {}
    changed_paths_total = 0
    for r in rows:
        action = str(r.get("action") or "unknown")
        idx = str(r.get("index") or "-")
        uname = str(r.get("username") or "-")
        by_action[action] = by_action.get(action, 0) + 1
        by_index[idx] = by_index.get(idx, 0) + 1
        by_user[uname] = by_user.get(uname, 0) + 1
        changed_paths_total += len(r.get("changed_paths") or [])
    return {
        "total_events": len(rows),
        "changed_paths_total": changed_paths_total,
        "by_action": by_action,
        "by_index": by_index,
        "by_user": by_user,
    }


def filter_audit_records(
    records: list[dict[str, Any]],
    *,
    username: str | None = None,
    action: str | None = None,
    index: str | None = None,
    id: str | None = None,
    changed_path: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
) -> list[dict[str, Any]]:
    username_q = (username or "").strip().lower()
    action_q = (action or "").strip().lower()
    index_q = (index or "").strip()
    id_q = (id or "").strip()
    path_q = (changed_path or "").strip().lower()
    start_q = (start_ts or "").strip()
    end_q = (end_ts or "").strip()

    def in_range(ts_text: str) -> bool:
        if not (start_q or end_q):
            return True
        try:
            ts = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
        except Exception:
            return False
        if start_q:
            try:
                start = datetime.fromisoformat(start_q.replace("Z", "+00:00"))
                if ts < start:
                    return False
            except Exception:
                raise HTTPException(status_code=400, detail="start_ts 格式錯誤，請使用 ISO 8601。")
        if end_q:
            try:
                end = datetime.fromisoformat(end_q.replace("Z", "+00:00"))
                if ts > end:
                    return False
            except Exception:
                raise HTTPException(status_code=400, detail="end_ts 格式錯誤，請使用 ISO 8601。")
        return True

    filtered: list[dict[str, Any]] = []
    for r in records:
        if username_q and username_q not in str(r.get("username") or "").lower():
            continue
        if action_q and action_q not in str(r.get("action") or "").lower():
            continue
        if index_q and index_q != str(r.get("index") or ""):
            continue
        if id_q and id_q != str(r.get("id") or ""):
            continue
        if path_q:
            paths = r.get("changed_paths") or []
            if not any(path_q in str(p or "").lower() for p in paths):
                continue
        if not in_range(str(r.get("ts") or "")):
            continue
        filtered.append(r)

    filtered.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    return filtered
