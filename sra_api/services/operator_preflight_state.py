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
from collections.abc import Callable
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
            self._active = True
            self._state = "RUNNING"
            self._generation += 1
            self._started = time.monotonic()
            self._elapsed = 0.0
        with preflight_budget(self._budget_seconds):
            try:
                result = operation()
                # A provider that returns late cannot publish successful evidence.
                check_budget()
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
            return {
                "schema_version": "sraf_operator_preflight_status_v1",
                "state": state,
                "generation": self._generation,
                "elapsed_seconds": round(elapsed, 3),
                "scope": "process_local_runtime_evidence_only",
            }
