"""Request-local count-only measurements for trusted deep retrieval.

Count actual SDK method invocations, including failures and mandatory PIT
cleanup, rather than coordinator budget reservations. No wire-level retry
claim, LLM inference, public API changes, or report synthesis measurement.
"""
from __future__ import annotations

from contextvars import ContextVar
import json
import logging
import os
import time

_LOG = logging.getLogger("sraf.arc.deep_retrieval_resource")
_KINDS = ("pit_open", "canonical_page", "optional_frequency", "pit_close")
_SCOPE = ContextVar("sraf_deep_retrieval_measurement", default=None)


class DeepRetrievalMeasurement:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.started = time.monotonic_ns()
        self.attempts = dict.fromkeys(_KINDS, 0)

    def report(self, status):
        return {"schema": "sraf_arc_deep_retrieval_resource_v1",
                "scope": "trusted_deep_retrieval_before_report_generation",
                "es_attempts_by_kind": dict(self.attempts),
                "measurement": {
                    "status": status,
                    "elapsed_ms": (time.monotonic_ns() - self.started) // 1000000,
                    "es_calls": sum(self.attempts.values()),
                    "llm_calls": None, "prompt_tokens": None,
                    "completion_tokens": None}}


def begin_measurement(coordinator):
    # Always mask any outer measurement, including nested disabled scopes.
    measurement = (DeepRetrievalMeasurement(coordinator)
                   if os.getenv("SRAF_ARC_DEEP_RESOURCE_METRICS") == "shadow" else None)
    return _SCOPE.set(measurement), measurement


def finish_measurement(token, measurement, status):
    _SCOPE.reset(token)
    if measurement is not None:
        try:
            _LOG.warning("SRAF_ARC_DEEP_RETRIEVAL_RESOURCE=%s", json.dumps(
                measurement.report(status), sort_keys=True, separators=(",", ":")))
        except Exception:
            # Observability must never replace the retrieval result/error.
            pass


def measured_es_call(coordinator, kind, method, **kwargs):
    measurement = _SCOPE.get()
    if measurement is not None and measurement.coordinator is coordinator and kind in _KINDS:
        measurement.attempts[kind] += 1
    return method(**kwargs)
