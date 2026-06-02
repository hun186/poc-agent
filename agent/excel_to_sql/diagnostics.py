"""Diagnostic helpers for ingestion commands."""

from __future__ import annotations

import importlib
import sys


def enable_native_crash_tracebacks():
    """Ask Python to print a traceback if a native extension segfaults.

    A bare ``Segmentation fault (core dumped)`` is emitted by the OS after the
    interpreter dies in native code, so normal Python exceptions/retry handling
    cannot report the failing line. ``faulthandler`` gives the next crash a
    best-effort Python stack trace without changing import behavior.
    """

    faulthandler = importlib.import_module("faulthandler")
    try:
        if not faulthandler.is_enabled():
            faulthandler.enable(file=sys.stderr, all_threads=True)
    except Exception:
        # Diagnostics must never make ingestion fail on platforms where stderr
        # cannot be used with faulthandler.
        return
