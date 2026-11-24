"""Private request-local observation of the ordinary report's real ES scope.

A receipt describes the one supported search branch, not semantic coverage,
authorization, actual index alias membership, evidence completeness or report
quality. Never put the receipt in output, trace, logs or a durable job.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import re
from threading import Lock


_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
_MAX_TRANSPORTS = 32


@dataclass(frozen=True, repr=False)
class OrdinaryScopeReceipt:
    indexes: tuple[str, ...]
    date_from: str | None
    date_to: str | None
    core_terms: tuple[str, ...]


def _indexes(value):
    if type(value) is not str:
        raise ValueError
    items = tuple(value.split(","))
    if (not 1 <= len(items) <= 8 or len(set(items)) != len(items)
            or any(not _INDEX.fullmatch(x) or ".." in x for x in items)):
        raise ValueError
    return items


def _date_pair(first, last):
    if first is None and last is None:
        return
    if type(first) is not str or type(last) is not str:
        raise ValueError
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    if start.isoformat() != first or end.isoformat() != last or start > end:
        raise ValueError


def _query_hash(body):
    query = body.get("query")
    if type(query) is not dict:
        raise ValueError
    return sha256(json.dumps(query, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).digest()


class OrdinaryScopeCapture:
    """Bounded, one-use collector shared only across this turn's tool threads."""
    def __init__(self):
        self._lock = Lock()
        self._started = self._finished = self._transports = 0
        self._invalid = self._sealed = False
        self._scope = None
        self._digest = None

    def begin_tool(self, name, *, acceptance):
        with self._lock:
            self._started += 1
            if self._sealed or self._started != 1 or name != "ESSearchNews.forward" or acceptance:
                self._invalid = True

    def end_tool(self, *, success):
        with self._lock:
            self._finished += 1
            if not success or self._sealed or self._finished != 1:
                self._invalid = True

    def declare_search(self, *, index, date_from, date_to, core_terms, body,
                       manual, must_high_value, must_selected, raw_query):
        with self._lock:
            try:
                if (self._sealed or self._invalid or self._started != 1
                        or self._scope is not None or manual is not False
                        or not (must_high_value is False or must_high_value is None)
                        or not (must_selected is False or must_selected is None)
                        or type(raw_query) is not str):
                    raise ValueError
                # The ordinary query builder infers years from query text if
                # no explicit date is supplied. Do not infer/guess that scope.
                if date_from is None and date_to is None and re.search(r"(?:19|20)\d{2}", raw_query):
                    raise ValueError
                _date_pair(date_from, date_to)
                if type(core_terms) not in (list, tuple):
                    raise ValueError
                terms = tuple(core_terms)
                if (not 1 <= len(terms) <= 8 or any(type(x) is not str or
                        not 1 <= len(x) <= 100 or x != x.strip() for x in terms)
                        or len({x.casefold() for x in terms}) != len(terms)):
                    raise ValueError
                self._scope = OrdinaryScopeReceipt(_indexes(index), date_from, date_to, terms)
                self._digest = _query_hash(body)
            except Exception:
                self._invalid = True

    def observe_transport(self, *, index, body, real_client, response):
        with self._lock:
            try:
                self._transports += 1
                if (self._sealed or self._invalid or self._scope is None
                        or self._transports > _MAX_TRANSPORTS or real_client is not True
                        or _indexes(index) != self._scope.indexes
                        or _query_hash(body) != self._digest
                        or type(response) is not dict or type(response.get("hits")) is not dict
                        or type(response["hits"].get("hits")) is not list):
                    raise ValueError
            except Exception:
                self._invalid = True

    def seal(self):
        with self._lock:
            if self._sealed:
                return None
            self._sealed = True
            if (self._invalid or self._started != 1 or self._finished != 1
                    or not 1 <= self._transports <= _MAX_TRANSPORTS):
                return None
            return self._scope


_CAPTURE: ContextVar[OrdinaryScopeCapture | None] = ContextVar("ordinary_scope_capture", default=None)


def current_ordinary_scope_capture():
    return _CAPTURE.get()


@contextmanager
def bind_ordinary_scope_capture(capture):
    token = _CAPTURE.set(capture)
    try:
        yield
    finally:
        _CAPTURE.reset(token)
