from datetime import datetime, timezone

import pytest

from requirement_scheduler.store import ScheduleStore


def test_audit_payload_is_bounded_and_rejects_secret_shaped_fields():
    at = datetime(2026, 9, 5, tzinfo=timezone.utc)
    event = ScheduleStore._audit_event("requirement_schedule.created", "operator", "s1", payload={"requirement_set_id": "set"}, created_at=at)
    assert event.created_at == at and event.payload == {"requirement_set_id": "set"}
    for key in ("password", "access_token", "connection_string", "raw_sql", "absolute_path", "traceback"):
        with pytest.raises(ValueError, match="audit_payload_invalid"):
            ScheduleStore._audit_event("requirement_schedule.created", "operator", "s1", payload={key: "x"})


def test_delivery_updates_are_pending_row_compare_and_set():
    class Cursor:
        rowcount = 0
        def execute(self, sql, *params):
            assert "delivered_at IS NULL" in sql
            return self
    class Connection(Cursor):
        def cursor(self): return self
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
    class Registry:
        def open_named_connection(self, _): return Connection()
    store = ScheduleStore(Registry(), "db")
    assert store.mark_audit_delivered("aud", datetime.now(timezone.utc)) is False
    assert store.mark_audit_failed("aud", datetime.now(timezone.utc)) is False
