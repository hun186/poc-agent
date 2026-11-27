"""Private request-lifetime bridge for an independently authorized A8 policy.

This is not an owner grant or an HTTP option. A trusted caller must supply
a live source/endpoint policy and a generation-reserved monotonic deadline.
Tool instances may cross worker threads, but stale instances cannot renew
the lifetime or use the policy after the Data Agent invocation ends.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import math
from threading import Event
import time


class _ReviewExecution:
    def __init__(self, question, policy, deadline):
        self._question = question
        self._policy = policy
        self.deadline = deadline
        self._closed = Event()

    def close(self):
        self._closed.set()

    def _live(self):
        return not self._closed.is_set() and time.monotonic() < self.deadline

    def authorize(self, **kwargs):
        if not self._live() or kwargs.get("question") != self._question:
            return False
        try:
            return self._policy(**kwargs) is True and self._live()
        except Exception:
            return False

    def refill_kwargs(self, question):
        if not self._live() or question != self._question:
            return {}
        return {"_arc_review_policy": self.authorize,
                "_arc_review_deadline_monotonic": self.deadline}


_SCOPE = ContextVar("sraf_arc_ordinary_review_execution", default=None)


def current_review_execution():
    return _SCOPE.get()


@contextmanager
def bind_review_execution(scope):
    token = _SCOPE.set(scope if type(scope) is _ReviewExecution else None)
    try:
        yield
    finally:
        _SCOPE.reset(token)


@contextmanager
def ordinary_review_execution(*, question, policy, deadline):
    scope = None
    if (type(question) is str and 0 < len(question) <= 6000
            and callable(policy) and type(deadline) in (int, float)):
        try:
            if math.isfinite(deadline) and deadline > time.monotonic():
                scope = _ReviewExecution(question, policy, deadline)
        except (OverflowError, ValueError):
            pass
    with bind_review_execution(scope):
        try:
            yield
        finally:
            if scope is not None:
                scope.close()
