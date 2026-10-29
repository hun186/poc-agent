"""Regression checks for non-secret startup instrumentation.

These tests do not start the API, connect to SQL/ES/LLM or run Report Jobs.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sra_api import startup_diagnostics as diagnostics


def test_success_marks_start_and_end_with_elapsed_ms(monkeypatch, caplog):
    times = iter((10.0, 10.125))
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: next(times))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        with diagnostics.startup_phase("requirement_pipeline"):
            pass
    messages = [r.getMessage() for r in caplog.records if "SRAF startup" in r.getMessage()]
    assert messages == [
        "SRAF startup phase=requirement_pipeline status=begin",
        "SRAF startup phase=requirement_pipeline status=complete elapsed_ms=125",
    ]


def test_exception_not_suppressed_or_leaked(monkeypatch, caplog):
    times = iter((1.0, 1.005))
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: next(times))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        with pytest.raises(RuntimeError, match="secret-in-error"):
            with diagnostics.startup_phase("external_plan"):
                raise RuntimeError("secret-in-error password=private")
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "phase=external_plan status=begin" in messages
    assert "phase=external_plan status=failed elapsed_ms=5 error_type=RuntimeError" in messages
    assert "secret-in-error" not in messages
    assert "password=private" not in messages
    assert "status=complete" not in messages


def test_base_exception_is_not_swallowed(monkeypatch, caplog):
    times = iter((1.0, 1.0))
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: next(times))
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(KeyboardInterrupt):
            with diagnostics.startup_phase("report_job_store"):
                raise KeyboardInterrupt()
    assert "error_type=KeyboardInterrupt" in caplog.text


def test_lifespan_wraps_existing_critical_steps_without_bypassing_work():
    source = (Path(__file__).resolve().parents[1] / "sra_api/main.py").read_text(encoding="utf-8")
    for phase in (
        "signing_config", "external_plan", "requirement_pipeline",
        "schedule_pipeline", "report_job_store", "report_job_worker_start",
    ):
        assert f'with startup_phase("{phase}"):' in source
    for operation in (
        "validate_signing_config()", 'parse_mode(os.getenv("REQUIREMENT_E2E_EXTERNAL_MODE"))',
        "requirement_store.initialize()", "schedule_store.initialize()",
        "store.initialize()", "store.recover_running()", "worker.start()",
        "try: yield", "finally: worker.stop()",
    ):
        assert operation in source
