from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .models import ScheduleAuditEvent


@dataclass(frozen=True)
class AuditDrainResult:
    attempted: int
    delivered: int
    failed: int


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone_naive")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def projection_record(event: ScheduleAuditEvent) -> dict:
    record = {
        "audit_event_id": event.audit_event_id,
        "action": event.action,
        "username": event.actor,
        "ts": _utc_iso(event.created_at),
    }
    if event.schedule_id is not None:
        record["schedule_id"] = event.schedule_id
    if event.schedule_version_id is not None:
        record["schedule_version_id"] = event.schedule_version_id
    record.update(event.payload)
    return record


def drain_audit_outbox(store, sink: Callable[[dict], None], *, limit: int,
                       now_utc: datetime) -> AuditDrainResult:
    """Bounded at-least-once projection; sink I/O is outside SQL transactions."""
    events = store.list_pending_audit_events(limit)
    delivered = failed = 0
    for event in events:
        try:
            sink(projection_record(event))
        except Exception:
            store.mark_audit_failed(event.audit_event_id, now_utc)
            failed += 1
        else:
            store.mark_audit_delivered(event.audit_event_id, now_utc)
            delivered += 1
    return AuditDrainResult(len(events), delivered, failed)
