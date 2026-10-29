"""Redacted, monotonic startup checkpoints for SRAF API lifespan.

All stage names are code-reviewed literals. No secrets, raw exceptions,
connection strings, model names or DB paths are accepted or logged.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

STAGES = frozenset({
    "lifespan.enter",
    "signing_config.begin",
    "signing_config.done",
    "external_plan.begin",
    "external_plan.done",
    "requirement_store.begin",
    "requirement_store.done",
    "schedule_store.begin",
    "schedule_store.done",
    "report_store.begin",
    "report_store.done",
    "report_recovery.begin",
    "report_recovery.done",
    "report_worker.begin",
    "report_worker.done",
    "lifespan.ready",
    "lifespan.shutdown",
})


class StartupStages:
    def __init__(self, logger: logging.Logger | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self._logger = logger or logging.getLogger("uvicorn.error")
        self._clock = clock or time.monotonic
        self._started = self._clock()

    def mark(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError("invalid_startup_stage")
        elapsed_ms = max(0, int((self._clock() - self._started) * 1000))
        self._logger.info("SRA_STARTUP phase=%s elapsed_ms=%d", stage, elapsed_ms)
