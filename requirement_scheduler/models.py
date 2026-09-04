from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from typing import Any


class RunPolicy(StrEnum):
    ALL_ACTIVE = "all_active"
    NEW_OR_CHANGED = "new_or_changed"
    CHANGED_ONLY = "changed_only"


@dataclass(frozen=True)
class RecurrenceSpec:
    kind: str
    local_time: time | None = None
    weekdays: tuple[int, ...] = ()
    day: int | None = None
    invalid_day: str | None = None
    every: int | None = None
    unit: str | None = None
    anchor_at: datetime | None = None

    @classmethod
    def validate(cls, value: dict[str, Any]) -> "RecurrenceSpec":
        if not isinstance(value, dict) or value.get("kind") not in {"daily", "weekly", "monthly", "interval"}:
            raise ValueError("recurrence_invalid")
        kind = value["kind"]
        allowed = {
            "daily": {"kind", "local_time"},
            "weekly": {"kind", "weekdays", "local_time"},
            "monthly": {"kind", "day", "local_time", "invalid_day"},
            "interval": {"kind", "every", "unit", "anchor_at"},
        }[kind]
        if set(value) != allowed:
            raise ValueError("recurrence_invalid")
        if kind == "interval":
            every = value["every"]
            if isinstance(every, bool) or not isinstance(every, int) or not 1 <= every <= 10080 or value["unit"] not in {"minutes", "hours", "days"}:
                raise ValueError("recurrence_invalid")
            try: anchor = datetime.fromisoformat(value["anchor_at"])
            except (TypeError, ValueError): raise ValueError("recurrence_invalid") from None
            if anchor.tzinfo is None or anchor.utcoffset() is None:
                raise ValueError("timezone_naive")
            return cls(kind=kind, every=every, unit=value["unit"], anchor_at=anchor)
        try: local = time.fromisoformat(value["local_time"])
        except (TypeError, ValueError): raise ValueError("recurrence_invalid") from None
        if local.microsecond:
            raise ValueError("recurrence_second_precision_required")
        if kind == "daily": return cls(kind=kind, local_time=local)
        if kind == "weekly":
            days = value["weekdays"]
            if not isinstance(days, list) or not days or any(isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 7 for d in days) or days != sorted(set(days)):
                raise ValueError("recurrence_invalid")
            return cls(kind=kind, local_time=local, weekdays=tuple(days))
        day = value["day"]
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31 or value["invalid_day"] != "last_day":
            raise ValueError("recurrence_invalid")
        return cls(kind=kind, local_time=local, day=day, invalid_day="last_day")

    def as_dict(self) -> dict[str, Any]:
        if self.kind == "interval":
            return {"kind": self.kind, "every": self.every, "unit": self.unit, "anchor_at": self.anchor_at.isoformat()}
        result: dict[str, Any] = {"kind": self.kind, "local_time": self.local_time.isoformat()}
        if self.kind == "weekly": result["weekdays"] = list(self.weekdays)
        if self.kind == "monthly": result.update(day=self.day, invalid_day=self.invalid_day)
        return result


@dataclass(frozen=True)
class ScheduleVersionCreate:
    timezone: str
    recurrence: RecurrenceSpec
    run_policy: RunPolicy
    model: str


@dataclass(frozen=True)
class TriggerIdentity:
    trigger_type: str
    scheduled_for: datetime | None = None
    trigger_request_id: str | None = None

    def __post_init__(self):
        if self.trigger_type not in {"scheduled", "manual"}: raise ValueError("trigger_invalid")
        if self.trigger_type == "scheduled" and self.scheduled_for is None: raise ValueError("trigger_invalid")


@dataclass(frozen=True)
class MaterializedRun:
    run: dict[str, Any]
    items: tuple[dict[str, Any], ...]
