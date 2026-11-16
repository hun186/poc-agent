"""Atomic *admission-only* budget for a future adaptive Report Job request.

One instance belongs to ONE trusted request, not a shared process-wide quota.
It bounds the number of newly admitted rounds and ES/planner calls, and leaves
an explicit generation reserve. It does NOT cancel an in-flight SDK call, limit
per-call tokens, coordinate across hosts, or change production routing.
"""
from __future__ import annotations

import math
from threading import Lock
from time import monotonic
from typing import Callable

from .contracts import BudgetSnapshot


class RequestAdmissionBudget:
    """Fail-closed, monotonic admission for a single future N-round request.

    The caller must obtain admission immediately before EVERY new round and
    ES/LLM planner call (including the first search). It must separately set
    transport timeouts and stop/cancel in-flight operations. Counters are never
    refunded after a call is admitted, even when a transport fails.
    """

    def __init__(
        self, *, total_seconds: int = 2400, generation_reserve_seconds: int = 600,
        max_rounds: int = 8, max_es_calls: int = 24,
        max_planner_calls: int = 6, clock: Callable[[], float] = monotonic,
    ) -> None:
        if (type(total_seconds) is not int or not 1 <= total_seconds <= 86400
                or type(generation_reserve_seconds) is not int
                or not 0 <= generation_reserve_seconds < total_seconds
                or type(max_rounds) is not int or not 1 <= max_rounds <= 32
                or type(max_es_calls) is not int or not 1 <= max_es_calls <= 1000
                or type(max_planner_calls) is not int or not 0 <= max_planner_calls <= 100
                or not callable(clock)):
            raise ValueError("invalid_request_admission_budget")
        self._clock = clock
        self._lock = Lock()
        self._start = self._read_time()
        self._end = self._start + total_seconds
        self._retrieval_end = self._end - generation_reserve_seconds
        self._reserve = generation_reserve_seconds
        self._max = {"round": max_rounds, "es": max_es_calls, "planner": max_planner_calls}
        self._used = {"round": 0, "es": 0, "planner": 0}
        # Request-local, once-only claim for one completed Evidence history.
        # A strategy claim is nonrefundable, even if the planner fails.
        self._strategy_claimed_after = -1

    def _read_time(self) -> float:
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("invalid_request_admission_clock")
        return float(value)

    def admit(self, kind: str) -> bool:
        """Atomically spend one nonrefundable call/round slot if still safe."""
        if kind not in ("round", "es", "planner"):
            raise ValueError("invalid_request_admission_kind")
        with self._lock:
            # Clock failure is a denial, not an opportunity for new IO.
            try:
                now = self._read_time()
            except Exception:
                return False
            if (now < self._start or now >= self._retrieval_end
                    or self._used[kind] >= self._max[kind]
                    or (kind != "round" and self._used["round"] == 0)):
                return False
            self._used[kind] += 1
            return True

    def claim_next_strategy(self, completed_rounds: int) -> bool:
        """Atomically consume ONE planner slot for ONE completed history.

        Prevent repeated/concurrent LLM planning on the same Evidence round,
        and reject exhausted next-round quota BEFORE paying for planner LLM.
        This is a pure admission operation; no model or ES call is performed.
        """
        if type(completed_rounds) is not int or completed_rounds < 1:
            return False
        with self._lock:
            try:
                now = self._read_time()
            except Exception:
                return False
            if (now < self._start or now >= self._retrieval_end
                    or self._used["round"] != completed_rounds
                    or self._strategy_claimed_after >= completed_rounds
                    or self._used["round"] >= self._max["round"]
                    or self._used["planner"] >= self._max["planner"]
                    or self._used["es"] >= self._max["es"]):
                return False
            self._strategy_claimed_after = completed_rounds
            self._used["planner"] += 1
            return True

    def snapshot(self) -> BudgetSnapshot:
        """A conservative planner hint, not an in-flight cancellation deadline."""
        with self._lock:
            try:
                now = self._read_time()
                remaining = int(max(0.0, self._end - now)) if now >= self._start else 0
            except Exception:
                remaining = 0
            # The planner's preflight check requires remaining > reserve.
            active = remaining > self._reserve and self._used["round"] > 0
            return BudgetSnapshot(
                remaining_es_calls=max(0, self._max["es"] - self._used["es"]) if active else 0,
                remaining_planner_calls=max(0, self._max["planner"] - self._used["planner"]) if active else 0,
                remaining_seconds=remaining,
                generation_reserve_seconds=self._reserve,
            )

    @property
    def rounds_started(self) -> int:
        with self._lock:
            return self._used["round"]
