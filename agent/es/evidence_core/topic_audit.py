"""Request-scoped, content-free Topic Match adaptive audit for Word/Markdown.

A Data Agent constructs tool instances on its caller thread but may execute
their methods on worker threads.  Capture the *sink object* per tool instance
then restore it only around the tool invocation. No private Evidence content,
question, date, ES identity or model response can enter this contract.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_SINK: ContextVar[list[dict] | None] = ContextVar("sraf_topic_audit_sink", default=None)
_MAX_RECORDS = 32
_MAX_VALUE = 1_000_000
_STATUSES = {"disabled", "insufficient_groups", "strict_not_low",
             "no_trusted_anchor", "shadow", "applied"}
_MODES = {"off", "shadow", "on"}
_FIELDS = ("inspected", "date_eligible", "two_text_axes", "direct_subject",
           "same_event_context", "blocked_meta_only", "blocked_unanchored",
           "uninspected_by_cap", "proposed", "selected")


def current_sink() -> list[dict] | None:
    return _SINK.get()


@contextmanager
def bind_sink(sink: list[dict] | None) -> Iterator[None]:
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def record(*, mode: str, status: str, strict: int, counts: dict[str, int],
           anchor_source: str = "none") -> None:
    sink = current_sink()
    if sink is None:
        return
    if len(sink) >= _MAX_RECORDS:
        # One fixed sentinel signals that later counters were not observed;
        # never report the first 32 slices as a complete request total.
        if len(sink) == _MAX_RECORDS:
            sink.append({"mode": mode, "status": "truncated"})
        return
    if mode not in _MODES or status not in _STATUSES:
        return
    if type(strict) is not int or not 0 <= strict <= _MAX_VALUE:
        return
    if any(type(counts.get(k)) is not int or
           not 0 <= counts[k] <= _MAX_VALUE for k in _FIELDS):
        return
    sink.append({"mode": mode, "status": status, "strict": strict,
                 "anchor_source": (anchor_source if anchor_source in
                                   {"explicit", "prose"} else "none"),
                 **{key: counts[key] for key in _FIELDS}})


def summary(sink: list[dict] | None, *, mode: str) -> dict:
    mode = mode if mode in _MODES else "off"
    rows = sink if isinstance(sink, list) else []
    valid = [r for r in rows if isinstance(r, dict)
             and r.get("mode") == mode and r.get("status") in _STATUSES
             and type(r.get("strict")) is int and
             all(type(r.get(k)) is int for k in _FIELDS)]
    def total(key: str) -> int:
        return min(_MAX_VALUE, sum(max(0, r[key]) for r in valid))
    return {
        "schema": "sraf_topic_adaptive_report_v1",
        "scope": "data_agent_tool_slices_not_global_recall",
        "mode": mode,
        "slices": min(_MAX_RECORDS, len(valid)),
        "truncated": any(isinstance(r, dict) and
                         r.get("status") == "truncated" for r in rows),
        "strict": total("strict"),
        "proposed": total("proposed"),
        "selected": total("selected"),
        "no_anchor": sum(r["status"] == "no_trusted_anchor" for r in valid),
        "not_low": sum(r["status"] == "strict_not_low" for r in valid),
        "attempted": sum(r["status"] in {"shadow", "applied"} for r in valid),
        "uninspected": total("uninspected_by_cap"),
        "prose_shadow_slices": sum(
            r.get("anchor_source") == "prose" and r["status"] == "shadow"
            for r in valid
        ),
    }
