from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .auth_support import _utc_now

DEFAULT_JSON_BACKUP_VERSIONS = 20
logger = logging.getLogger(__name__)


class JsonFileStore:
    """Small JSON-file persistence helper with atomic writes and multi-version .bak recovery."""

    def __init__(self, *, max_backup_versions: int = DEFAULT_JSON_BACKUP_VERSIONS) -> None:
        self.max_backup_versions = max(1, max_backup_versions)

    @staticmethod
    def backup_path(path: Path) -> Path:
        return path.with_suffix(path.suffix + ".bak")

    @staticmethod
    def recovery_log_path(path: Path) -> Path:
        return path.with_suffix(path.suffix + ".recovery.jsonl")

    def versioned_backup_path(self, path: Path) -> Path:
        day_key = _utc_now()[:10].replace("-", "")
        if len(day_key) != 8 or not day_key.isdigit():
            day_key = "unknown"
        return path.with_suffix(path.suffix + f".bak.{day_key}")

    def backup_paths_newest_first(self, path: Path) -> list[Path]:
        versioned = sorted(path.parent.glob(f"{path.name}.bak.*"), reverse=True)
        latest = self.backup_path(path)
        return ([latest] if latest.exists() else []) + versioned

    def prune_backups(self, path: Path) -> None:
        versioned = sorted(path.parent.glob(f"{path.name}.bak.*"), reverse=True)
        for backup in versioned[self.max_backup_versions:]:
            try:
                backup.unlink()
            except OSError:
                pass

    def read(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return copy.deepcopy(default)
        except json.JSONDecodeError:
            data = self._recover_from_backup(path, default)
        if not isinstance(data, dict):
            return copy.deepcopy(default)
        return data

    def _record_recovery_event(self, path: Path, *, action: str, backup: Path | None = None, message: str | None = None) -> None:
        payload = {
            "ts": _utc_now(),
            "action": action,
            "path": str(path),
            "backup": str(backup) if backup else None,
            "message": message,
        }
        try:
            with self.recovery_log_path(path).open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            logger.warning("auth_json_recovery_log_failed path=%s action=%s", path, action)

    def _recover_from_backup(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        for backup in self.backup_paths_newest_first(path):
            try:
                with backup.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    shutil.copy2(backup, path)
                    logger.warning("auth_json_recovered_from_backup path=%s backup=%s", path, backup)
                    self._record_recovery_event(path, action="recovered_from_backup", backup=backup)
                    return data
            except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                logger.warning("auth_json_backup_unusable path=%s backup=%s error=%s", path, backup, exc)
                self._record_recovery_event(path, action="backup_unusable", backup=backup, message=str(exc))
                continue
        logger.error("auth_json_recovery_failed path=%s", path)
        self._record_recovery_event(path, action="recovery_failed", message="no valid backup found")
        return copy.deepcopy(default)

    def write(self, path: Path, data: dict[str, Any], *, prefix: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                shutil.copy2(path, self.backup_path(path))
                versioned_backup = self.versioned_backup_path(path)
                if not versioned_backup.exists():
                    shutil.copy2(path, versioned_backup)
                self.prune_backups(path)
            except OSError:
                pass
        data["updated_at"] = _utc_now()
        fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
