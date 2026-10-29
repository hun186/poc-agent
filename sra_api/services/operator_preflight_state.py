"""Process-local observation and re-entry fencing for operator E2E preflight.

This is not a cancellation mechanism or a durable cross-process job queue.
A client disconnect cannot stop an in-flight provider/Elasticsearch call.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class PreflightInProgress(RuntimeError):
    """Reject an overlapping operator preflight without entering the live resolver."""


class OperatorPreflightTracker:
    """Serialize the operator-only request while exposing redacted progress."""

    def __init__(self) -> None:
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
        try:
            result = operation()
        except BaseException:
            # Only the worker actually returning/unwinding marks termination.
            # A timed-out/disconnected HTTP client never clears RUNNING.
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
            return {
                "schema_version": "sraf_operator_preflight_status_v1",
                "state": self._state,
                "generation": self._generation,
                "elapsed_seconds": round(elapsed, 3),
                "scope": "process_local_runtime_evidence_only",
            }
