"""Same-Linux-host E2E plan-generation fencing, using isolated child processes.

All backends are simulated: no real SQL, Elasticsearch, Ollama, DOCX or
active SRAF deployment receives a request.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import pytest

from agent.external_capabilities import (
    BackendPlan, CapabilityError, frozen_plan, install_plan,
    requirement_acceptance_scope, reset_plan_for_tests,
)
from sra_api.services.operator_preflight_state import OperatorPreflightTracker
from sra_api.services.linux_e2e_preflight_guard import (
    host_preflight_guard, read_host_preflight_epoch,
)

PLAN = BackendPlan("live", "live", "live", "pass", "pass")


@pytest.fixture(autouse=True)
def isolated_plan(monkeypatch):
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    reset_plan_for_tests()
    yield
    reset_plan_for_tests()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux same-host epoch only")
def test_host_epoch_fences_prior_api_worker_and_allows_authorized_local_recheck():
    first_worker = OperatorPreflightTracker()
    assert first_worker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    original_generation = read_host_preflight_epoch()
    assert len(original_generation) == 32
    assert frozen_plan() == PLAN

    # Independent Python interpreter models a second Linux API process with
    # no access to the first worker's process-local BackendPlan. It can only
    # publish its own plan after its own successful operator preflight.
    snippet = """
from agent.external_capabilities import BackendPlan, CapabilityError, frozen_plan
from sra_api.services.operator_preflight_state import OperatorPreflightTracker
try:
    frozen_plan()
except CapabilityError as e:
    assert str(e) == "external_capability_plan_unresolved"
else:
    raise AssertionError("a peer inherited another worker's plan")
plan = BackendPlan("live", "live", "live", "pass", "pass")
assert OperatorPreflightTracker().run(lambda: frozen_plan(lambda _: plan)) == plan
assert frozen_plan() == plan
"""
    peer = subprocess.run(
        [sys.executable, "-c", snippet], check=False, capture_output=True,
        text=True, timeout=15, env=dict(os.environ),
    )
    assert peer.returncode == 0, (peer.stdout, peer.stderr)
    assert read_host_preflight_epoch() != original_generation
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        install_plan(PLAN)

    # Reauthorization requires this worker's OWN full successful preflight;
    # no plan is copied, imported or trusted just because the peer succeeded.
    assert first_worker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    assert frozen_plan() == PLAN


@pytest.mark.skipif(sys.platform != "linux", reason="Linux same-host epoch only")
def test_inflight_admitted_job_survives_peer_epoch_rotation():
    tracker = OperatorPreflightTracker()
    assert tracker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    admitted = frozen_plan()
    with requirement_acceptance_scope(admitted):
        with host_preflight_guard() as lock_fd:
            from sra_api.services.linux_e2e_preflight_guard import advance_host_preflight_epoch
            advance_host_preflight_epoch(lock_fd)
            assert frozen_plan() == admitted
        assert frozen_plan() == admitted
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux same-host epoch only")
def test_corrupt_host_epoch_fails_closed_without_exposing_contents(monkeypatch):
    from sra_api.services import linux_e2e_preflight_guard as guard
    tracker = OperatorPreflightTracker()
    assert tracker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    monkeypatch.setattr(guard, "read_host_preflight_epoch",
                        lambda: "not-the-original-generation")
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux same-host epoch only")
def test_unavailable_host_epoch_denies_new_jobs_not_existing_admission(monkeypatch):
    from sra_api.services import linux_e2e_preflight_guard as guard
    tracker = OperatorPreflightTracker()
    assert tracker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    admitted = frozen_plan()
    def unavailable():
        raise guard.HostPreflightUnavailable("external_e2e_host_guard_unavailable")
    monkeypatch.setattr(guard, "read_host_preflight_epoch", unavailable)
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()
    with requirement_acceptance_scope(admitted):
        assert frozen_plan() == PLAN


@pytest.mark.skipif(sys.platform != "linux", reason="Linux same-host epoch only")
def test_host_epoch_rotation_does_not_let_an_incomplete_preflight_restore_trust():
    tracker = OperatorPreflightTracker()
    assert tracker.run(lambda: frozen_plan(lambda _: PLAN)) == PLAN
    original = read_host_preflight_epoch()
    def failure():
        frozen_plan(lambda _: PLAN)
        raise RuntimeError("post_probe_source_error")
    with pytest.raises(RuntimeError, match="post_probe_source_error"):
        tracker.run(failure)
    assert read_host_preflight_epoch() != original
    with pytest.raises(CapabilityError, match="external_capability_plan_revalidation_required"):
        frozen_plan()


def test_direct_legacy_plan_without_operator_remains_process_local():
    # Internal non-operator callers keep their old contract; they do not
    # borrow another worker's authenticated host epoch by reading its file.
    assert frozen_plan(lambda _: PLAN) == PLAN
    assert frozen_plan() == PLAN
