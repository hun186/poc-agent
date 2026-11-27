"""ARC request-local atomic reservations and tool-worker scope.

One instance must be owned by one report and explicitly propagated to its
workers. Never create a process-global budget or treat reservations as
observed consumption. No automatic refunds or reset on new rounds.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from threading import Lock
import math
from time import monotonic


@dataclass(frozen=True)
class ArcUnits:
    slices: int = 0
    hits: int = 0
    rows: int = 0
    chars: int = 0
    es_calls: int = 0
    llm_calls: int = 0

    def __post_init__(self):
        if any(type(getattr(self, f.name)) is not int or getattr(self, f.name) < 0
               for f in fields(self)):
            raise ValueError("invalid ARC budget units")


# Provisional hard ceilings, not performance measurements.
REQUEST_CEILING = ArcUnits(8, 1024, 2048, 1048576, 2, 2)
ROUND_CEILING = ArcUnits(4, 512, 1024, 524288, 1, 1)
MAX_ROUNDS = 32
# Conservative admission margin, not a transport hard timeout.
OPTIONAL_MODEL_MIN_REMAINING_SECONDS = 25


def _fits(used: ArcUnits, limit: ArcUnits) -> bool:
    return all(getattr(used, f.name) <= getattr(limit, f.name) for f in fields(used))


def _plus(first: ArcUnits, second: ArcUnits) -> ArcUnits:
    return ArcUnits(**{f.name: getattr(first, f.name) + getattr(second, f.name)
                       for f in fields(first)})


class ArcRequestBudget:
    """Reserve all requested dimensions atomically before optional work.

    A failed reservation never consumes anything. Successful reservations
    remain charged even on failure/cancellation; this conservatively bounds
    retries. Counts are reservations, not actual runtime measurements.
    Round ordinals must originate from the report coordinator, not the LLM.
    """

    def __init__(self, *, request_limit: ArcUnits = REQUEST_CEILING,
                 round_limit: ArcUnits = ROUND_CEILING,
                 model_deadline_monotonic: float | None = None):
        if (type(request_limit) is not ArcUnits or type(round_limit) is not ArcUnits
                or not _fits(request_limit, REQUEST_CEILING)
                or not _fits(round_limit, ROUND_CEILING)
                or not _fits(round_limit, request_limit)):
            raise ValueError("invalid ARC budget limits")
        self._request_limit = request_limit
        self._round_limit = round_limit
        self._reserved = ArcUnits()
        self._rounds: dict[int, ArcUnits] = {}
        self._sealed = False
        self._lock = Lock()
        # No supplied deadline preserves the legacy optional-model behavior.
        # An invalid explicitly supplied cutoff fails closed for model work,
        # without interfering with local diagnostics or the formal report.
        self._model_deadline = None
        if model_deadline_monotonic is not None:
            self._model_deadline = float('-inf')
            if type(model_deadline_monotonic) in (int, float):
                try:
                    if math.isfinite(model_deadline_monotonic):
                        self._model_deadline = model_deadline_monotonic
                except (OverflowError, ValueError):
                    pass

    def _model_window_locked(self, *, admission: bool) -> bool:
        if self._sealed:
            return False
        if self._model_deadline is None:
            return True
        remaining = self._model_deadline - monotonic()
        return (remaining >= OPTIONAL_MODEL_MIN_REMAINING_SECONDS
                if admission else remaining > 0)

    def model_window_open(self, *, admission: bool = True) -> bool:
        """Check the shared time fence; not a reservation or an egress grant."""
        with self._lock:
            return self._model_window_locked(admission=admission)

    def reserve(self, round_ordinal: int, units: ArcUnits) -> bool:
        if (type(round_ordinal) is not int or not 1 <= round_ordinal <= MAX_ROUNDS
                or type(units) is not ArcUnits or units == ArcUnits()):
            return False
        with self._lock:
            if self._sealed or (units.llm_calls and not self._model_window_locked(admission=True)):
                return False
            request_next = _plus(self._reserved, units)
            round_next = _plus(self._rounds.get(round_ordinal, ArcUnits()), units)
            if (not _fits(request_next, self._request_limit)
                    or not _fits(round_next, self._round_limit)):
                return False
            self._reserved = request_next
            self._rounds[round_ordinal] = round_next
            return True

    def snapshot(self) -> tuple[ArcUnits, dict[int, ArcUnits]]:
        """Immutable unit values and a copied mapping, no query/source data."""
        with self._lock:
            return self._reserved, dict(self._rounds)

    def seal(self) -> None:
        """Prevent optional work after the report coordinator ends the scope."""
        with self._lock:
            self._sealed = True


# Private caller-side scope; never exposed as a model tool argument.
_SCOPE: ContextVar[tuple[ArcRequestBudget, int] | None] = ContextVar(
    "sraf_arc_budget_scope", default=None,
)


def current_arc_budget():
    return _SCOPE.get()


@contextmanager
def bind_arc_budget(scope):
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


@contextmanager
def data_agent_arc_budget(*, enabled: bool, model_deadline_monotonic=None):
    """Own one Data Agent invocation, not the complete deep report.

    The future report coordinator must own a shared budget across invocations.
    For now each invocation is one round, always using caller ordinal 1.
    """
    budget = (ArcRequestBudget(model_deadline_monotonic=model_deadline_monotonic)
              if enabled else None)
    with bind_arc_budget((budget, 1) if budget is not None else None):
        try:
            yield
        finally:
            if budget is not None:
                budget.seal()
