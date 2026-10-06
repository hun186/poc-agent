from requirement_scheduler import store as store_module
from requirement_scheduler.migrations import SCHEMA_VERSION, migration_3_to_4_statements
from requirement_scheduler.store import ScheduleStore


class _Cursor:
    def __init__(self, version: int):
        self.version = version
        self.rows = ()
        self.executed = []
        self.rowcount = 1

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        if "SELECT OBJECT_ID" in sql:
            self.rows = ((1,),)
        elif "SELECT version FROM [sra_schedule].[schema_version]" in sql:
            self.rows = ((self.version,),)
        elif sql.startswith("UPDATE [sra_schedule].[schema_version] SET version=?"):
            assert params == (SCHEMA_VERSION, 3)
            self.version = SCHEMA_VERSION
            self.rows = ()
        else:
            self.rows = ()
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, version: int):
        self.cursor_obj = _Cursor(version)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class _Registry:
    def __init__(self, connection):
        self.connection = connection

    def open_named_connection(self, connection_ref):
        assert connection_ref == "control"
        return self.connection


def test_existing_v3_schedule_schema_migrates_transactionally_to_v4(monkeypatch):
    connection = _Connection(version=3)
    store = ScheduleStore(_Registry(connection), "control")

    monkeypatch.setattr(store_module, "validation_queries", lambda *_args: ())
    monkeypatch.setattr(store_module, "read_catalog", lambda *_args: {})
    monkeypatch.setattr(store_module, "canonical_catalog_matches", lambda *_args: True)

    store.initialize()

    sql = "\n".join(statement for statement, _params in connection.cursor_obj.executed)
    for statement in migration_3_to_4_statements("sra_schedule", "sra_requirement"):
        assert statement in sql
    assert connection.cursor_obj.version == SCHEMA_VERSION == 4
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed


def test_v3_to_v4_catalog_failure_rolls_back_without_advancing_marker(monkeypatch):
    connection = _Connection(version=3)
    store = ScheduleStore(_Registry(connection), "control")

    monkeypatch.setattr(store_module, "validation_queries", lambda *_args: ())
    monkeypatch.setattr(store_module, "read_catalog", lambda *_args: {})
    monkeypatch.setattr(store_module, "canonical_catalog_matches", lambda *_args: False)

    import pytest
    with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
        store.initialize()

    sql = "\n".join(statement for statement, _params in connection.cursor_obj.executed)
    assert "requirement_product_tasks" in sql
    assert "requirement_product_requests" in sql
    assert connection.cursor_obj.version == 3
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_v4_migration_contains_no_foreign_keys_for_request_reservation_refs():
    ddl = "\n".join(migration_3_to_4_statements("sra_schedule", "sra_requirement"))
    request_ddl = ddl.split("CREATE TABLE [sra_schedule].[requirement_product_requests]", 1)[1]
    assert "task_id NVARCHAR(64) NULL" in request_ddl
    assert "source_id NVARCHAR(64) NULL" in request_ddl
    assert "schedule_id NVARCHAR(64) NULL" in request_ddl
    assert "snapshot_id NVARCHAR(64) NULL" in request_ddl
    assert "FOREIGN KEY(task_id)" not in request_ddl
    assert "FOREIGN KEY(source_id)" not in request_ddl
    assert "FOREIGN KEY(schedule_id)" not in request_ddl
    assert "FOREIGN KEY(snapshot_id)" not in request_ddl
