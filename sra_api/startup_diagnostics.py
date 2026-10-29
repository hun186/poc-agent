"""Non-secret, fail-closed timing markers for FastAPI lifespan startup.

Only fixed, caller-owned phase labels and exception *types* are logged.
The original exception is re-raised; this helper never skips startup work.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import time
from collections.abc import Iterator

_LOGGER = logging.getLogger("uvicorn.error")


@contextmanager
def startup_phase(phase: str) -> Iterator[None]:
    """Record begin/end or failure of a synchronous startup step."""
    start = time.monotonic()
    _LOGGER.info("SRAF startup phase=%s status=begin", phase)
    try:
        yield
    except BaseException as exc:
        elapsed_ms = max(0, round((time.monotonic() - start) * 1000))
        _LOGGER.error(
            "SRAF startup phase=%s status=failed elapsed_ms=%d error_type=%s",
            phase, elapsed_ms, type(exc).__name__,
        )
        raise
    else:
        elapsed_ms = max(0, round((time.monotonic() - start) * 1000))
        _LOGGER.info(
            "SRAF startup phase=%s status=complete elapsed_ms=%d",
            phase, elapsed_ms,
        )
