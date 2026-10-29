"""Regression contract: startup diagnostic logs are useful and secret-free."""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from sra_api.core.startup_stage import STAGES, StartupStages


def test_checkpoint_logging_uses_only_fixed_literals(caplog):
    clock_values = iter((10.0, 10.125, 12.25))
    stages = StartupStages(clock=lambda: next(clock_values))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        stages.mark("lifespan.enter")
        stages.mark("external_plan.begin")
    assert [record.getMessage() for record in caplog.records] == [
        "SRA_STARTUP phase=lifespan.enter elapsed_ms=125",
        "SRA_STARTUP phase=external_plan.begin elapsed_ms=2250",
    ]


@pytest.mark.parametrize("value", ["password=abc", "bearer secret", "stage\nsecret", "", "foo"])
def test_arbitrary_unreviewed_stage_cannot_leak_to_logs(value, caplog):
    stages = StartupStages(clock=lambda: 1.0)
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        with pytest.raises(ValueError, match="invalid_startup_stage"):
            stages.mark(value)
    assert not caplog.records


def test_every_phase_literal_is_reviewed_and_startup_probes_are_traceable():
    source = (Path(__file__).resolve().parents[1] / "sra_api/main.py").read_text()
    tree = ast.parse(source)
    lifespan = next(node for node in tree.body
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    calls = [node for node in ast.walk(lifespan)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "mark"
             and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "startup"
             and len(node.args) == 1
             and isinstance(node.args[0], ast.Constant)
             and isinstance(node.args[0].value, str)]
    # AST walking is breadth-first; source line order is the execution order
    # for this static, non-branch-overlapping checkpoint contract.
    actual = [node.args[0].value for node in sorted(calls, key=lambda n: n.lineno)]
    assert actual == [
        "lifespan.enter", "signing_config.begin", "signing_config.done",
        "external_plan.begin", "external_plan.done",
        "requirement_store.begin", "requirement_store.done",
        "schedule_store.begin", "schedule_store.done",
        "report_store.begin", "report_store.done",
        "report_recovery.begin", "report_recovery.done",
        "report_worker.begin", "report_worker.done", "lifespan.ready",
        "lifespan.shutdown",
    ]
    assert set(actual) == STAGES


def test_logger_never_embeds_arguments_or_exception_text():
    source = (Path(__file__).resolve().parents[1] / "sra_api/core/startup_stage.py").read_text()
    assert 'self._logger.info("SRA_STARTUP phase=%s elapsed_ms=%d", stage, elapsed_ms)' in source
    assert "format_exception" not in source
    assert "exc_info=" not in source
