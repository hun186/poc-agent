from __future__ import annotations

import math
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from typing import Callable


SCHEDULE_WORKER_ACTOR = "requirement-schedule-worker"
_POLL_INTERVAL_ENV = "REQUIREMENT_SCHEDULE_WORKER_POLL_INTERVAL"


def parse_poll_interval() -> float:
    """Return the validated schedule-only polling interval."""
    try:
        value = float(os.getenv(_POLL_INTERVAL_ENV, "2.0"))
    except (TypeError, ValueError) as exc:
        raise ValueError("schedule_worker_config_invalid") from exc
    if not math.isfinite(value) or not 0.1 <= value <= 300.0:
        raise ValueError("schedule_worker_config_invalid")
    return value


class RequirementScheduleWorker:
    def __init__(self, store, poll_interval: float, *, clock: Callable[[], datetime] | None = None):
        if not math.isfinite(poll_interval) or not 0.1 <= poll_interval <= 300.0:
            raise ValueError("schedule_worker_config_invalid")
        self.store = store
        self.poll_interval = poll_interval
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run_once(self) -> object | None:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
            raise RuntimeError("invalid_utc_clock")
        now = now.replace(microsecond=0)
        return self.store.claim_due(now_utc=now, actor=SCHEDULE_WORKER_ACTOR)

    def run(self, stop_event) -> None:
        while not stop_event.is_set():
            try:
                claimed = self.run_once()
            except RuntimeError as exc:
                if str(exc).split(":", 1)[0] != "persistence_error":
                    raise
                print("persistence_error", file=sys.stderr)
                stop_event.wait(self.poll_interval)
                continue
            if claimed is None:
                stop_event.wait(self.poll_interval)


def run_schedule_worker(worker: RequirementScheduleWorker, stop_event=None) -> None:
    """Run continuously with process signals mapped to an interruptible stop."""
    stop = stop_event or threading.Event()
    previous = signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    try:
        try:
            worker.run(stop)
        except KeyboardInterrupt:
            stop.set()
    finally:
        signal.signal(signal.SIGTERM, previous)
