from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .auth_json_store import JsonFileStore
from .auth_support import LOGIN_AUDIT_LIMIT, _utc_now


class LoginAuditStore:
    """Sharded login audit store backed by monthly JSON files."""

    def __init__(self, manifest_path: Path, users_path: Path, json_store: JsonFileStore) -> None:
        self.manifest_path = manifest_path
        self.users_path = users_path
        self._json = json_store
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_dir().mkdir(parents=True, exist_ok=True)

    def ensure(self) -> None:
        self.audit_dir().mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            existing = self._json.read(self.manifest_path, {})
            legacy_audit = existing.get("events") if isinstance(existing, dict) else None
            if isinstance(legacy_audit, list):
                self.append_events([item for item in legacy_audit if isinstance(item, dict)])
            if existing.get("storage") == "sharded":
                return
        self.append_events(self._legacy_events_from_users_file())
        self.write_manifest()

    def _legacy_events_from_users_file(self) -> list[dict[str, Any]]:
        try:
            with self.users_path.open("r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            legacy_audit = legacy_data.get("login_audit") if isinstance(legacy_data, dict) else None
            if isinstance(legacy_audit, list):
                return [item for item in legacy_audit[-LOGIN_AUDIT_LIMIT:] if isinstance(item, dict)]
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass
        return []

    def audit_dir(self) -> Path:
        return self.manifest_path.with_suffix(self.manifest_path.suffix + ".d")

    def shard_path(self, ts: str | None = None) -> Path:
        shard_key = (ts or _utc_now())[:7].replace("-", "")
        if len(shard_key) != 6 or not shard_key.isdigit():
            shard_key = _utc_now()[:7].replace("-", "")
        return self.audit_dir() / f"login_audit-{shard_key}.json"

    def shard_paths_newest_first(self) -> list[Path]:
        return sorted(self.audit_dir().glob("login_audit-*.json"), reverse=True)

    def write_manifest(self) -> None:
        self._json.write(
            self.manifest_path,
            {"storage": "sharded", "shard_dir": str(self.audit_dir()), "created_at": _utc_now()},
            prefix=".login_audit_manifest.",
        )

    def append_events(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        grouped: dict[Path, list[dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(self.shard_path(str(event.get("ts") or "")), []).append(event)
        for shard_path, shard_events in grouped.items():
            data = self._json.read(shard_path, {"events": []})
            audit = data.setdefault("events", [])
            audit.extend(shard_events)
            if len(audit) > LOGIN_AUDIT_LIMIT:
                del audit[:-LOGIN_AUDIT_LIMIT]
            self._json.write(shard_path, data, prefix=".login_audit_shard.")

    def record(self, username: str, *, success: bool, reason: str, role: str | None = None, status_value: str | None = None, client_host: str | None = None, user_agent: str | None = None) -> None:
        self.append_events([{
            "ts": _utc_now(),
            "username": username,
            "success": success,
            "reason": reason,
            "role": role,
            "status": status_value,
            "client_host": client_host,
            "user_agent": user_agent,
        }])
        self.write_manifest()

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, LOGIN_AUDIT_LIMIT))
        events: list[dict[str, Any]] = []
        for shard_path in self.shard_paths_newest_first():
            shard_events = self._json.read(shard_path, {"events": []}).get("events", [])
            if not isinstance(shard_events, list):
                continue
            events.extend(item for item in reversed(shard_events) if isinstance(item, dict))
            if len(events) >= limit:
                break
        return list(reversed(events[:limit]))
