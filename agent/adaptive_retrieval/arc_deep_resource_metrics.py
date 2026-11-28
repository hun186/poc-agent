"""Request-local count-only measurements for trusted deep retrieval.

Count actual SDK method invocations, including failures and mandatory PIT
cleanup, rather than coordinator budget reservations. No wire-level retry
claim, LLM inference, public API changes, or report synthesis measurement.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

from contextvars import ContextVar
import json
import logging
import time

_LOG = logging.getLogger("sraf.arc.deep_retrieval_resource")
_KINDS = ("pit_open", "canonical_page", "optional_frequency", "pit_close")
_SCOPE = ContextVar("sraf_deep_retrieval_measurement", default=None)


class DeepRetrievalMeasurement:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.started = time.monotonic_ns()
        self.attempts = dict.fromkeys(_KINDS, 0)
        self.callback_counts = {
            kind: {"attempted": 0, "returned": 0, "raised": 0,
                   "elapsed_ms": 0, "input_chars": 0, "output_chars": 0}
            for kind in ("planner", "semantic_witness")}

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


    def callback_report(self, status):
        return {"schema": "sraf_arc_deep_callback_resource_v1",
                "scope": "trusted_deep_retrieval_callback_boundaries_only",
                "status": status,
                "callbacks": {kind: dict(counts) for kind, counts in self.callback_counts.items()},
                "provider_llm_calls": None, "prompt_tokens": None,
                "completion_tokens": None}


def begin_measurement(coordinator):
    # Always mask any outer measurement, including nested disabled scopes.
    measurement = (DeepRetrievalMeasurement(coordinator)
                   if arc_shadow_enabled("SRAF_ARC_DEEP_RESOURCE_METRICS") else None)
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
        try:
            _LOG.warning("SRAF_ARC_DEEP_CALLBACK_RESOURCE=%s", json.dumps(
                measurement.callback_report(status), sort_keys=True, separators=(",", ":")))
        except Exception:
            pass


def measured_es_call(coordinator, kind, method, **kwargs):
    measurement = _SCOPE.get()
    if measurement is not None and measurement.coordinator is coordinator and kind in _KINDS:
        measurement.attempts[kind] += 1
    return method(**kwargs)


def _text_chars(value):
    return len(value) if type(value) is str else 0


def _measure_callback(measurement, kind, input_chars, call, *args, **kwargs):
    """Count actual callback boundaries, not transport attempts or valid verdicts."""
    if measurement is None:
        return call(*args, **kwargs)
    counter = measurement.callback_counts[kind]
    counter["attempted"] += 1
    counter["input_chars"] += input_chars
    started = time.monotonic_ns()
    try:
        result = call(*args, **kwargs)
        counter["returned"] += 1
        counter["output_chars"] += _text_chars(result)
        return result
    except BaseException:
        counter["raised"] += 1
        raise
    finally:
        counter["elapsed_ms"] += max(0, time.monotonic_ns() - started) // 1000000


def measured_planner_callback(planner, prompt, *, system_prompt):
    measurement = _SCOPE.get()
    if measurement is None or measurement.coordinator._planner is not planner:
        return planner.llm_call(prompt, system_prompt=system_prompt)
    return _measure_callback(measurement, "planner",
        _text_chars(prompt) + _text_chars(system_prompt),
        planner.llm_call, prompt, system_prompt=system_prompt)


def measured_semantic_callback(coordinator, assessor, target, evidence):
    measurement = _SCOPE.get()
    if measurement is None or measurement.coordinator is not coordinator:
        return assessor(target, evidence)
    # Only count the actual private argument fields, not a guessed serialized
    # provider prompt. No raw target label, passage or verdict is retained.
    return _measure_callback(measurement, "semantic_witness",
        _text_chars(target.label) + _text_chars(evidence.text),
        assessor, target, evidence)
