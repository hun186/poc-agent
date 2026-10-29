"""No external SQL, ES, Ollama, or API service is contacted."""
import json
import threading

import pytest
from fastapi import HTTPException

from api.routers.editor_dependencies import require_superuser
from sra_api.routers import operator_e2e
from sra_api.services.operator_preflight_state import (
    OperatorPreflightTracker, PreflightInProgress,
)


def test_running_snapshot_and_overlapping_request_never_invokes_backend():
    tracker = OperatorPreflightTracker()
    entered, release = threading.Event(), threading.Event()
    seen = []
    def first():
        entered.set()
        assert release.wait(3)
        seen.append("first")
        return {"ok": True}
    thread = threading.Thread(target=lambda: tracker.run(first))
    thread.start()
    try:
        assert entered.wait(3)
        snapshot = tracker.snapshot()
        assert snapshot["state"] == "RUNNING"
        assert snapshot["generation"] == 1
        assert snapshot["scope"] == "process_local_runtime_evidence_only"
        with pytest.raises(PreflightInProgress, match="external_e2e_preflight_in_progress"):
            tracker.run(lambda: seen.append("second"))
        assert seen == []
        assert tracker.snapshot()["state"] == "RUNNING"
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert seen == ["first"]
    assert tracker.snapshot()["state"] == "COMPLETED"
    assert tracker.run(lambda: "again") == "again"
    assert tracker.snapshot()["generation"] == 2


def test_failure_unwinds_guard_without_echoing_internal_error():
    tracker = OperatorPreflightTracker()
    def sensitive():
        raise RuntimeError("https://private.example Bearer VERY_SECRET")
    with pytest.raises(RuntimeError, match="VERY_SECRET"):
        tracker.run(sensitive)
    assert tracker.snapshot()["state"] == "FAILED"
    assert "VERY_SECRET" not in json.dumps(tracker.snapshot())
    assert "private.example" not in json.dumps(tracker.snapshot())
    assert tracker.run(lambda: 42) == 42
    assert tracker.snapshot()["state"] == "COMPLETED"


def test_endpoint_rejects_concurrent_preflight_with_409(monkeypatch):
    tracker = OperatorPreflightTracker()
    entered, release = threading.Event(), threading.Event()
    called = []
    def expensive(*_args):
        called.append(1)
        entered.set()
        assert release.wait(3)
        return {"schema_version": "requirement_e2e_runtime_evidence_v1"}
    monkeypatch.setattr(operator_e2e, "_preflight_tracker", tracker)
    monkeypatch.setattr(operator_e2e, "configured_runtime_evidence", expensive)
    thread = threading.Thread(target=lambda: operator_e2e.runtime_evidence("release", object()))
    thread.start()
    try:
        assert entered.wait(3)
        assert operator_e2e.runtime_evidence_status(object())["state"] == "RUNNING"
        with pytest.raises(HTTPException) as conflict:
            operator_e2e.runtime_evidence("release", object())
        assert conflict.value.status_code == 409
        assert conflict.value.detail == {"code": "external_e2e_preflight_in_progress"}
        assert called == [1]
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert operator_e2e.runtime_evidence_status(object())["state"] == "COMPLETED"


def test_status_route_is_superuser_protected():
    from fastapi.params import Depends
    from inspect import signature
    parameter = signature(operator_e2e.runtime_evidence_status).parameters["user"]
    assert isinstance(parameter.default, Depends)
    assert parameter.default.dependency is require_superuser


def test_status_is_not_persistent_acceptance_or_fake_timeout():
    tracker = OperatorPreflightTracker()
    snapshot = tracker.snapshot()
    assert snapshot["state"] == "NOT_STARTED"
    assert snapshot["generation"] == 0
    assert "acceptance" not in snapshot
    assert "FULL_LIVE" not in json.dumps(snapshot)
    assert "TIMEOUT" not in json.dumps(snapshot)
