"""Operator-only provisional E2E BackendPlan: no SQL, ES, Ollama or live API."""
from __future__ import annotations

import threading
import time

import pytest

from agent import e2e_preflight_budget as budget
from agent.external_capabilities import (
    BackendPlan, CapabilityError, frozen_plan, reset_plan_for_tests,
)
from sra_api.services.operator_preflight_state import OperatorPreflightTracker


@pytest.fixture(autouse=True)
def clean_plan(monkeypatch):
    reset_plan_for_tests()
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    yield
    reset_plan_for_tests()


PLAN = BackendPlan("live", "live", "live", "pass", "pass")


def test_candidate_is_invisible_to_other_threads_until_complete_evidence():
    tracker = OperatorPreflightTracker()
    prepared, resume = threading.Event(), threading.Event()
    responses = []
    def evidence():
        assert frozen_plan(lambda _mode: PLAN) == PLAN
        assert frozen_plan() == PLAN  # same operator request can use candidate
        prepared.set()
        assert resume.wait(3)
        return {"ok": True}
    def execute():
        responses.append(tracker.run(evidence))
    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert prepared.wait(3)
        with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
            frozen_plan()  # another request/job does NOT inherit provisional plan
        assert tracker.snapshot()["state"] == "RUNNING"
    finally:
        resume.set()
        worker.join(3)
    assert not worker.is_alive()
    assert responses == [{"ok": True}]
    assert frozen_plan() == PLAN
    assert tracker.snapshot()["state"] == "COMPLETED"


def test_failure_after_candidate_does_not_install_and_retry_can_prepare():
    tracker = OperatorPreflightTracker()
    def partial_evidence():
        assert frozen_plan(lambda _mode: PLAN) == PLAN
        raise RuntimeError("artifact_root_mismatch")
    with pytest.raises(RuntimeError, match="artifact_root_mismatch"):
        tracker.run(partial_evidence)
    assert tracker.snapshot()["state"] == "FAILED"
    with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
        frozen_plan()
    assert tracker.run(lambda: (frozen_plan(lambda _mode: PLAN), "done")[1]) == "done"
    assert tracker.snapshot()["state"] == "COMPLETED"
    assert frozen_plan() == PLAN


def test_overdue_after_provisional_candidate_never_publishes():
    tracker = OperatorPreflightTracker(budget_seconds=0.01)
    def late_evidence():
        frozen_plan(lambda _mode: PLAN)
        time.sleep(0.03)
        return {"ok": True}
    with pytest.raises(budget.PreflightDeadlineExceeded):
        tracker.run(late_evidence)
    assert tracker.snapshot()["state"] == "TIMEOUT"
    with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
        frozen_plan()


def test_no_plan_operation_keeps_local_authority_unchanged():
    tracker = OperatorPreflightTracker()
    assert tracker.run(lambda: {"source": "verified"}) == {"source": "verified"}
    with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
        frozen_plan()


def test_direct_resolution_contract_remains_immediate_outside_operator_handler():
    # Compatibility with existing tests and non-HTTP internal operator paths;
    # production jobs still require a local frozen plan or reject.
    assert frozen_plan(lambda _mode: PLAN) == PLAN
    assert frozen_plan() == PLAN


def test_stage_rejects_mismatching_mode_without_publishing(monkeypatch):
    tracker = OperatorPreflightTracker()
    bad = BackendPlan("auto", "live", "live", "pass", "pass")
    with pytest.raises(CapabilityError, match="external_capability_plan_frozen"):
        tracker.run(lambda: frozen_plan(lambda _mode: bad))
    with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
        frozen_plan()


def test_stage_is_not_inherited_by_independent_threads():
    tracker = OperatorPreflightTracker()
    exceptions = []
    def evidence():
        assert frozen_plan(lambda _mode: PLAN) == PLAN
        def other_thread():
            try:
                frozen_plan()
            except CapabilityError as e:
                exceptions.append(str(e))
        child = threading.Thread(target=other_thread)
        child.start()
        child.join(3)
        assert not child.is_alive()
        return "done"
    assert tracker.run(evidence) == "done"
    assert exceptions == ["external_capability_plan_unresolved"]
    assert frozen_plan() == PLAN
