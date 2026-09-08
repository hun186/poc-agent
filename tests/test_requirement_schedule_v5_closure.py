from copy import deepcopy
from datetime import datetime, timezone

import pytest

from requirement_scheduler.audit_delivery import drain_audit_outbox
from requirement_scheduler.migrations import (
    REQUIRED_CHECKS, REQUIRED_COLUMNS, REQUIRED_DEFAULTS, REQUIRED_FILTERED_INDEXES, REQUIRED_KEYS,
    canonical_v2_statements, migration_1_to_2_statements,
    required_foreign_keys, validation_queries,
)
import requirement_scheduler.migrations as migrations
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
            self._rows = [(3,)] if self.marker_written else []
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
                           fk.referenced_table, rc, i, 0, 0)
                          for fk in required_foreign_keys("sra_schedule", "sra_requirement")
                          for i, (c, rc) in enumerate(zip(fk.columns, fk.referenced_columns), 1)]
        elif "sys.default_constraints" in sql and len(params) == 1:
            self._rows = [(d.table, d.name, d.column, "((0))") for d in REQUIRED_DEFAULTS]
        elif "sys.check_constraints" in sql and len(params) == 1:
            self._rows = [(c.table, c.name, c.definition) for c in REQUIRED_CHECKS]
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
                elif expected.__class__.__name__ == "ForeignKey":
                    self._rows = [("sra_schedule", expected.table, expected.name, c,
                                   expected.referenced_schema, expected.referenced_table, rc, i, 0, 0)
                                  for i, (c, rc) in enumerate(zip(expected.columns, expected.referenced_columns), 1)]
                elif expected.__class__.__name__ == "DefaultConstraint":
                    self._rows = [("sra_schedule", expected.table, expected.name, expected.column, "((0))")]
                else:
                    self._rows = [("sra_schedule", expected.table, expected.name, expected.definition)]
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


def test_sql_server_not_like_placement_normalizes_for_digest_checks():
    assert migrations.normalize_sql_predicate(
        "artifact_sha256 NOT LIKE '%[^0-9a-f]%'"
    ) == migrations.normalize_sql_predicate(
        "NOT [artifact_sha256] LIKE '%[^0-9a-f]%'"
    )
    assert migrations.normalize_sql_predicate(
        "artifact_sha256 IS NULL OR artifact_sha256 NOT LIKE '%[^0-9a-f]%' "
        "AND LEN(artifact_sha256)=64"
    ) == migrations.normalize_sql_predicate(
        "([artifact_sha256] IS NULL OR NOT [artifact_sha256] like "
        "'%[^0-9a-f]%' AND len([artifact_sha256])=(64))"
    )
    assert migrations.normalize_sql_predicate(
        "semantic_fingerprint NOT LIKE '%[^0-9a-f]%' "
        "AND LEN(semantic_fingerprint)=64"
    ) == migrations.normalize_sql_predicate(
        "(NOT [semantic_fingerprint] LIKE '%[^0-9a-f]%' "
        "AND LEN([semantic_fingerprint])=(64))"
    )
    assert migrations.normalize_sql_predicate(
        "example = 'NOT artifact_sha256 LIKE'"
    ) == "example='notartifact_sha256like'"


@pytest.mark.parametrize(
    ("constraint_name", "sql_server_definition"),
    (
        (
            "CK_requirement_batch_run_item_artifact_sha256",
            "([artifact_sha256] IS NULL OR NOT [artifact_sha256] like "
            "'%[^0-9a-f]%' AND len([artifact_sha256])=(64))",
        ),
        (
            "CK_handoff_submission_fingerprint",
            "(NOT [semantic_fingerprint] like '%[^0-9a-f]%' "
            "AND len([semantic_fingerprint])=(64))",
        ),
    ),
)
def test_check_catalog_accepts_sql_server_not_like_placement(
    constraint_name, sql_server_definition
):
    expected = next(check for check in REQUIRED_CHECKS if check.name == constraint_name)
    rows = (("sra_schedule", expected.table, expected.name, sql_server_definition),)
    assert migrations.validate_catalog_evidence("sra_schedule", expected, rows)


@pytest.mark.parametrize(
    "drifted_definition",
    (
        "([artifact_sha256] IS NULL OR NOT [some_other_column] like "
        "'%[^0-9a-f]%' AND len([artifact_sha256])=(64))",
        "([artifact_sha256] IS NULL OR NOT [artifact_sha256] like "
        "'%[^0-9]%' AND len([artifact_sha256])=(64))",
        "([artifact_sha256] IS NULL OR NOT [artifact_sha256] like "
        "'%[^0-9a-f]%' AND len([artifact_sha256])=(63))",
        "([artifact_sha256] IS NULL OR [artifact_sha256] like "
        "'%[^0-9a-f]%' AND len([artifact_sha256])=(64))",
        "([artifact_sha256] IS NOT NULL OR NOT [artifact_sha256] like "
        "'%[^0-9a-f]%' AND len([artifact_sha256])=(64))",
    ),
)
def test_check_catalog_rejects_digest_semantic_drift(drifted_definition):
    expected = next(
        check for check in REQUIRED_CHECKS
        if check.name == "CK_requirement_batch_run_item_artifact_sha256"
    )
    rows = (("sra_schedule", expected.table, expected.name, drifted_definition),)
    assert not migrations.validate_catalog_evidence("sra_schedule", expected, rows)


def test_initialize_executes_explicit_fresh_v2_and_rereads_marker_last():
    connection = Connection()
    ScheduleStore(Registry(connection), "db").initialize()
    statements = [sql for sql, _ in connection.cursor_value.sql]
    assert connection.commits == 1 and connection.rollbacks == 0
    marker_write = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO [sra_schedule].[schema_version]"))
    assert all("CREATE " not in sql and "ALTER " not in sql for sql in statements[marker_write + 1:])
    assert statements[-1].startswith("SELECT version")
    assert not any("requirement_schedule_catalog" in sql for sql in statements)


def test_marker_reread_accepts_dbapi_indexable_rows_without_tuple_equality():
    class Row:
        def __init__(self, value): self.value = value
        def __getitem__(self, index): return self.value if index == 0 else (_ for _ in ()).throw(IndexError())
        def __len__(self): return 1
        def __eq__(self, other): return False
    connection = Connection()
    original = connection.cursor_value.fetchall
    connection.cursor_value.fetchall = lambda: [Row(3)] if connection.cursor_value.sql[-1][0].startswith("SELECT version") and connection.cursor_value.marker_written else original()
    ScheduleStore(Registry(connection), "db").initialize()
    assert connection.commits == 1


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
    repair = ScheduleStore(Registry(Connection()), "db")._pr200_identity_repair_statements()
    assert "LEN(q.external_item_id)>240" in repair[-3]
    assert "phase1a_task_id=q.external_item_id" in repair[-1]
    assert "materialized" not in repair[0]


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


class IndexableRow:
    """Small pyodbc.Row analogue: indexable, sized, and deliberately not a tuple."""

    def __init__(self, *values):
        self.values = values

    def __getitem__(self, index):
        return self.values[index]

    def __len__(self):
        return len(self.values)

    def __iter__(self):
        return iter(self.values)

    def __eq__(self, other):
        return self is other


def _catalog(shape):
    if shape == "v2":
        return {
            "columns": deepcopy(REQUIRED_COLUMNS),
            "keys": tuple(REQUIRED_KEYS),
            "indexes": tuple(REQUIRED_FILTERED_INDEXES),
            "foreign_keys": required_foreign_keys("sra_schedule", "sra_requirement"),
            "defaults": tuple(REQUIRED_DEFAULTS),
            "checks": tuple(REQUIRED_CHECKS),
        }
    names = migrations._PR200_FK_NAMES if shape == "pr200_v1" else migrations._PR201_FK_NAMES
    return {
        "columns": migrations._v1_columns(shape),
        "keys": tuple(k for k in REQUIRED_KEYS if k.name not in {
            "UQ_requirement_schedule_version_owner", "PK_requirement_schedule_audit_outbox"
        }),
        "indexes": tuple(REQUIRED_FILTERED_INDEXES[:2]),
        "foreign_keys": tuple(fk for fk in migrations.v1_foreign_keys(
            "sra_schedule", "sra_requirement") if fk.name in names),
        "defaults": (),
        "checks": (),
    }


class StatefulDatabase:
    """Transactional SQL Server model for the exact scheduler SQL surface.

    It intentionally interprets only statements emitted by ScheduleStore.  Catalog
    reads use normal execute/fetch methods, while DDL and UPDATE statements change
    durable modeled state.  A rollback restores a deep transaction snapshot.
    """

    def __init__(self, shape="pr200_v1", *, marker_rows=None, marker_table=True,
                 external_id="external-1", config_rows=(), fail_at=None,
                 guard_token=None, final_marker_rows=None, catalog_mutator=None):
        self.shape = shape
        self.marker_table = marker_table
        self.marker_rows = list(marker_rows if marker_rows is not None else
                                ([] if not marker_table else [1 if shape != "v2" else 2]))
        self.catalog = _catalog(shape) if marker_table else {
            "columns": {}, "keys": (), "indexes": (), "foreign_keys": (),
            "defaults": (), "checks": (),
        }
        self.width = 480 if shape == "v2" else 256
        self.batch_identity = "reqrun-run-1" if shape == "v2" else "phase1c-run-1"
        self.selected_identity = external_id if shape in {"v2", "pr201_v1"} else "req-1"
        self.skipped_identity = None
        self.external_id = external_id
        self.config_rows = list(config_rows)
        self.outbox_exists = shape == "v2"
        self.sql = []
        self.rowcount = 1
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
        self.fail_at = fail_at
        self.guard_token = guard_token
        self.final_marker_rows = final_marker_rows
        self.catalog_mutator = catalog_mutator
        self.mutations = []
        self._rows = []
        self._snapshot = self._state()

    def _state(self):
        return deepcopy((self.marker_table, self.marker_rows, self.catalog, self.width,
                         self.batch_identity, self.selected_identity,
                         self.skipped_identity, self.outbox_exists))

    def cursor(self):
        return self

    def _catalog_rows(self, sql, params):
        c = self.catalog
        if "SELECT t.name FROM sys.tables" in sql:
            return [(name,) for name in sorted(c["columns"])]
        if (sql.startswith("SELECT t.name,c.name,ty.name")
                or sql.startswith("SELECT c.name,ty.name")):
            table = params[1] if len(params) == 2 else None
            return [(name, col.name, col.sql_type, col.max_length, col.nullable, col.ordinal)
                    for name in sorted(c["columns"]) if table is None or name == table
                    for col in c["columns"][name]][:] if len(params) == 1 else [
                        (col.name, col.sql_type, col.max_length, col.nullable, col.ordinal)
                        for col in c["columns"].get(table, ())]
        if "sys.key_constraints" in sql:
            wanted = params[1] if len(params) == 2 else None
            rows = [(k.table, k.name, k.kind, col, ordinal) for k in c["keys"]
                    if wanted is None or k.name == wanted
                    for ordinal, col in enumerate(k.columns, 1)]
            return rows if len(params) == 1 else [
                ("sra_schedule", table, name, kind, col, ordinal)
                for table, name, kind, col, ordinal in rows]
        if "sys.indexes" in sql:
            wanted = params[1] if len(params) == 2 else None
            rows = [(i.table, i.name, i.is_unique, True,
                     " ( [" + i.filter_definition.replace("=", "] = [") + "] ) ", col, ordinal)
                    for i in c["indexes"] if wanted is None or i.name == wanted
                    for ordinal, col in enumerate(i.columns, 1)]
            return rows if len(params) == 1 else [("sra_schedule",) + row for row in rows]
        if "sys.foreign_keys" in sql:
            wanted = params[1] if len(params) == 2 else None
            rows = [(fk.table, fk.name, col, fk.referenced_schema, fk.referenced_table,
                     ref, ordinal, fk.delete_action, fk.update_action)
                    for fk in c["foreign_keys"] if wanted is None or fk.name == wanted
                    for ordinal, (col, ref) in enumerate(zip(fk.columns, fk.referenced_columns), 1)]
            return rows if len(params) == 1 else [("sra_schedule",) + row for row in rows]
        if "sys.default_constraints" in sql:
            wanted = params[1] if len(params) == 2 else None
            rows = [(d.table, d.name, d.column, "((0))") for d in c["defaults"]
                    if wanted is None or d.name == wanted]
            return rows if len(params) == 1 else [("sra_schedule",) + row for row in rows]
        if "sys.check_constraints" in sql:
            wanted = params[1] if len(params) == 2 else None
            rows = [(item.table, item.name, item.definition)
                    for item in c["checks"] if wanted is None or item.name == wanted]
            return rows if len(params) == 1 else [("sra_schedule",) + row for row in rows]
        return None

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        self._rows = []
        self.rowcount = 1
        if self.fail_at and self.fail_at(sql, len(self.sql)):
            raise RuntimeError("injected migration failure")
        if "OBJECT_ID" in sql:
            self._rows = [(object(),)] if self.marker_table else [(None,)]
            return self
        if sql.startswith("IF SCHEMA_ID"):
            return self
        if sql.startswith("IF OBJECT_ID"):
            self.marker_table = True
            self.marker_rows = []
            self.mutations.append("bootstrap")
            return self
        if sql.startswith("SELECT version"):
            rows = self.marker_rows
            if self.final_marker_rows is not None and any(
                    text.startswith(("INSERT INTO [sra_schedule].[schema_version]",
                                     "UPDATE [sra_schedule].[schema_version]")) for text, _ in self.sql):
                rows = self.final_marker_rows
            self._rows = [IndexableRow(*row) if isinstance(row, tuple) else IndexableRow(row)
                          for row in rows]
            return self
        catalog_rows = self._catalog_rows(sql, params)
        if catalog_rows is not None:
            self._rows = catalog_rows
            return self
        if "SELECT v.timezone" in sql:
            self._rows = self.config_rows
            return self
        if sql.startswith("IF EXISTS"):
            if self.guard_token and self.guard_token in sql:
                raise RuntimeError("unsupported_requirement_schedule_schema")
            if "LEN(q.external_item_id)>240" in sql and len(self.external_id) > 240:
                raise RuntimeError("unsupported_requirement_schedule_schema")
            return self
        if "ALTER COLUMN phase1a_task_id" in sql:
            self.width = 480
            self.mutations.append("widen")
        elif sql.startswith("UPDATE [sra_schedule].[requirement_batch_runs]"):
            self.batch_identity = "reqrun-run-1"
            self.mutations.append("repair_batch")
        elif sql.startswith("UPDATE i SET phase1a_task_id"):
            self.selected_identity = self.external_id
            self.mutations.append("repair_item")
        elif sql.startswith("CREATE TABLE [sra_schedule].[requirement_schedules]"):
            self.mutations.append("fresh_ddl")
        elif sql.startswith("CREATE INDEX IX_requirement_schedule_audit_pending"):
            self.catalog = _catalog("v2")
            if self.catalog_mutator:
                self.catalog_mutator(self.catalog)
            self.outbox_exists = True
            self.mutations.append("canonical_catalog")
        elif sql.startswith("ALTER TABLE") or sql.startswith("CREATE TABLE"):
            self.mutations.append(sql.split()[0].lower())
        if sql.startswith("INSERT INTO [sra_schedule].[schema_version]"):
            self.marker_rows = [3]
            self.mutations.append("marker")
        elif sql.startswith("UPDATE [sra_schedule].[schema_version]"):
            self.marker_rows = [3] if self.marker_rows in ([1], [2]) else self.marker_rows
            self.rowcount = 1 if self.marker_rows == [3] else 0
            self.mutations.append("marker")
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def commit(self):
        self.commits += 1
        self._snapshot = self._state()

    def rollback(self):
        self.rollbacks += 1
        (self.marker_table, self.marker_rows, self.catalog, self.width,
         self.batch_identity, self.selected_identity, self.skipped_identity,
         self.outbox_exists) = deepcopy(self._snapshot)

    def close(self):
        self.closed += 1


def _initialize(database, **kwargs):
    return ScheduleStore(Registry(database), "db", **kwargs).initialize()


def test_stateful_fresh_and_existing_v2_public_initialization_paths():
    fresh = StatefulDatabase(marker_table=False)
    _initialize(fresh)
    assert fresh.marker_rows == [3] and fresh.catalog == _catalog("v2")
    assert fresh.commits == 1 and fresh.rollbacks == 0
    assert fresh.mutations[-1] == "marker"
    assert fresh.sql[-1][0].startswith("SELECT version")
    assert not any("ALTER COLUMN" in sql for sql, _ in fresh.sql)

    existing = StatefulDatabase("v2")
    _initialize(existing)
    assert existing.marker_rows == [3] and existing.commits == 1
    assert sum("sys.columns" in sql for sql, _ in existing.sql) >= len(REQUIRED_COLUMNS) + 1


@pytest.mark.parametrize("shape", ["pr200_v1", "pr201_v1"])
def test_stateful_exact_v1_catalogs_migrate_through_public_initialize(shape):
    external_id = "外" * 200
    database = StatefulDatabase(shape, external_id=external_id)
    original_identity = database.selected_identity
    _initialize(database)
    assert database.marker_rows == [3] and database.catalog == _catalog("v2")
    assert database.width == 480 and database.commits == 1 and database.rollbacks == 0
    assert database.mutations[-1] == "marker"
    widen = database.mutations.index("widen")
    if shape == "pr200_v1":
        assert database.batch_identity == "reqrun-run-1"
        assert database.selected_identity == external_id and database.skipped_identity is None
        assert widen < database.mutations.index("repair_item")
        assert "repair_batch" in database.mutations
    else:
        assert database.selected_identity == original_identity
        assert "repair_batch" not in database.mutations and "repair_item" not in database.mutations
        statements = "\n".join(sql for sql, _ in database.sql)
        assert "DROP CONSTRAINT FK_schedule_active_version" in statements
        assert "DROP CONSTRAINT FK_run_schedule_version" in statements


def test_pr200_rejects_oversized_external_identity_before_any_mutation():
    database = StatefulDatabase("pr200_v1", external_id="x" * 241)
    before = database._state()
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        _initialize(database)
    assert database._state() == before and database.marker_rows == [1]
    assert "repair_batch" not in database.mutations and "repair_item" not in database.mutations


@pytest.mark.parametrize("guard_token", [
    "phase1a_source_sha256", "handoff_started_at", "deadline_elapsed_during_execution<>0",
    "success_count<>0", "remote_job_id", "remote_job_state", "artifact_relative_path",
    "dispatched_at", "remote_completed_at", "expired_before_handoff<>0",
    "last_successful_requirement_version_id", "phase1a_batch_id<>",
    "selection_status='selected'", "selection_status NOT IN", "v.requirement_version_id IS NULL",
])
def test_pr200_gate_b_guard_matrix_fails_closed_and_restores_state(guard_token):
    database = StatefulDatabase("pr200_v1", guard_token=guard_token)
    before = database._state()
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        _initialize(database)
    assert database._state() == before and database.marker_rows == [1]
    assert "repair_batch" not in database.mutations and "repair_item" not in database.mutations


def _config_row(*, timezone_name="UTC", recurrence='{"kind":"daily","local_time":"01:00:00"}',
                policy="all_active", model="model", digest="a" * 64, status="approved",
                enabled=False, active=False):
    version_id = "sv-1"
    return (timezone_name, recurrence, policy, model, digest, status, enabled,
            version_id if active else None, version_id, "approver" if status == "approved" else None,
            datetime.now(timezone.utc) if status == "approved" else None)


@pytest.mark.parametrize("change", [
    {"timezone_name": "Not/AZone"}, {"recurrence": "{}"}, {"policy": "unsafe"},
    {"model": ""}, {"digest": "bad"},
])
@pytest.mark.parametrize("authority", ["approved", "active"])
def test_recognized_v1_invalid_authoritative_config_fails_closed(change, authority):
    base = {"status": "approved"} if authority == "approved" else {
        "status": "draft", "enabled": True, "active": True
    }
    database = StatefulDatabase("pr201_v1", config_rows=[_config_row(**base, **change)])
    before = database._state()
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        _initialize(database)
    assert database._state() == before and database.mutations == []


def test_invalid_disabled_unapproved_history_is_not_broadened_into_migration_blocker():
    database = StatefulDatabase("pr201_v1", config_rows=[_config_row(
        status="draft", timezone_name="Not/AZone", policy="unsafe")])
    _initialize(database)
    assert database.marker_rows == [3]


@pytest.mark.parametrize("marker_rows", [[], [1, 1], [(1, "extra")], ["not-a-number"], [4], [-1]])
def test_preexisting_marker_authority_rejects_unsupported_evidence(marker_rows):
    database = StatefulDatabase("pr200_v1", marker_rows=marker_rows)
    before = database._state()
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        _initialize(database)
    assert database._state() == before and database.commits == 0


@pytest.mark.parametrize("final_rows", [[], [3, 3], [(3, "extra")], [1], [4]])
def test_final_marker_reread_mismatch_rolls_back_complete_migration(final_rows):
    database = StatefulDatabase("pr200_v1", final_marker_rows=final_rows)
    before = database._state()
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        _initialize(database)
    assert database._state() == before


def _nth_match(fragment, occurrence=1):
    seen = 0
    def predicate(sql, _):
        nonlocal seen
        if fragment in sql:
            seen += 1
            return seen == occurrence
        return False
    return predicate


@pytest.mark.parametrize("failure", [
    _nth_match("SELECT v.timezone"),
    _nth_match("ALTER COLUMN phase1a_task_id"),
    _nth_match("UPDATE i SET phase1a_task_id"),
    _nth_match("ADD CONSTRAINT FK_run_schedule"),
    _nth_match("CREATE TABLE [sra_schedule].[requirement_schedule_audit_outbox]"),
    _nth_match("sys.columns", 3),
    _nth_match("UPDATE [sra_schedule].[schema_version]"),
    _nth_match("SELECT version", 2),
])
def test_migration_failure_boundaries_restore_data_catalog_and_marker(failure):
    database = StatefulDatabase("pr200_v1", external_id="z" * 200, fail_at=failure)
    before = database._state()
    with pytest.raises(RuntimeError):
        _initialize(database)
    assert database.rollbacks == 1 and database.commits == 0
    assert database._state() == before
    assert database.marker_rows == [1] and database.width == 256
    assert database.selected_identity == "req-1" and not database.outbox_exists


@pytest.mark.parametrize("drift_kind", ["missing_fk", "unique_pending_index"])
def test_catalog_postvalidation_rejects_structural_drift_and_rolls_back(drift_kind):
    def drift(catalog):
        if drift_kind == "missing_fk":
            catalog["foreign_keys"] = catalog["foreign_keys"][:-1]
        else:
            pending = catalog["indexes"][-1]
            catalog["indexes"] = catalog["indexes"][:-1] + (migrations.replace(pending, is_unique=True),)
    database = StatefulDatabase("pr201_v1", catalog_mutator=drift)
    before = database._state()
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        _initialize(database)
    assert database._state() == before


def test_initialize_invokes_bounded_startup_projector_without_owning_success():
    database = StatefulDatabase("v2")
    calls = []
    store = ScheduleStore(Registry(database), "db", audit_sink=lambda event: calls.append(event), audit_drain_limit=7)
    store.list_pending_audit_events = lambda limit: calls.append(("limit", limit)) or ()
    store.initialize()
    assert calls == [("limit", 7)] and database.commits == 1

    failing = StatefulDatabase("v2")
    store = ScheduleStore(Registry(failing), "db", audit_sink=lambda _: (_ for _ in ()).throw(OSError()))
    store.list_pending_audit_events = lambda limit: (_ for _ in ()).throw(OSError("sink unavailable"))
    store.initialize()
    assert failing.commits == 1


def test_audit_allowlist_matrix_rejects_every_extra_key():
    allowed = {
        "requirement_schedule.created": {"requirement_set_id": "r"},
        "requirement_schedule.updated": {"field": "name"},
        "requirement_schedule.version_created": {"version_number": 1},
        "requirement_schedule.version_approved": {"version_number": 1},
        "requirement_schedule.enabled": {},
        "requirement_schedule.disabled": {},
    }
    for action, payload in allowed.items():
        assert ScheduleStore._audit_event(action, "actor", "s", payload=payload).payload == payload
        for unsafe in ("password", "credential", "sql", "config", "runtime_state", "path"):
            with pytest.raises(ValueError, match="audit_payload_invalid"):
                ScheduleStore._audit_event(action, "actor", "s", payload={**payload, unsafe: "value"})


def test_phase1ca_source_has_no_orchestration_or_execution_boundary_coupling():
    import pathlib
    gate_a = {"migrations.py", "models.py", "policy.py", "recurrence.py", "service.py", "store.py", "audit_delivery.py"}
    sources = "\n".join(p.read_text().lower() for p in pathlib.Path("requirement_scheduler").glob("*.py") if p.name in gate_a)
    forbidden = ("langgraph", "smolagents", "workflow_registry", "orchestration adapter",
                 "reportjobworker", "elasticsearch", "backgroundtasks", "threading")
    assert not [term for term in forbidden if term in sources]
