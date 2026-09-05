from datetime import datetime, timedelta, timezone

from requirement_scheduler.audit_delivery import drain_audit_outbox, projection_record
from requirement_scheduler.models import ScheduleAuditEvent


CREATED = datetime(2026, 9, 5, 1, 2, 3, tzinfo=timezone.utc)


def event():
    return ScheduleAuditEvent("aud_1", "requirement_schedule.enabled", "operator", "s1", "v1", {}, CREATED)


class Store:
    def __init__(self):
        self.events = (event(),); self.delivered = []; self.failed = []
    def list_pending_audit_events(self, limit): return self.events[:limit]
    def mark_audit_delivered(self, event_id, at): self.delivered.append((event_id, at)); return True
    def mark_audit_failed(self, event_id, at): self.failed.append((event_id, at)); return True


def test_projection_uses_immutable_lifecycle_time_and_stable_identity():
    assert projection_record(event())["ts"] == "2026-09-05T01:02:03Z"
    assert projection_record(event())["audit_event_id"] == "aud_1"


def test_bounded_delivery_and_safe_retry_failure():
    now = CREATED + timedelta(hours=4); store = Store(); records = []
    result = drain_audit_outbox(store, records.append, limit=1, now_utc=now)
    assert (result.attempted, result.delivered, result.failed) == (1, 1, 0)
    assert records[0]["ts"] == "2026-09-05T01:02:03Z"
    failing = Store()
    result = drain_audit_outbox(failing, lambda _: (_ for _ in ()).throw(RuntimeError("/secret/path")), limit=1, now_utc=now)
    assert result.failed == 1 and failing.failed == [("aud_1", now)]
