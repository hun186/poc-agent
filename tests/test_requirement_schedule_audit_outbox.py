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



def test_product_task_updated_audit_payload_is_bounded_and_explicit():
    at = datetime(2026, 10, 8, 4, 0, tzinfo=timezone.utc)
    event = ScheduleStore._audit_event(
        "requirement.task.updated",
        "admin",
        "sch-1",
        schedule_version_id="sv-draft-1",
        payload={
            "task_id": "task-1",
            "revision": 8,
            "operation": "task_version_activate",
        },
        created_at=at,
    )

    assert event.action == "requirement.task.updated"
    assert event.schedule_id == "sch-1"
    assert event.schedule_version_id == "sv-draft-1"
    assert event.payload == {
        "task_id": "task-1",
        "revision": 8,
        "operation": "task_version_activate",
    }

    with pytest.raises(ValueError, match="audit_payload_invalid"):
        ScheduleStore._audit_event(
            "requirement.task.updated",
            "admin",
            "sch-1",
            payload={
                "task_id": "task-1",
                "revision": 8,
                "operation": "task_version_activate",
                "raw_sql": "select secret",
            },
            created_at=at,
        )
