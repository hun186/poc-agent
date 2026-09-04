from __future__ import annotations

from datetime import datetime


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError("timezone_naive")


class ScheduleService:
    """Control-plane orchestration only; deliberately has no execution dependencies."""
    def __init__(self, store): self.store = store

    def approve_version(self, *, schedule_id: str, version_number: int, actor: str, now_utc: datetime):
        _require_aware(now_utc)
        return self.store.approve_version(schedule_id=schedule_id, version_number=version_number, actor=actor, now_utc=now_utc)

    def set_enabled(self, *, schedule_id: str, enabled: bool, actor: str, now_utc: datetime):
        _require_aware(now_utc)
        return self.store.set_enabled(schedule_id=schedule_id, enabled=enabled, actor=actor, now_utc=now_utc)
