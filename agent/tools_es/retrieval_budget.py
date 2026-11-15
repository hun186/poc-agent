"""Bounded opt-in admission for *additional* ES date-refill pages (#413).

A single instance may be shared by a future request-wide planner. This is a
pre-flight gate, not transport cancellation, an ES runtime timeout, or an
OpenWebUI heartbeat. First ES response already exists before date refill.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable


class ESPageAdmissionBudget:
    """Thread-safe per-instance count/deadline gate for next-page ES calls."""

    def __init__(
        self, *,
        max_additional_es_calls: int,
        deadline_monotonic: float,
        generation_reserve_seconds: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if (type(max_additional_es_calls) is not int
                or not 0 <= max_additional_es_calls <= 10_000):
            raise ValueError("invalid_es_call_budget")
        if (type(deadline_monotonic) not in (int, float)
                or not math.isfinite(deadline_monotonic)):
            raise ValueError("invalid_deadline")
        if (type(generation_reserve_seconds) not in (int, float)
                or not math.isfinite(generation_reserve_seconds)
                or generation_reserve_seconds < 0):
            raise ValueError("invalid_generation_reserve")
        if clock is not None and not callable(clock):
            raise ValueError("invalid_clock")
        self._remaining = max_additional_es_calls
        self._deadline = float(deadline_monotonic)
        self._reserve = float(generation_reserve_seconds)
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()

    def __call__(self) -> bool:
        # Atomic across smolagents worker threads sharing the same instance;
        # no cross-host guarantee or attempt to cancel an in-flight search.
        with self._lock:
            if self._remaining == 0:
                return False
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                return False
            if float(now) >= self._deadline - self._reserve:
                return False
            self._remaining -= 1
            return True
