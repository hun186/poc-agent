"""Hosted regression: all foreign model/ES calls use controlled fake clients."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent import e2e_preflight_budget as budget
from agent.external_capabilities import (
    BackendPlan, CapabilityError, _operator_es_call, frozen_plan,
    prepare_requirement_elasticsearch, reset_plan_for_tests,
)
from sra_api.routers import operator_e2e
from sra_api.services.operator_preflight_state import (
    OperatorPreflightTracker, PreflightInProgress,
)


@pytest.fixture(autouse=True)
def isolate_plan():
    reset_plan_for_tests()
    yield
    reset_plan_for_tests()


def test_budget_is_opt_in_and_nested_budget_cannot_expand(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    assert not budget.budget_active()
    assert budget.budget_timeout(10) == 10
    with budget.preflight_budget(10):
        assert budget.budget_active()
        assert budget.budget_timeout(30) == 10
        clock[0] += 2
        with budget.preflight_budget(50):
            assert budget.budget_timeout(30) == 8
        clock[0] += 8
        with pytest.raises(budget.PreflightDeadlineExceeded, match="external_e2e_preflight_deadline_exceeded"):
            budget.check_budget()
    assert not budget.budget_active()
    assert budget.budget_timeout(10) == 10


def test_late_resolver_cannot_publish_immutable_plan(monkeypatch):
    clock = [200.0]
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    with budget.preflight_budget(5):
        def late(_mode):
            clock[0] += 6
            return BackendPlan("live", "live", "live", "pass", "pass")
        with pytest.raises(budget.PreflightDeadlineExceeded):
            frozen_plan(late)
    with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
        frozen_plan()


def test_inflight_e2e_job_fails_closed_without_waiting_for_plan_lock(monkeypatch):
    from agent import external_capabilities as ext
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    locked = threading.Event()
    release = threading.Event()
    result = []
    def resolving(_mode):
        locked.set()
        assert release.wait(3)
        return BackendPlan("live", "live", "live", "pass", "pass")
    thread = threading.Thread(target=lambda: frozen_plan(resolving))
    thread.start()
    try:
        assert locked.wait(3)
        started = time.monotonic()
        with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
            ext.frozen_plan()
        assert time.monotonic() - started < 1
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()


def test_es_uses_remaining_budget_without_retries(monkeypatch):
    clock = [300.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    class Client:
        observed = []
        def options(self, **kwargs):
            self.observed.append(kwargs)
            return self
    client = Client()
    with budget.preflight_budget(8):
        clock[0] += 3
        assert _operator_es_call(client, lambda es: 42) == 42
    assert len(client.observed) == 1
    assert client.observed[0]["request_timeout"] == 5
    assert client.observed[0]["max_retries"] == 0
    assert client.observed[0]["retry_on_timeout"] is False


def test_es_without_bounded_options_fails_closed():
    with budget.preflight_budget(5):
        with pytest.raises(CapabilityError, match="external_e2e_es_deadline_unavailable"):
            _operator_es_call(object(), lambda es: pytest.fail("must never reach backend"))


def test_expiry_during_es_create_stops_before_fixture_indexing(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    actions = []
    class Indices:
        def exists(self, **_kw):
            return False
        def create(self, **_kw):
            actions.append("create")
            clock[0] += 20
        def get_mapping(self, **_kw):
            pytest.fail("mapping should not be queried after late create")
    class Client:
        indices = Indices()
        def options(self, **_kw):
            return self
        def ping(self):
            return True
        def index(self, **_kw):
            pytest.fail("late index mutation")
    with budget.preflight_budget(10):
        with pytest.raises(budget.PreflightDeadlineExceeded):
            prepare_requirement_elasticsearch(Client(), "requirement_e2e_test", [])
    assert actions == ["create"]


def test_blocked_sdk_stays_running_overdue_until_real_exit():
    tracker = OperatorPreflightTracker(budget_seconds=0.01)
    entered, released = threading.Event(), threading.Event()
    failures = []
    def blocked():
        entered.set()
        assert released.wait(3)
        return {"value": "late"}
    def run():
        try:
            tracker.run(blocked)
        except BaseException as exc:
            failures.append(exc)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(3)
        time.sleep(0.04)
        assert tracker.snapshot()["state"] == "RUNNING_OVERDUE"
        with pytest.raises(PreflightInProgress):
            tracker.run(lambda: "duplicate")
    finally:
        released.set()
        worker.join(3)
    assert not worker.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], budget.PreflightDeadlineExceeded)
    assert tracker.snapshot()["state"] == "TIMEOUT"


def test_operator_http_returns_redacted_deadline_failure(monkeypatch):
    tracker = OperatorPreflightTracker(budget_seconds=0.01)
    monkeypatch.setattr(operator_e2e, "_preflight_tracker", tracker)
    def slow(*_args):
        time.sleep(0.03)
        return {"SECRET": "private.example/token"}
    monkeypatch.setattr(operator_e2e, "configured_runtime_evidence", slow)
    with pytest.raises(HTTPException) as failure:
        operator_e2e.runtime_evidence("release", object())
    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": "external_e2e_preflight_deadline_exceeded"}
    assert "SECRET" not in json.dumps(tracker.snapshot())
    assert tracker.snapshot()["state"] == "TIMEOUT"


def test_source_validation_failure_does_not_begin_plan_resolution(monkeypatch, tmp_path):
    from sra_api.services import requirement_e2e_runtime_evidence as module
    called = []
    def reject(*_args, **_kwargs):
        raise RuntimeError("release_provenance_missing")
    monkeypatch.setattr(module, "collect_source_evidence", reject)
    monkeypatch.setattr(
        "agent.external_capabilities.frozen_plan",
        lambda *_a: called.append(True),
    )
    with pytest.raises(RuntimeError, match="release_provenance_missing"):
        module.collect_runtime_evidence(tmp_path, tmp_path)
    assert called == []
