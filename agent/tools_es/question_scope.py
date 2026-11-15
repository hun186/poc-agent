"""Request-local original report question for future safe Evidence diagnostics.

This carries the caller-supplied *unrefined* question through the synchronous
CodeAgent tool call without putting it in tool arguments, logs, ES bodies or a
process-global variable. It is provenance, not an auth or subject-entity proof.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_MAX_ORIGINAL_QUESTION_CHARS = 8192
_original_report_question: ContextVar[Optional[str]] = ContextVar(
    "sraf_original_report_question", default=None,
)


def get_original_report_question() -> Optional[str]:
    """Return only the bounded question explicitly bound by this request."""
    return _original_report_question.get()


@contextmanager
def bind_original_report_question(value: Optional[str]) -> Iterator[None]:
    """Scope one report question; always reset on exceptions and nesting.

    A missing/invalid/oversized original is NOT replaced with the refined
    prompt or the LLM-generated Elasticsearch query. This function never
    truncates a question, so the later subject-anchor extractor cannot infer
    requirements from only a partial request.
    """
    original = (
        value if isinstance(value, str) and
        0 < len(value) <= _MAX_ORIGINAL_QUESTION_CHARS else None
    )
    token = _original_report_question.set(original)
    try:
        yield
    finally:
        _original_report_question.reset(token)
