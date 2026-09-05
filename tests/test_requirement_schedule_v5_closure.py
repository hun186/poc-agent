from datetime import datetime, timezone

import pytest

from requirement_scheduler.audit_delivery import drain_audit_outbox
from requirement_scheduler.migrations import (
    REQUIRED_COLUMNS, REQUIRED_FILTERED_INDEXES, REQUIRED_KEYS,
    canonical_v2_statements, migration_1_to_2_statements,
    required_foreign_keys, validation_queries,
)
from requirement_scheduler.models import RunPolicy, ScheduleAuditEvent
from requirement_scheduler.store import ScheduleStore


class FreshCursor:
    """DB-API-only executable fresh-schema fake; no production-only catalog hook."""
    def __init__(self):
        self.sql = []
        self._rows = []
        self.marker_written = False
        self.rowcount = 1

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        self._rows = []
        if "OBJECT_ID" in sql:
            self._rows = [(None,)]
        elif sql.startswith("SELECT version"):
            self._rows = [(2,)] if self.marker_written else []
        elif sql.startswith("INSERT INTO [sra_schedule].[schema_version]"):
            self.marker_written = True
        elif "SELECT t.name FROM sys.tables" in sql:
            self._rows = [(name,) for name in sorted(REQUIRED_COLUMNS)]
        elif "SELECT t.name,c.name" in sql:
            self._rows = [(table, c.name, c.sql_type, c.max_length, c.nullable, c.ordinal)
                          for table in sorted(REQUIRED_COLUMNS) for c in REQUIRED_COLUMNS[table]]
        elif "SELECT t.name,kc.name" in sql:
            self._rows = [(k.table, k.name, k.kind, c, i) for k in REQUIRED_KEYS
                          for i, c in enumerate(k.columns, 1)]
        elif "SELECT t.name,i.name" in sql:
            self._rows = [(index.table, index.name, index.is_unique, True,
                           index.filter_definition, c, i)
                          for index in REQUIRED_FILTERED_INDEXES
                          for i, c in enumerate(index.columns, 1)]
        elif "SELECT pt.name,fk.name" in sql:
            self._rows = [(fk.table, fk.name, c, fk.referenced_schema,
                           fk.referenced_table, rc, i, 0)
                          for fk in required_foreign_keys("sra_schedule", "sra_requirement")
                          for i, (c, rc) in enumerate(zip(fk.columns, fk.referenced_columns), 1)]
        elif params and isinstance(params[-1], str):
            expected = next((e for _, query, query_params, e in validation_queries("sra_schedule", "sra_requirement")
                             if query == sql and query_params == params), None)
            if expected is not None:
                if hasattr(expected, "sql_type"):
                    raise AssertionError("unreachable")
                if isinstance(expected, tuple):
                    self._rows = [(c.name, c.sql_type, c.max_length, c.nullable, c.ordinal) for c in expected]
                elif expected.__class__.__name__ == "KeyConstraint":
                    self._rows = [("sra_schedule", expected.table, expected.name, expected.kind, c, i)
                                  for i, c in enumerate(expected.columns, 1)]
                elif expected.__class__.__name__ == "FilteredIndex":
                    self._rows = [("sra_schedule", expected.table, expected.name, expected.is_unique, True,
                                   expected.filter_definition, c, i) for i, c in enumerate(expected.columns, 1)]
                else:
                    self._rows = [("sra_schedule", expected.table, expected.name, c,
                                   expected.referenced_schema, expected.referenced_table, rc, i)
                                  for i, (c, rc) in enumerate(zip(expected.columns, expected.referenced_columns), 1)]
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class Connection:
    def __init__(self):
        self.cursor_value = FreshCursor(); self.commits = 0; self.rollbacks = 0
    def cursor(self): return self.cursor_value
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


class Registry:
    def __init__(self, connection): self.connection = connection
    def open_named_connection(self, _): return self.connection


def test_initialize_executes_explicit_fresh_v2_and_rereads_marker_last():
    connection = Connection()
    ScheduleStore(Registry(connection), "db").initialize()
    statements = [sql for sql, _ in connection.cursor_value.sql]
    assert connection.commits == 1 and connection.rollbacks == 0
    marker_write = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO [sra_schedule].[schema_version]"))
    assert all("CREATE " not in sql and "ALTER " not in sql for sql in statements[marker_write + 1:])
    assert statements[-1].startswith("SELECT version")
    assert not any("requirement_schedule_catalog" in sql for sql in statements)


def test_canonical_widths_outbox_and_index_are_exact():
    columns = {c.name: c.max_length for table in ("requirement_schedule_versions", "requirement_batch_runs", "requirement_batch_run_items") for c in REQUIRED_COLUMNS[table]}
    assert columns["run_policy"] == 64 and columns["status"] == 40
    assert columns["trigger_type"] == 32 and columns["selection_status"] == 32
    assert columns["execution_state"] == 64 and columns["remote_job_state"] == 64
    assert columns["phase1a_task_id"] == 480
    pending = REQUIRED_FILTERED_INDEXES[-1]
    assert pending.columns == ("delivered_at", "created_at", "audit_event_id") and pending.is_unique is False
    ddl = "\n".join(canonical_v2_statements("sra_schedule", "sra_requirement"))
    assert "safe_payload_json NVARCHAR(2000) NOT NULL" in ddl
    assert "action NVARCHAR(96) NOT NULL" in ddl and "batch_run_id NVARCHAR(64) NULL" in ddl
    assert "migration_0_to_1_statements" not in canonical_v2_statements.__code__.co_names


def test_shape_specific_migrations_do_not_form_hybrids():
    pr200 = "\n".join(migration_1_to_2_statements("sra_schedule", "pr200_v1"))
    pr201 = "\n".join(migration_1_to_2_statements("sra_schedule", "pr201_v1"))
    assert "DROP CONSTRAINT" not in pr200
    for name in ("FK_run_schedule", "FK_run_item_run", "FK_state_schedule", "FK_state_success_item"):
        assert f"ADD CONSTRAINT {name}" in pr200
    assert "DROP CONSTRAINT FK_schedule_active_version" in pr201
    assert "DROP CONSTRAINT FK_run_schedule_version" in pr201
    assert "UPDATE" not in pr201


@pytest.mark.parametrize("policy", list(RunPolicy))
def test_persisted_run_policy_is_explicitly_coerced(policy):
    config = ScheduleStore._validate_persisted_config(
        "UTC", '{"kind":"daily","local_time":"01:00:00"}', policy.value, "model"
    )
    assert config.run_policy is policy


def test_invalid_persisted_run_policy_is_rejected_safely():
    with pytest.raises(ValueError, match="recurrence_invalid"):
        ScheduleStore._validate_persisted_config("UTC", '{"kind":"daily","local_time":"01:00:00"}', "unsafe", "model")


def test_action_payloads_are_positive_allowlists():
    ScheduleStore._audit_event("requirement_schedule.created", "actor", "s", payload={"requirement_set_id": "r"})
    with pytest.raises(ValueError, match="audit_payload_invalid"):
        ScheduleStore._audit_event("requirement_schedule.created", "actor", "s", payload={"metadata": "arbitrary"})


def test_projection_lost_races_do_not_claim_delivery_or_failure():
    event = ScheduleAuditEvent("a", "requirement_schedule.enabled", "actor", "s", None, {}, datetime.now(timezone.utc))
    class LostRace:
        def list_pending_audit_events(self, limit): return (event,)
        def mark_audit_delivered(self, *_): return False
        def mark_audit_failed(self, *_): return False
    result = drain_audit_outbox(LostRace(), lambda _: None, limit=1, now_utc=datetime.now(timezone.utc))
    assert (result.attempted, result.delivered, result.failed) == (1, 0, 0)
    result = drain_audit_outbox(LostRace(), lambda _: (_ for _ in ()).throw(OSError()), limit=1, now_utc=datetime.now(timezone.utc))
    assert (result.attempted, result.delivered, result.failed) == (1, 0, 0)


def test_gate_b_implementation_remains_absent():
    # Gate A has schema-reserved columns only; it exposes no execution bridge/worker.
    import pathlib
    sources = "\n".join(p.read_text() for p in pathlib.Path("requirement_scheduler").glob("*.py"))
    for forbidden in ("ReportJobWorker", "batch_scheduler.store", "elasticsearch", "manual_execute"):
        assert forbidden not in sources
