"""Hosted-only tests: no private ES, Ollama, SQL or report-job execution."""
from __future__ import annotations

import threading
import time

import pytest

from agent.e2e_preflight_budget import PreflightDeadlineExceeded
from agent.external_capabilities import (
    BackendPlan, CapabilityError, frozen_plan, install_plan,
    reset_plan_for_tests,
)
from sra_api.services.operator_preflight_state import OperatorPreflightTracker


PLAN = BackendPlan("live", "live", "live", "pass", "pass")
DRIFT = BackendPlan("live", "live", "live", "pass", "dataset_incompatible")


@pytest.fixture(autouse=True)
def isolated_published_plan(monkeypatch):
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    reset_plan_for_tests()
    yield
    reset_plan_for_tests()


def test_recheck_suspends_old_plan_until_fresh_probe_and_complete_evidence():
    assert frozen_plan(lambda mode: PLAN) == PLAN
    tracker = OperatorPreflightTracker()
    entered, released = threading.Event(), threading.Event()
    called = []
    returned = []
    errors = []

    def evidence():
        entered.set()
        assert released.wait(3)
        current = frozen_plan(lambda mode: called.append(mode) or PLAN)
        assert current == PLAN
        return {"acceptance": current.evidence()}

    def run():
        try:
            returned.append(tracker.run(evidence))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
            frozen_plan()
        with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
            install_plan(PLAN)
        assert tracker.snapshot()["state"] == "RUNNING"
    finally:
        released.set()
        thread.join(3)
    assert not thread.is_alive()
    assert errors == []
    assert called == ["live"]
    assert returned[0]["acceptance"]["classification"] == "FULL_LIVE"
    assert frozen_plan() == PLAN
    assert tracker.snapshot()["state"] == "COMPLETED"


def test_repeated_operator_preflight_must_reprobe_not_echo_old_capability():
    assert frozen_plan(lambda _: PLAN) == PLAN
    calls = []
    tracker = OperatorPreflightTracker()
    for _ in range(2):
        assert tracker.run(
            lambda: frozen_plan(lambda mode: calls.append(mode) or PLAN)
        ) == PLAN
    assert calls == ["live", "live"]
    assert frozen_plan() == PLAN


def test_drift_fails_closed_and_same_original_plan_can_be_revalidated():
    assert frozen_plan(lambda _: PLAN) == PLAN
    tracker = OperatorPreflightTracker()
    with pytest.raises(CapabilityError, match="external_capability_plan_drift"):
        tracker.run(lambda: frozen_plan(lambda _: DRIFT))
    assert tracker.snapshot()["state"] == "FAILED"
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()
    # A new operator run re-verifies the original immutable policy.
    assert tracker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    assert frozen_plan() == PLAN
    assert tracker.snapshot()["state"] == "COMPLETED"


def test_backend_probe_error_keeps_previous_plan_suspended():
    assert frozen_plan(lambda _: PLAN) == PLAN
    tracker = OperatorPreflightTracker()
    def broken(_mode):
        raise OSError("private-model.example?access_token=SENSITIVE")
    with pytest.raises(OSError, match="SENSITIVE"):
        tracker.run(lambda: frozen_plan(broken))
    assert tracker.snapshot()["state"] == "FAILED"
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()
    assert "SENSITIVE" not in str(tracker.snapshot())


def test_source_failure_before_backend_probe_suspends_cached_authority():
    assert frozen_plan(lambda _: PLAN) == PLAN
    tracker = OperatorPreflightTracker()
    def bad_source():
        raise RuntimeError("release_provenance_missing")
    with pytest.raises(RuntimeError, match="release_provenance_missing"):
        tracker.run(bad_source)
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_failure_after_equal_provisional_probe_does_not_restore_old_plan():
    assert frozen_plan(lambda _: PLAN) == PLAN
    tracker = OperatorPreflightTracker()
    def fail_after_probe():
        assert frozen_plan(lambda _: PLAN) == PLAN
        raise RuntimeError("artifact_root_mismatch")
    with pytest.raises(RuntimeError, match="artifact_root_mismatch"):
        tracker.run(fail_after_probe)
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_expiry_after_equal_probe_does_not_restore_stale_plan():
    assert frozen_plan(lambda _: PLAN) == PLAN
    tracker = OperatorPreflightTracker(budget_seconds=0.01)
    def slow():
        assert frozen_plan(lambda _: PLAN) == PLAN
        time.sleep(0.03)
        return {"ok": True}
    with pytest.raises(PreflightDeadlineExceeded):
        tracker.run(slow)
    assert tracker.snapshot()["state"] == "TIMEOUT"
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_empty_operator_run_cannot_reauthorize_a_suspended_plan():
    assert frozen_plan(lambda _: PLAN) == PLAN
    tracker = OperatorPreflightTracker()
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        tracker.run(lambda: {"pretend": "success_without_reprobe"})
    assert tracker.snapshot()["state"] == "FAILED"
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_drift_does_not_allow_switch_to_semantic_mock():
    assert frozen_plan(lambda _: PLAN) == PLAN
    mixed = BackendPlan("live", "semantic_mock", "live", "transport_unavailable", "pass")
    tracker = OperatorPreflightTracker()
    with pytest.raises(CapabilityError, match="external_capability_plan_drift"):
        tracker.run(lambda: frozen_plan(lambda _: mixed))
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_admitted_plan_survives_operator_suspension_inside_agent_scope():
    from agent.external_capabilities import (
        requirement_acceptance_scope, suspend_published_plan,
    )
    assert frozen_plan(lambda _: PLAN) == PLAN
    admitted = frozen_plan()
    with requirement_acceptance_scope(admitted):
        assert frozen_plan() == PLAN
        suspend_published_plan()
        assert frozen_plan() == PLAN
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_admitted_plan_reaches_smolagents_tool_worker_thread():
    from types import SimpleNamespace
    from agent.external_capabilities import (
        requirement_acceptance_scope, suspend_published_plan,
    )
    from agent.tools_es.common import bind_requirement_acceptance, requirement_acceptance_tool_scope
    assert frozen_plan(lambda _: PLAN) == PLAN
    with requirement_acceptance_scope(frozen_plan()):
        tool = bind_requirement_acceptance(SimpleNamespace())
    suspend_published_plan()
    observed = []
    def remote_tool():
        with requirement_acceptance_tool_scope(tool):
            observed.append(frozen_plan())
    thread = threading.Thread(target=remote_tool)
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert observed == [PLAN]
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_report_worker_pins_admitted_plan_for_later_llm_and_es_lookups(monkeypatch, tmp_path):
    from io import BytesIO
    from types import SimpleNamespace
    from zipfile import ZipFile
    from agent.external_capabilities import suspend_published_plan
    from sra_api.services.report_job_worker import ReportJobWorker
    from sra_api.services import report_job_worker as worker_module
    from agent import external_capabilities

    assert frozen_plan(lambda _: PLAN) == PLAN
    observed = []
    class Store:
        def complete(self, *args):
            observed.append(("complete", args))
        def fail(self, *args):
            observed.append(("fail", args))
    job = SimpleNamespace(
        job_id="e2e-accepted-1", filename="result.docx", prompt="bounded report",
        session_id="demo-session", model="requirement-e2e:test-model",
    )
    def fake_turn(**kwargs):
        assert kwargs["payload"].model == "test-model"
        assert frozen_plan() == PLAN
        suspend_published_plan()  # models a concurrent operator rerun
        # Both model and ES capability lookups use the admitted job's plan.
        assert frozen_plan().llm_backend == "live"
        assert frozen_plan().elasticsearch_backend == "live"
        return SimpleNamespace(output="report", turn_id="demo-turn")
    monkeypatch.setattr(
        external_capabilities, "verified_requirement_e2e_job_model",
        lambda job: (True, "test-model"),
    )
    monkeypatch.setattr(worker_module, "execute_agent_turn", fake_turn)

    archive = BytesIO()
    with ZipFile(archive, "w") as doc:
        doc.writestr("[Content_Types].xml", "<Types/>")
    class Export:
        def build_docx_bytes(self, *_a, **_kw):
            return archive.getvalue(), "result.docx"
    monkeypatch.setattr(worker_module, "ExportWordService", Export)

    ReportJobWorker(Store(), tmp_path).execute(job)
    assert observed and observed[0][0] == "complete", observed
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_new_report_job_still_denied_after_operator_suspend(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from agent.external_capabilities import suspend_published_plan
    from sra_api.services.report_job_worker import ReportJobWorker
    from sra_api.services import report_job_worker as worker_module
    from agent import external_capabilities
    assert frozen_plan(lambda _: PLAN) == PLAN
    suspend_published_plan()
    seen = []
    class Store:
        def complete(self, *_args):
            pytest.fail("suspended job may not complete")
        def fail(self, *args):
            seen.append(args)
    monkeypatch.setattr(external_capabilities, "verified_requirement_e2e_job_model",
                        lambda job: (True, "model"))
    monkeypatch.setattr(worker_module, "execute_agent_turn",
                        lambda **kwargs: pytest.fail("should fail at admission"))
    job = SimpleNamespace(job_id="e2e-new", filename="no.docx", prompt="x",
                          session_id="s", model="requirement-e2e:model")
    ReportJobWorker(Store(), tmp_path).execute(job)
    assert len(seen) == 1
    assert seen[0][1] == "CapabilityError"
