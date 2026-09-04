from datetime import timezone

from requirement_scheduler.store import ScheduleStore
from requirement_scheduler.models import RecurrenceSpec, RunPolicy, ScheduleVersionCreate
import pytest


class Connection:
    def __init__(self): self.rows = []; self.commits = self.rollbacks = self.closed = 0; self.one = None
    def cursor(self): return self
    def execute(self, sql, *params):
        self.sql, self.params = sql, params
        if "[requirement_sets]" in sql: self.one = (params[0],)
        if sql.startswith("INSERT INTO") and "requirement_schedules" in sql: self.rows.append(params)
        return self
    def fetchall(self): return self.rows
    def fetchone(self): return self.one
    @property
    def description(self): return [(x,) for x in ("schedule_id", "name", "requirement_set_id", "enabled", "active_version_id", "next_run_at", "created_by", "created_at", "updated_by", "updated_at")]
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): self.closed += 1


class Registry:
    def __init__(self): self.connection = Connection()
    def open_named_connection(self, name): return self.connection


def test_create_is_disabled_parameterized_and_utc():
    registry = Registry(); store = ScheduleStore(registry, "control")
    created = store.create_schedule(name="Morning", requirement_set_id="set_1", actor="operator")
    assert created["enabled"] is False and created["next_run_at"] is None
    assert created["created_at"].tzinfo == timezone.utc
    assert "?" in registry.connection.sql and registry.connection.commits == 1 and registry.connection.closed == 1


def test_persistence_error_is_safe_and_rolls_back():
    class Broken(Connection):
        def execute(self, sql, *params): raise RuntimeError("Driver=secret; password=bad")
    registry = Registry(); registry.connection = Broken()
    store = ScheduleStore(registry, "control")
    try: store.create_schedule(name="x", requirement_set_id="set", actor="op")
    except RuntimeError as exc: assert str(exc) == "persistence_error"
    assert registry.connection.rollbacks == 1 and registry.connection.closed == 1


def test_domain_schedule_version_rejects_bad_timezone_and_model():
    recurrence=RecurrenceSpec.validate({"kind":"daily","local_time":"09:00:00"})
    with pytest.raises(ValueError, match="timezone_invalid"):
        ScheduleVersionCreate("No/Such_Zone", recurrence, RunPolicy.ALL_ACTIVE, "m")
    with pytest.raises(ValueError, match="schedule_model_invalid"):
        ScheduleVersionCreate("UTC", recurrence, RunPolicy.ALL_ACTIVE, "   ")
