"""Process-local observation and re-entry fencing for operator E2E preflight.

This is not a cancellation mechanism or a durable cross-process job queue.
A client disconnect cannot stop an in-flight provider/Elasticsearch call.
"""
from __future__ import annotations

import threading
import time

from agent.e2e_preflight_budget import (
    E2E_SERVER_PREFLIGHT_BUDGET_SECONDS, PreflightDeadlineExceeded,
    check_budget, preflight_budget,
)
from agent.external_capabilities import (
    publish_staged_plan, staged_plan_publication,
)
from collections.abc import Callable
from sra_api.services.linux_e2e_preflight_guard import (
    HostPreflightBusy, host_preflight_guard, linux_host_guard_held,
)
from typing import Any, TypeVar

T = TypeVar("T")


class PreflightInProgress(RuntimeError):
    """Reject an overlapping operator preflight without entering the live resolver."""


class OperatorPreflightTracker:
    """Serialize the operator-only request while exposing redacted progress."""

    def __init__(self, budget_seconds: float = E2E_SERVER_PREFLIGHT_BUDGET_SECONDS) -> None:
        if budget_seconds <= 0:
            raise ValueError("positive_budget_required")
        self._budget_seconds = budget_seconds
        self._lock = threading.Lock()
        self._active = False
        self._state = "NOT_STARTED"
        self._generation = 0
        self._started: float | None = None
        self._elapsed = 0.0

    def run(self, operation: Callable[[], T]) -> T:
        with self._lock:
            if self._active:
                raise PreflightInProgress("external_e2e_preflight_in_progress")
            # Acquired before RUNNING: a rejected host-level duplicate must
            # not increment generation or masquerade as a failed execution.
            guard = host_preflight_guard()
            try:
                guard.__enter__()
            except HostPreflightBusy as exc:
                raise PreflightInProgress("external_e2e_preflight_in_progress") from exc
            try:
                self._active = True
                self._state = "RUNNING"
                self._generation += 1
                self._started = time.monotonic()
                self._elapsed = 0.0
            except BaseException:
                guard.__exit__(None, None, None)
                raise
        try:
            with preflight_budget(self._budget_seconds):
                with staged_plan_publication() as staged:
                    try:
                        result = operation()
                        # Do not publish an E2E BackendPlan until the whole
                        # operator evidence handler returned before its budget.
                        check_budget()
                        publish_staged_plan(staged)
                    except PreflightDeadlineExceeded:
                        self._finish("TIMEOUT")
                        raise
                    except Exception as exc:
                        try:
                            check_budget()
                        except PreflightDeadlineExceeded as timeout:
                            self._finish("TIMEOUT")
                            raise timeout from exc
                        self._finish("FAILED")
                        raise
                    except BaseException:
                        self._finish("FAILED")
                        raise
                    self._finish("COMPLETED")
                    return result
        finally:
            # Does not drop the host guard on an HTTP disconnect or a client
            # timeout: release occurs only when server-side run() exits.
            guard.__exit__(None, None, None)

    def _finish(self, state: str) -> None:
        with self._lock:
            if self._started is not None:
                self._elapsed = max(0.0, time.monotonic() - self._started)
            self._state = state
            self._active = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = (
                max(0.0, time.monotonic() - self._started)
                if self._active and self._started is not None
                else self._elapsed
            )
            state = self._state
            if self._active and elapsed >= self._budget_seconds:
                # A hung SDK is still running; do not fabricate cancellation.
                state = "RUNNING_OVERDUE"
            scope = "process_local_runtime_evidence_only"
            if not self._active and linux_host_guard_held():
                # A peer is holding the host lock; its state, PID, outcome and
                # generation are deliberately unknown to this process.
                state = "HOST_LOCK_HELD"
                scope = "linux_same_host_lock_observation_only"
                elapsed = 0.0
            return {
                "schema_version": "sraf_operator_preflight_status_v1",
                "state": state,
                "generation": 0 if state == "HOST_LOCK_HELD" else self._generation,
                "elapsed_seconds": round(elapsed, 3),
                "scope": scope,
            }
