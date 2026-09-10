from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
from pathlib import Path
import signal

import pytest

from requirement_scheduler.schedule_worker import (
    SCHEDULE_WORKER_ACTOR,
    RequirementScheduleWorker,
    parse_poll_interval,
)
from requirement_scheduler import cli
from requirement_scheduler.store import ScheduleStore


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, results=()):
        self.results = list(results)
        self.claims = []

    def claim_due(self, *, now_utc, actor):
        self.claims.append((now_utc, actor))
        result = self.results.pop(0) if self.results else None
        if isinstance(result, BaseException):
            raise result
        return result


class FakeStopEvent:
    def __init__(self, *, stop_after_checks=None):
        self.check_count = 0
        self.stop_after_checks = stop_after_checks
        self.waits = []
        self.was_set = False

    def is_set(self):
        self.check_count += 1
        if self.stop_after_checks is not None and self.check_count >= self.stop_after_checks:
            self.was_set = True
        return self.was_set

    def wait(self, seconds):
        self.waits.append(seconds)
        self.was_set = True
        return True

    def set(self):
        self.was_set = True


def test_poll_interval_defaults_to_2_seconds(monkeypatch):
    monkeypatch.delenv("REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL", raising=False)
    assert parse_poll_interval() == 2.0


def test_poll_interval_accepts_inclusive_bounds(monkeypatch):
    for value in ("0.1", "300.0"):
        monkeypatch.setenv("REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL", value)
        assert parse_poll_interval() == float(value)


@pytest.mark.parametrize(
    "value", ["0", "-1", "0.099", "300.001", "invalid", "NaN", "inf", "-inf"]
)
def test_poll_interval_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL", value)
    with pytest.raises(ValueError, match="schedule_worker_config_invalid"):
        parse_poll_interval()


def test_run_once_no_due_claims_exactly_once():
    store = FakeStore([None])
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    assert worker.run_once() is None
    assert store.claims == [(NOW, SCHEDULE_WORKER_ACTOR)]


def test_run_once_claimed_returns_existing_result_exactly_once():
    claimed = {"batch_run_id": "br-1"}
    store = FakeStore([claimed, {"batch_run_id": "br-2"}])
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    assert worker.run_once() is claimed
    assert store.claims == [(NOW, SCHEDULE_WORKER_ACTOR)]


def test_run_once_persistence_error_is_fatal_without_wait():
    store = FakeStore([RuntimeError("persistence_error")])
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="persistence_error"):
        worker.run_once()
    assert len(store.claims) == 1


def test_run_once_rejects_naive_clock_before_claim():
    store = FakeStore()
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW.replace(tzinfo=None))
    with pytest.raises(RuntimeError, match="invalid_utc_clock"):
        worker.run_once()
    assert store.claims == []


def test_run_once_uses_aware_utc_and_stable_actor():
    offset_time = NOW.astimezone(timezone(timedelta(hours=8)))
    store = FakeStore()
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: offset_time)
    with pytest.raises(RuntimeError, match="invalid_utc_clock"):
        worker.run_once()
    assert store.claims == []

    utc_store = FakeStore()
    RequirementScheduleWorker(utc_store, 2.0, clock=lambda: NOW).run_once()
    assert utc_store.claims == [(NOW, "requirement-schedule-worker")]


def test_run_once_truncates_runtime_clock_to_utc_second_precision():
    runtime_now = datetime(2026, 9, 10, 2, 52, 2, 671876, tzinfo=timezone.utc)
    store = FakeStore()

    RequirementScheduleWorker(store, 2.0, clock=lambda: runtime_now).run_once()

    claimed_now, actor = store.claims[0]
    assert claimed_now == datetime(2026, 9, 10, 2, 52, 2, tzinfo=timezone.utc)
    assert claimed_now.tzinfo is timezone.utc
    assert claimed_now.microsecond == 0
    assert claimed_now.second == runtime_now.second
    assert actor == "requirement-schedule-worker"


def test_run_no_due_claims_once_then_waits_interruptibly():
    store = FakeStore([None])
    stop = FakeStopEvent()
    RequirementScheduleWorker(store, 2.0, clock=lambda: NOW).run(stop)
    assert len(store.claims) == 1
    assert stop.waits == [2.0]


def test_run_one_due_then_no_due_reaches_next_bounded_iteration():
    store = FakeStore([{"batch_run_id": "br-1"}, None])
    stop = FakeStopEvent()
    RequirementScheduleWorker(store, 2.0, clock=lambda: NOW).run(stop)
    assert len(store.claims) == 2
    assert stop.waits == [2.0]


def test_run_multiple_due_claims_one_per_iteration_until_stopped():
    store = FakeStore([{"batch_run_id": "br-1"}, {"batch_run_id": "br-2"}])
    stop = FakeStopEvent(stop_after_checks=3)
    RequirementScheduleWorker(store, 2.0, clock=lambda: NOW).run(stop)
    assert len(store.claims) == 2
    assert stop.check_count == 3
    assert stop.waits == []


def test_run_persistence_error_emits_safe_category_waits_then_retries_later(capsys):
    store = FakeStore([RuntimeError("persistence_error: raw database detail"), None])
    stop = FakeStopEvent()

    def wait(seconds):
        stop.waits.append(seconds)
        if len(stop.waits) == 2:
            stop.was_set = True

    stop.wait = wait
    RequirementScheduleWorker(store, 2.0, clock=lambda: NOW).run(stop)
    assert len(store.claims) == 2
    assert stop.waits == [2.0, 2.0]
    captured = capsys.readouterr()
    assert captured.err.strip() == "persistence_error"
    assert "raw database detail" not in captured.err


def test_run_unexpected_invariant_error_is_fatal():
    store = FakeStore([RuntimeError("invariant_broken")])
    with pytest.raises(RuntimeError, match="invariant_broken"):
        RequirementScheduleWorker(store, 2.0, clock=lambda: NOW).run(FakeStopEvent())


def test_sigterm_sets_schedule_worker_stop_event(monkeypatch):
    from requirement_scheduler.schedule_worker import run_schedule_worker

    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler))

    class Worker:
        def run(self, stop):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            assert stop.is_set()

    assert run_schedule_worker(Worker()) is None


def test_keyboard_interrupt_sets_schedule_worker_stop_event(monkeypatch):
    from requirement_scheduler.schedule_worker import run_schedule_worker

    observed = {}

    class Worker:
        def run(self, stop):
            observed["stop"] = stop
            raise KeyboardInterrupt

    assert run_schedule_worker(Worker()) is None
    assert observed["stop"].is_set()


def test_cli_accepts_schedule_worker():
    args = cli.build_parser().parse_args(["schedule-worker"])
    assert args.command == "schedule-worker"
    assert args.once is False


def test_cli_accepts_schedule_worker_once():
    args = cli.build_parser().parse_args(["schedule-worker", "--once"])
    assert args.command == "schedule-worker"
    assert args.once is True


def test_cli_keeps_handoff_worker():
    args = cli.build_parser().parse_args(["handoff-worker"])
    assert args.command == "handoff-worker"


def test_cli_rejects_generic_worker():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["worker"])


@pytest.mark.parametrize("result", [None, {"batch_run_id": "br-1"}])
def test_cli_once_no_due_exits_zero_after_one_claim(result):
    store = FakeStore([result, {"batch_run_id": "br-2"}])
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    assert cli.main(["schedule-worker", "--once"], schedule_worker_factory=lambda: worker) == 0
    assert len(store.claims) == 1


def test_cli_once_claimed_exits_zero_after_one_claim():
    store = FakeStore([{"batch_run_id": "br-1"}, {"batch_run_id": "br-2"}])
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    assert cli.main(["schedule-worker", "--once"], schedule_worker_factory=lambda: worker) == 0
    assert len(store.claims) == 1


def test_cli_once_persistence_error_exits_nonzero_without_wait(capsys):
    store = FakeStore([RuntimeError("persistence_error: private SQL detail")])
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    assert cli.main(["schedule-worker", "--once"], schedule_worker_factory=lambda: worker) != 0
    assert len(store.claims) == 1
    assert capsys.readouterr().err.strip() == "persistence_error"


def test_cli_startup_failure_exits_nonzero_with_zero_claims(capsys):
    def fail_startup():
        raise RuntimeError("persistence_error: private registry detail")

    assert cli.main(["schedule-worker", "--once"], schedule_worker_factory=fail_startup) != 0
    assert capsys.readouterr().err.strip() == "persistence_error"


@pytest.mark.parametrize(
    "value", ["0", "-1", "0.099", "300.001", "invalid", "NaN", "inf", "-inf"]
)
def test_invalid_schedule_config_prevents_store_construction_and_claim(monkeypatch, value, capsys):
    monkeypatch.setenv("REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL", value)
    constructed = []
    monkeypatch.setattr(cli, "SqlRegistry", type("Registry", (), {"load": lambda *_: constructed.append(True)}))
    assert cli.main(["schedule-worker", "--once"]) != 0
    assert constructed == []
    assert capsys.readouterr().err.strip() == "schedule_worker_config_invalid"


def test_cli_and_environment_cannot_override_schedule_actor(monkeypatch):
    monkeypatch.setenv("REQUIREMENT_SCHEDULE_WORKER_ACTOR", "attacker")
    help_text = cli.build_parser().format_help()
    assert "actor" not in help_text.lower()
    store = FakeStore()
    worker = RequirementScheduleWorker(store, 2.0, clock=lambda: NOW)
    assert cli.main(["schedule-worker", "--once"], schedule_worker_factory=lambda: worker) == 0
    assert store.claims[0][1] == "requirement-schedule-worker"


class ExistingStoreConnection:
    def __init__(self, due_row):
        self.due_row = due_row
        self.current = None
        self.sql = []
        self.commits = 0

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.sql.append((sql, params))
        if "SELECT TOP 1 s.schedule_id" in sql:
            self.current = self.due_row
        elif "SELECT batch_run_id" in sql:
            self.current = None
        elif "SELECT active_snapshot_id" in sql:
            self.current = None
        return self

    def fetchone(self):
        return self.current

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


class ExistingStoreRegistry:
    def __init__(self, connections):
        self.connections = list(connections)

    def open_named_connection(self, _name):
        return self.connections.pop(0)


def _due_row(schedule_id, due=NOW):
    recurrence = '{"recurrence":{"kind":"daily","local_time":"12:00:00"}}'
    return (schedule_id, f"sv-{schedule_id}", due, "UTC", recurrence, "all_active")


def test_existing_store_materializes_one_scheduled_occurrence_per_claim():
    connection = ExistingStoreConnection(_due_row("schedule-1"))
    worker = RequirementScheduleWorker(
        ScheduleStore(ExistingStoreRegistry([connection]), "db"), 2.0, clock=lambda: NOW
    )
    result = worker.run_once()
    assert result["schedule_id"] == "schedule-1"
    assert sum("INSERT INTO [sra_schedule].[requirement_batch_runs]" in sql for sql, _ in connection.sql) == 1
    assert sum("SELECT TOP 1 s.schedule_id" in sql for sql, _ in connection.sql) == 1


def test_existing_store_eventually_processes_multiple_due_occurrences():
    first = ExistingStoreConnection(_due_row("schedule-1"))
    second = ExistingStoreConnection(_due_row("schedule-2"))
    empty = ExistingStoreConnection(None)
    store = ScheduleStore(ExistingStoreRegistry([first, second, empty]), "db")
    stop = FakeStopEvent()
    RequirementScheduleWorker(store, 2.0, clock=lambda: NOW).run(stop)
    assert all("SELECT TOP 1 s.schedule_id" in connection.sql[0][0]
               for connection in (first, second, empty))
    assert stop.waits == [2.0]


def test_existing_store_owns_advancement_disabled_filtering_and_occurrence_uniqueness():
    connection = ExistingStoreConnection(_due_row("schedule-1"))
    result = ScheduleStore(ExistingStoreRegistry([connection]), "db").claim_due(
        now_utc=NOW, actor=SCHEDULE_WORKER_ACTOR
    )
    select_sql = connection.sql[0][0]
    update_sql = next(sql for sql, _ in connection.sql if "UPDATE [sra_schedule].[requirement_schedules]" in sql)
    assert "s.enabled=1" in select_sql
    assert "ORDER BY s.next_run_at,s.schedule_id" in select_sql
    assert result["next_run_at"] == NOW + timedelta(days=1)
    assert "SET next_run_at=?" in update_sql
    identity_sql = next(sql for sql, _ in connection.sql if "SELECT batch_run_id" in sql)
    assert "scheduled_for=?" in identity_sql
    assert "trigger_type=?" in identity_sql


def test_schedule_worker_import_graph_excludes_execution_dependencies():
    source = Path("requirement_scheduler/schedule_worker.py").read_text()
    tree = ast.parse(source)
    imports = set()
    referenced_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
            referenced_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            referenced_names.add(node.id)
    prohibited_modules = {
        "requests", "httpx", "urllib", "batch_scheduler.store",
        "agent", "elasticsearch", "requirement_scheduler.handoff",
        "requirement_scheduler.coordinator", "requirement_scheduler.legacy_report_job_gateway",
    }
    prohibited_symbols = {
        "BatchSchedulerService", "ReportJobStore", "ReportJobWorker",
        "LegacyReportJobGateway", "RequirementHandoffCoordinator", "ExportWordService",
    }
    assert not any(
        imported == prohibited or imported.startswith(f"{prohibited}.")
        for imported in imports for prohibited in prohibited_modules
    )
    assert referenced_names.isdisjoint(prohibited_symbols)
