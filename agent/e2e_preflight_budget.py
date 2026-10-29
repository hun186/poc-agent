"""Cooperative budget for explicitly authorized operator E2E only.

Never confuses an expired budget with SDK cancellation/remote rollback.
Normal production report generation has no budget context.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

E2E_SERVER_PREFLIGHT_BUDGET_SECONDS = 540.0
_DEADLINE: ContextVar[float | None] = ContextVar("operator_e2e_deadline", default=None)


class PreflightDeadlineExceeded(RuntimeError):
    """Only a fixed, redacted category escapes to the operator API."""


@contextmanager
def preflight_budget(seconds: float = E2E_SERVER_PREFLIGHT_BUDGET_SECONDS) -> Iterator[None]:
    if seconds <= 0:
        raise ValueError("positive_budget_required")
    deadline = time.monotonic() + seconds
    parent = _DEADLINE.get()
    token = _DEADLINE.set(min(parent, deadline) if parent is not None else deadline)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def budget_active() -> bool:
    return _DEADLINE.get() is not None


def check_budget() -> None:
    end = _DEADLINE.get()
    if end is not None and time.monotonic() >= end:
        raise PreflightDeadlineExceeded("external_e2e_preflight_deadline_exceeded")


def budget_timeout(maximum_seconds: float) -> float:
    """Bound per-call timeout by this request's remaining monotonic budget."""
    if maximum_seconds <= 0:
        raise ValueError("positive_timeout_required")
    end = _DEADLINE.get()
    if end is None:
        return maximum_seconds
    remaining = end - time.monotonic()
    if remaining <= 0:
        raise PreflightDeadlineExceeded("external_e2e_preflight_deadline_exceeded")
    return min(remaining, maximum_seconds)
