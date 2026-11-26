"""Optional count-only ordinary report adapter observations.

A report owns one sealed collector, explicitly passed to its ES tool
threads. Counts cover only instrumented adapters, never inferred whole
provider or wire totals. No question, endpoint, source or result retention.
"""
from __future__ import annotations

from agent.arc_mode import arc_shadow_enabled

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
from threading import Lock
import time

_LOG = logging.getLogger("sraf.arc.ordinary_resource")
_SCOPE = ContextVar("sraf_ordinary_resource_scope", default=None)
_KINDS = ("es_search", "es_highlight_retry", "es_optional_frequency",
          "ollama_chat", "ollama_generate", "data_agent_generate")
_TOKEN_KEYS = ("prompt_eval_count", "eval_count")


class OrdinaryResourceMeasurement:
    def __init__(self):
        self._started = time.monotonic_ns()
        self._lock = Lock()
        self._sealed = False
        self._attempts = dict.fromkeys(_KINDS, 0)
        self._tokens = {k: 0 for k in _TOKEN_KEYS}
        self._known = {k: 0 for k in _TOKEN_KEYS}

    def attempt(self, kind):
        with self._lock:
            if self._sealed or kind not in _KINDS:
                return False
            self._attempts[kind] += 1
            return True

    def usage(self, data):
        if type(data) is not dict or data.get("done") is not True:
            return
        with self._lock:
            if self._sealed:
                return
            for key in _TOKEN_KEYS:
                value = data.get(key)
                if type(value) is int and 0 <= value <= 10**12:
                    self._tokens[key] += value
                    self._known[key] += 1

    def seal(self, outcome):
        with self._lock:
            self._sealed = True
            return {"schema": "sraf_arc_ordinary_resource_v1",
                    "scope": "ordinary_report_adapter_observation_not_full_transport_totals",
                    "outcome": outcome,
                    "elapsed_ms": (time.monotonic_ns() - self._started) // 1000000,
                    "adapter_attempts": dict(self._attempts),
                    "ollama_reported_usage": {
                        k: {"known_attempts": self._known[k],
                            "observed_sum": self._tokens[k] if self._known[k] else None}
                        for k in _TOKEN_KEYS},
                    "complete_transport_totals": False}


def current_measurement():
    return _SCOPE.get()


@contextmanager
def bind_measurement(measurement):
    token = _SCOPE.set(measurement)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def observed_attempt(kind, method, /, *args, **kwargs):
    measurement = current_measurement()
    if measurement is not None:
        measurement.attempt(kind)
    return method(*args, **kwargs)


def observed_ollama_json(kind, url, **kwargs):
    # Keep the established transport and error behavior. Associate usage
    # with this exact attempted POST, only after a successful JSON decode.
    import requests
    measurement = current_measurement()
    counted = measurement is not None and measurement.attempt(kind)
    response = requests.post(url, **kwargs)
    response.raise_for_status()
    data = response.json()
    if counted:
        measurement.usage(data)
    return data


def measure_ordinary_report(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        from agent.external_capabilities import requirement_acceptance_active
        measurement = (OrdinaryResourceMeasurement()
                       if arc_shadow_enabled("SRAF_ARC_ORDINARY_RESOURCE_METRICS")
                       and not requirement_acceptance_active() else None)
        outcome = "raised"
        with bind_measurement(measurement):
            try:
                result = func(*args, **kwargs)
                outcome = "returned"
                return result
            finally:
                if measurement is not None:
                    try:
                        record = measurement.seal(outcome)
                        _LOG.warning("SRAF_ARC_ORDINARY_RESOURCE=%s", json.dumps(
                            record, sort_keys=True, separators=(",", ":")))
                    except Exception:
                        pass
    return wrapped
