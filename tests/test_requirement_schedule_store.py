from datetime import datetime, timezone
import json

from requirement_scheduler.store import ScheduleStore
from requirement_scheduler.recurrence import next_occurrence
from requirement_scheduler.models import MaterializedRun, RecurrenceSpec, RunPolicy, ScheduleVersionCreate, TriggerIdentity
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


def test_get_batch_run_projects_durable_handoff_and_artifact_identity(monkeypatch):
    store = ScheduleStore(Registry(), "control")
    queries = []

    def query(sql, *params):
        queries.append(sql)
        if "requirement_batch_run_items" in sql:
            return [{"run_item_id": "item-1", "remote_job_id": "job-1", "remote_job_state": "running"}]
        return [{
            "batch_run_id": "run-1",
            "snapshot_id": "snap-1",
            "phase1a_output_root_fingerprint": "a" * 64,
        }]

    monkeypatch.setattr(store, "_query", query)
    run = store.get_batch_run(schedule_id="schedule-1", batch_run_id="run-1")

    assert run["snapshot_id"] == "snap-1"
    assert run["phase1a_output_root_fingerprint"] == "a" * 64
    assert run["items"][0]["remote_job_id"] == "job-1"
    assert run["items"][0]["remote_job_state"] == "running"
    assert "snapshot_id" in queries[0]
    assert "phase1a_output_root_fingerprint" in queries[0]
    assert "remote_job_id" in queries[1]
    assert "remote_job_state" in queries[1]


def test_operator_artifact_evidence_is_bound_to_batch_and_run_item(monkeypatch):
    store = ScheduleStore(Registry(), "control")
    observed = {}

    def query(sql, *params):
        observed.update(sql=sql, params=params)
        return [{"batch_run_id": "batch-1", "run_item_id": "item-1"}]

    monkeypatch.setattr(store, "_query", query)
    result = store.get_operator_artifact_evidence(batch_run_id="batch-1", run_item_id="item-1")
    assert result == {"batch_run_id": "batch-1", "run_item_id": "item-1"}
    assert observed["params"] == ("batch-1", "item-1")
    assert "i.batch_run_id=r.batch_run_id" in observed["sql"]

    monkeypatch.setattr(store, "_query", lambda *_args: [])
    with pytest.raises(KeyError, match="run_item_not_found"):
        store.get_operator_artifact_evidence(batch_run_id="batch-1", run_item_id="other-item")


class VersionConnection:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []
        self.last = ""
        self.one = None
        self.commits = self.rollbacks = self.closed = 0

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.last = sql
        if "FROM [sra_schedule].[requirement_schedules]" in sql:
            self.one = (params[0],)
        elif "WHERE schedule_version_id=?" in sql:
            self.one = self.existing
        elif "MAX(version_number)" in sql:
            self.one = (3,)
        else:
            self.one = None
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def _version_config():
    recurrence = RecurrenceSpec.validate({"kind": "daily", "local_time": "09:00:00"})
    return ScheduleVersionCreate("UTC", recurrence, RunPolicy.ALL_ACTIVE, "model-a")


def test_create_version_uses_supplied_identity_when_absent():
    registry = Registry()
    registry.connection = VersionConnection()
    store = ScheduleStore(registry, "control")
    result = store.create_version(
        schedule_id="schedule-1",
        config=_version_config(),
        actor="operator",
        schedule_version_id="sv-fixed",
    )
    insert = next(
        params for sql, params in registry.connection.calls
        if "INSERT INTO [sra_schedule].[requirement_schedule_versions]" in sql
    )
    assert result["schedule_version_id"] == "sv-fixed"
    assert result["version_number"] == 3
    assert insert[0] == "sv-fixed"
    assert registry.connection.commits == 1


def test_create_version_same_identity_and_digest_replays_existing_row():
    config = _version_config()
    encoded, digest = ScheduleStore.canonical_config(config)
    created_at = datetime(2026, 10, 6, tzinfo=timezone.utc)
    existing = (
        "sv-fixed",
        "schedule-1",
        2,
        "UTC",
        encoded,
        config.run_policy.value,
        config.model,
        digest,
        "approved",
        "operator",
        created_at,
    )
    registry = Registry()
    registry.connection = VersionConnection(existing=existing)
    store = ScheduleStore(registry, "control")
    result = store.create_version(
        schedule_id="schedule-1",
        config=config,
        actor="retrying-operator",
        schedule_version_id="sv-fixed",
    )
    assert result["schedule_version_id"] == "sv-fixed"
    assert result["version_number"] == 2
    assert result["status"] == "approved"
    assert result["created_by"] == "operator"
    assert not any(
        "INSERT INTO [sra_schedule].[requirement_schedule_versions]" in sql
        for sql, _ in registry.connection.calls
    )
    assert registry.connection.commits == 1


def test_create_version_same_identity_with_different_semantics_fails_closed():
    config = _version_config()
    encoded, _ = ScheduleStore.canonical_config(config)
    existing = (
        "sv-fixed",
        "schedule-1",
        2,
        "UTC",
        encoded,
        config.run_policy.value,
        config.model,
        "0" * 64,
        "draft",
        "operator",
        datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    registry = Registry()
    registry.connection = VersionConnection(existing=existing)
    store = ScheduleStore(registry, "control")
    with pytest.raises(RuntimeError, match="^persistence_error$"):
        store.create_version(
            schedule_id="schedule-1",
            config=config,
            actor="operator",
            schedule_version_id="sv-fixed",
        )
    assert registry.connection.rollbacks == 1
    assert not any(
        "INSERT INTO [sra_schedule].[requirement_schedule_versions]" in sql
        for sql, _ in registry.connection.calls
    )



class ScheduleReplayConnection(Connection):
    def __init__(self, existing):
        super().__init__()
        self.existing = existing
        self.calls = []

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.sql, self.params = sql, params
        if "[sra_requirement].[requirement_sets]" in sql:
            self.one = (params[0],)
        elif "FROM [sra_schedule].[requirement_schedules] WITH (UPDLOCK,HOLDLOCK)" in sql:
            self.one = self.existing
        elif sql.startswith("INSERT INTO") and "requirement_schedules" in sql:
            self.rows.append(params)
            self.one = None
        else:
            self.one = None
        return self


def test_create_schedule_same_supplied_identity_and_semantics_replays_without_insert():
    created_at = datetime(2026, 10, 7, tzinfo=timezone.utc)
    existing = (
        "One Time",
        "set-1",
        False,
        "sv-existing",
        None,
        "admin",
        created_at,
        "admin",
        created_at,
    )
    registry = Registry()
    registry.connection = ScheduleReplayConnection(existing)
    store = ScheduleStore(registry, "control")

    result = store.create_schedule(
        name="One Time",
        requirement_set_id="set-1",
        actor="retry-admin",
        schedule_id="sch-fixed",
    )

    assert result["schedule_id"] == "sch-fixed"
    assert result["active_version_id"] == "sv-existing"
    assert result["enabled"] is False
    assert not any(
        sql.startswith("INSERT INTO") and "requirement_schedules" in sql
        for sql, _ in registry.connection.calls
    )
    assert registry.connection.commits == 1


def test_create_schedule_same_supplied_identity_with_different_semantics_fails_closed():
    existing = (
        "Other Name",
        "set-1",
        False,
        None,
        None,
        "admin",
        datetime(2026, 10, 7, tzinfo=timezone.utc),
        "admin",
        datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    registry = Registry()
    registry.connection = ScheduleReplayConnection(existing)
    store = ScheduleStore(registry, "control")

    with pytest.raises(RuntimeError, match="^persistence_error$"):
        store.create_schedule(
            name="One Time",
            requirement_set_id="set-1",
            actor="admin",
            schedule_id="sch-fixed",
        )

    assert registry.connection.rollbacks == 1
    assert not any(
        sql.startswith("INSERT INTO") and "requirement_schedules" in sql
        for sql, _ in registry.connection.calls
    )



class SelectionTimeCursor:
    def __init__(self, *, expires_at):
        self.expires_at = expires_at
        self.last_sql = ""
        self.calls = []

    def execute(self, sql, *params):
        self.last_sql = sql
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        sql = self.last_sql
        if "FROM [sra_schedule].[requirement_batch_runs]" in sql:
            return None
        if "SELECT active_snapshot_id" in sql:
            return ("snap-1",)
        if "requirement_schedule_item_state" in sql:
            return None
        return None

    def fetchall(self):
        if "FROM [sra_requirement].[requirement_snapshot_items]" in self.last_sql:
            return [
                (
                    "req-1",
                    "rv-1",
                    1,
                    1,
                    self.expires_at,
                    "external-1",
                )
            ]
        return []


def test_materialize_locked_uses_separate_selection_time_from_audit_time():
    store = ScheduleStore(Registry(), "control")
    selection_time = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
    retry_time = datetime(2026, 10, 7, 4, 10, tzinfo=timezone.utc)
    cursor = SelectionTimeCursor(
        expires_at=datetime(2026, 10, 7, 4, 5, tzinfo=timezone.utc)
    )

    result = store._materialize_locked(
        cursor,
        "sch-1",
        "sv-1",
        RunPolicy.ALL_ACTIVE.value,
        TriggerIdentity("manual", trigger_request_id="product-create:preq-1"),
        retry_time,
        "admin",
        selection_time=selection_time,
    )

    assert result.run["selected_count"] == 1
    item_insert = next(
        params
        for sql, params in cursor.calls
        if "INSERT INTO [sra_schedule].[requirement_batch_run_items]" in sql
    )
    assert item_insert[-3] == retry_time
    assert item_insert[-2] == selection_time
    assert item_insert[-1] == retry_time



class RecurringFinalizeConnection:
    def __init__(self, *, now_utc, first_run_selectable=True):
        config = _version_config()
        encoded, digest = ScheduleStore.canonical_config(config)
        self.now_utc = now_utc
        self.first_run_selectable = first_run_selectable
        self.config = config
        self.encoded = encoded
        self.digest = digest
        self.calls = []
        self.last_sql = ""
        self.one = None
        self.rowcount = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.last_sql = sql
        self.rowcount = 0
        if "FROM [sra_schedule].[requirement_product_requests]" in sql:
            self.one = (
                "preq-1", "user", "admin", "task_create", "idem-1", "a" * 64,
                "in_progress", "task-1", "src-1", "run-1", "snap-1", "sch-1",
                "sv-1", None, None, None, None, None, None,
                datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
                datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc),
                None,
            )
        elif "FROM [sra_schedule].[requirement_product_tasks]" in sql:
            self.one = (
                "task-1", "sch-1", "src-1", "recurring", "provisioning", 1
            )
        elif "FROM [sra_schedule].[requirement_schedules]" in sql:
            self.one = ("set-1", False, "sv-1", None)
        elif "FROM [sra_schedule].[requirement_schedule_versions]" in sql:
            self.one = (
                "approved",
                self.config.timezone,
                self.encoded,
                self.config.run_policy.value,
                self.config.model,
                self.digest,
            )
        elif "FROM [sra_requirement].[requirement_sets]" in sql:
            self.one = ("snap-1",)
        elif "FROM [sra_requirement].[requirement_snapshot_items]" in sql:
            self.one = (1,) if self.first_run_selectable else None
        elif sql.startswith("UPDATE [sra_schedule].[requirement_schedules]"):
            self.one = None
            self.rowcount = 1
        elif sql.startswith("UPDATE [sra_schedule].[requirement_product_tasks]"):
            self.one = None
            self.rowcount = 1
        elif sql.startswith("UPDATE [sra_schedule].[requirement_product_requests]"):
            self.one = None
            self.rowcount = 1
        else:
            self.one = None
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


class RecurringFinalizeRegistry:
    def __init__(self, connection):
        self.connection = connection

    def open_named_connection(self, _name):
        return self.connection


def test_recurring_product_finalizer_atomically_enables_without_initial_run(monkeypatch):
    now = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
    connection = RecurringFinalizeConnection(now_utc=now)
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")
    audit = []
    monkeypatch.setattr(
        store,
        "_enqueue_audit_event",
        lambda _cursor, event: audit.append(event),
    )
    monkeypatch.setattr(store, "_drain_best_effort", lambda: None)

    result = store.finalize_recurring_product_task_create(
        request_id="preq-1",
        task_id="task-1",
        actor="admin",
        now_utc=now,
    )

    expected_due = next_occurrence(
        connection.config.recurrence,
        connection.config.timezone,
        now,
    )
    assert result["next_run_at"] == expected_due.isoformat()
    assert result["task_revision"] == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(audit) == 1
    assert audit[0].action == "requirement_schedule.enabled"
    assert audit[0].payload == {}
    schedule_update = next(
        params
        for sql, params in connection.calls
        if sql.startswith("UPDATE [sra_schedule].[requirement_schedules]")
    )
    assert schedule_update[0] == expected_due
    assert not any(
        "INSERT INTO [sra_schedule].[requirement_batch_runs]" in sql
        or "INSERT INTO [sra_schedule].[requirement_batch_run_items]" in sql
        for sql, _ in connection.calls
    )
    request_update = next(
        params
        for sql, params in connection.calls
        if sql.startswith("UPDATE [sra_schedule].[requirement_product_requests]")
    )
    safe_result = json.loads(request_update[0])
    assert safe_result["next_run_at"] == expected_due.isoformat()
    assert "batch_run_id" not in safe_result



def test_recurring_product_finalizer_terminalizes_when_first_due_has_no_selectable_rows(monkeypatch):
    now = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
    connection = RecurringFinalizeConnection(
        now_utc=now,
        first_run_selectable=False,
    )
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")
    monkeypatch.setattr(store, "_drain_best_effort", lambda: None)

    with pytest.raises(
        ValueError,
        match="requirement_product_no_selectable_first_run",
    ):
        store.finalize_recurring_product_task_create(
            request_id="preq-1",
            task_id="task-1",
            actor="admin",
            now_utc=now,
        )

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert not any(
        sql.startswith("UPDATE [sra_schedule].[requirement_schedules]")
        for sql, _ in connection.calls
    )
    assert not any(
        sql.startswith("UPDATE [sra_schedule].[requirement_product_tasks]")
        for sql, _ in connection.calls
    )
    terminal_update = next(
        (sql, params)
        for sql, params in connection.calls
        if sql.startswith("UPDATE [sra_schedule].[requirement_product_requests]")
    )
    assert "state='failed_terminal'" in terminal_update[0]
    assert "requirement_product_no_selectable_first_run" in terminal_update[0]



class ClaimDueSelectionConnection:
    def __init__(self, *, persisted_due, recurrence_json):
        self.persisted_due = persisted_due
        self.recurrence_json = recurrence_json
        self.calls = []
        self.last_sql = ""
        self.one = None
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.last_sql = sql
        if "SELECT TOP 1 s.schedule_id" in sql:
            self.one = (
                "sch-1",
                "sv-1",
                self.persisted_due,
                "UTC",
                self.recurrence_json,
                RunPolicy.ALL_ACTIVE.value,
            )
        else:
            self.one = None
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_claim_due_evaluates_scheduled_run_at_occurrence_time(monkeypatch):
    config = _version_config()
    recurrence_json, _ = ScheduleStore.canonical_config(config)
    persisted_due = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    claim_time = datetime(2026, 10, 7, 9, 5, tzinfo=timezone.utc)
    connection = ClaimDueSelectionConnection(
        persisted_due=persisted_due,
        recurrence_json=recurrence_json,
    )
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")
    observed = {}

    def fake_materialize(
        cursor,
        schedule_id,
        version_id,
        policy,
        trigger,
        now_utc,
        actor,
        *,
        selection_time=None,
    ):
        observed.update(
            {
                "trigger": trigger,
                "now_utc": now_utc,
                "selection_time": selection_time,
            }
        )
        return MaterializedRun(
            {"batch_run_id": "br-1", "schedule_id": schedule_id},
            (),
        )

    monkeypatch.setattr(store, "_materialize_locked", fake_materialize)

    result = store.claim_due(now_utc=claim_time, actor="scheduler")

    assert result["scheduled_for"] == persisted_due
    assert observed["trigger"].scheduled_for == persisted_due
    assert observed["selection_time"] == persisted_due
    assert observed["now_utc"] == claim_time
    assert connection.commits == 1



def test_materialize_locked_terminalizes_zero_selection_run_in_same_transaction():
    store = ScheduleStore(Registry(), "control")
    selection_time = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    materialized_at = datetime(2026, 10, 7, 9, 10, tzinfo=timezone.utc)
    cursor = SelectionTimeCursor(
        expires_at=datetime(2026, 10, 7, 8, 59, tzinfo=timezone.utc)
    )

    result = store._materialize_locked(
        cursor,
        "sch-1",
        "sv-1",
        RunPolicy.ALL_ACTIVE.value,
        TriggerIdentity("scheduled", scheduled_for=selection_time),
        materialized_at,
        "scheduler",
        selection_time=selection_time,
    )

    assert result.run["selected_count"] == 0
    assert result.run["state"] == "completed"
    terminal_update = next(
        params
        for sql, params in cursor.calls
        if "UPDATE [sra_schedule].[requirement_batch_runs] SET success_count=?" in sql
    )
    assert terminal_update[0] == 0
    assert terminal_update[1] == 0
    assert terminal_update[2] == "completed"
    assert terminal_update[3] == 0
    assert terminal_update[4] == materialized_at
    assert terminal_update[5] == materialized_at



def _task_update_request_row(
    *,
    state="in_progress",
    base_revision=7,
    result_revision=None,
    schedule_version_id=None,
    safe_result_json=None,
    error_code=None,
):
    now = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)
    return (
        "preq-update-1",
        "user",
        "admin",
        "task_update",
        "idem-update",
        "a" * 64,
        state,
        "task-1",
        "src-1",
        None,
        None,
        "sch-1",
        schedule_version_id,
        None,
        base_revision,
        result_revision,
        None,
        safe_result_json,
        error_code,
        now,
        now,
        now if state in {"succeeded", "failed_terminal"} else None,
    )


class TaskUpdateReservationConnection:
    def __init__(self, *, task_state="active", revision=7):
        self.task_state = task_state
        self.revision = revision
        self.calls = []
        self.one = None
        self.rowcount = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.rowcount = 0
        if (
            "FROM [sra_schedule].[requirement_product_requests]" in sql
            and "operation='task_update'" in sql
        ):
            self.one = None
        elif "FROM [sra_schedule].[requirement_product_tasks]" in sql:
            self.one = (
                "task-1",
                "sch-1",
                "src-1",
                "recurring",
                self.task_state,
                self.revision,
            )
        elif sql.startswith(
            "INSERT INTO [sra_schedule].[requirement_product_requests]"
        ):
            self.one = None
            self.rowcount = 1
        else:
            self.one = None
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_reserve_product_task_update_persists_base_revision_and_draft_identity():
    connection = TaskUpdateReservationConnection(revision=7)
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")
    now = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)

    result = store.reserve_product_task_update(
        task_id="task-1",
        principal_kind="user",
        principal_id="admin",
        idempotency_key="idem-update",
        request_sha256="a" * 64,
        allocate_schedule_version=True,
        now_utc=now,
    )

    assert result["base_task_revision"] == 7
    assert result["schedule_id"] == "sch-1"
    assert result["source_id"] == "src-1"
    assert result["schedule_version_id"].startswith("sv_")
    insert = next(
        params
        for sql, params in connection.calls
        if sql.startswith(
            "INSERT INTO [sra_schedule].[requirement_product_requests]"
        )
    )
    assert insert[6] == "task-1"
    assert insert[7] == "src-1"
    assert insert[8] == "sch-1"
    assert insert[9] == result["schedule_version_id"]
    assert insert[10] == 7
    assert connection.commits == 1


def test_reserve_product_task_update_rejects_provisioning_before_ledger_insert():
    connection = TaskUpdateReservationConnection(task_state="provisioning")
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")

    with pytest.raises(ValueError, match="requirement_task_provisioning"):
        store.reserve_product_task_update(
            task_id="task-1",
            principal_kind="user",
            principal_id="admin",
            idempotency_key="idem-update",
            request_sha256="a" * 64,
            allocate_schedule_version=False,
            now_utc=datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc),
        )

    assert connection.rollbacks == 1
    assert not any(
        sql.startswith(
            "INSERT INTO [sra_schedule].[requirement_product_requests]"
        )
        for sql, _ in connection.calls
    )


class TaskUpdateFinalizeConnection:
    def __init__(self, *, task_revision=7, proposal=False):
        self.task_revision = task_revision
        self.proposal = proposal
        self.calls = []
        self.one = None
        self.rowcount = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0
        self.due = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.rowcount = 0
        if (
            "FROM [sra_schedule].[requirement_product_requests]" in sql
            and "WHERE request_id=?" in sql
        ):
            self.one = _task_update_request_row(
                schedule_version_id="sv-draft-1" if self.proposal else None
            )
        elif (
            "SELECT task_id,schedule_id,source_id,execution_kind,product_state,revision"
            in sql
        ):
            self.one = (
                "task-1",
                "sch-1",
                "src-1",
                "recurring",
                "active",
                self.task_revision,
            )
        elif "SELECT schedule_id,product_state,revision" in sql:
            self.one = ("sch-1", "active", self.task_revision)
        elif "SELECT name,enabled,active_version_id,next_run_at" in sql:
            self.one = ("Original", True, "sv-active", self.due)
        elif (
            "SELECT schedule_version_id,schedule_id,version_number,config_sha256,status"
            in sql
        ):
            self.one = (
                "sv-draft-1",
                "sch-1",
                4,
                "d" * 64,
                "draft",
            )
        elif sql.startswith("UPDATE [sra_schedule].[requirement_schedules]"):
            self.one = None
            self.rowcount = 1
        elif sql.startswith("UPDATE [sra_schedule].[requirement_product_tasks]"):
            self.one = None
            self.rowcount = 1
        elif sql.startswith("UPDATE [sra_schedule].[requirement_product_requests]"):
            self.one = None
            self.rowcount = 1
        else:
            self.one = None
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def test_finalize_product_task_update_atomically_mirrors_disable_and_increments_once(monkeypatch):
    connection = TaskUpdateFinalizeConnection()
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")
    audit = []
    monkeypatch.setattr(
        store,
        "_enqueue_audit_event",
        lambda _cursor, event: audit.append(event),
    )
    monkeypatch.setattr(store, "_drain_best_effort", lambda: None)
    now = datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)

    result = store.finalize_product_task_update(
        request_id="preq-update-1",
        task_id="task-1",
        actor="admin",
        name="Renamed",
        enabled=False,
        is_superuser=True,
        now_utc=now,
    )

    assert result["task_revision"] == 8
    assert result["name"] == "Renamed"
    assert result["product_state"] == "disabled"
    assert result["enabled"] is False
    assert result["next_run_at"] is None
    task_update = next(
        params
        for sql, params in connection.calls
        if sql.startswith(
            "UPDATE [sra_schedule].[requirement_product_tasks]"
        )
    )
    assert task_update[:2] == ("disabled", 8)
    request_update = next(
        params
        for sql, params in connection.calls
        if sql.startswith(
            "UPDATE [sra_schedule].[requirement_product_requests]"
        )
        and "SET state='succeeded'" in sql
    )
    assert request_update[0] == 8
    safe_result = json.loads(request_update[1])
    assert safe_result["task_revision"] == 8
    assert [event.action for event in audit] == [
        "requirement_schedule.updated",
        "requirement_schedule.disabled",
    ]
    assert connection.commits == 1


def test_finalize_product_task_update_stale_revision_terminalizes_without_mutation(monkeypatch):
    connection = TaskUpdateFinalizeConnection(task_revision=8)
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")
    monkeypatch.setattr(store, "_drain_best_effort", lambda: None)

    with pytest.raises(ValueError, match="requirement_task_conflict"):
        store.finalize_product_task_update(
            request_id="preq-update-1",
            task_id="task-1",
            actor="admin",
            name="Stale",
            enabled=None,
            is_superuser=True,
            now_utc=datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc),
        )

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert not any(
        sql.startswith("UPDATE [sra_schedule].[requirement_schedules]")
        or sql.startswith("UPDATE [sra_schedule].[requirement_product_tasks]")
        for sql, _ in connection.calls
    )
    terminal = next(
        params
        for sql, params in connection.calls
        if sql.startswith(
            "UPDATE [sra_schedule].[requirement_product_requests]"
        )
        and "failed_terminal" in sql
    )
    assert terminal[0] == "requirement_task_conflict"


def test_complete_product_task_update_proposal_keeps_revision_and_result_revision_null():
    connection = TaskUpdateFinalizeConnection(proposal=True)
    store = ScheduleStore(RecurringFinalizeRegistry(connection), "control")

    result = store.complete_product_task_update_proposal(
        request_id="preq-update-1",
        task_id="task-1",
        actor="operator",
        now_utc=datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc),
    )

    assert result == {
        "mode": "schedule_proposal",
        "task_id": "task-1",
        "base_task_revision": 7,
        "schedule_id": "sch-1",
        "schedule_version_id": "sv-draft-1",
        "version_number": 4,
        "config_sha256": "d" * 64,
        "status": "draft",
    }
    assert not any(
        sql.startswith("UPDATE [sra_schedule].[requirement_product_tasks]")
        for sql, _ in connection.calls
    )
    proposal_update = next(
        (sql, params)
        for sql, params in connection.calls
        if sql.startswith(
            "UPDATE [sra_schedule].[requirement_product_requests]"
        )
        and "SET state='succeeded'" in sql
    )
    assert "result_task_revision=NULL" in proposal_update[0]
    assert connection.commits == 1
