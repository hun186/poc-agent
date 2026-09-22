import signal
import threading
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from requirement_scheduler.coordinator import RequirementHandoffCoordinator
from requirement_scheduler.reconciliation import ReconcileResult


@dataclass(frozen=True)
class Proof:
    token: str
    generation: int


def config(**overrides):
    values = {
        "lease_duration": 0.12,
        "heartbeat_interval": 0.02,
        "poll_interval": 0.01,
        "batch_size": 20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class Store:
    def __init__(self):
        self.events = []
        self.proof = Proof("token", 1)

    def acquire_lease(self, *_args):
        self.events.append("acquire")
        return self.proof

    def renew_lease(self, proof, *_args):
        assert proof == self.proof
        self.events.append("renew")
        return self.proof

    def initialize(self):
        self.events.append("initialize")

    def release_lease(self, proof):
        self.events.append("release")
        return proof == self.proof


class Reconciler:
    def __init__(self, store, remaining=False):
        self.store = store
        self.remaining = remaining

    def reconcile_batch(self, *_args):
        self.store.events.append("reconcile")
        return ReconcileResult(0, self.remaining)


class Service:
    def __init__(self, store):
        self.store = store

    def prepare_next(self, *_args):
        self.store.events.append("prepare")
        return None


def coordinator(store, reconciler=None, service=None, **config_overrides):
    return RequirementHandoffCoordinator(
        store,
        reconciler or Reconciler(store),
        service or Service(store),
        config(**config_overrides),
        owner_id="owner",
    )


def test_reconciliation_precedes_new_prepare_and_renewal_precedes_mutation():
    store = Store()
    subject = coordinator(store)
    subject.run_once()
    subject.run_once()
    assert store.events == [
        "acquire", "reconcile", "prepare", "renew", "reconcile", "prepare"
    ]


def test_backlog_blocks_new_prepare():
    store = Store()
    subject = coordinator(store, Reconciler(store, True))
    subject.run_once()
    assert store.events == ["acquire", "reconcile"]


def test_long_authoritative_operation_is_renewed_before_fenced_mutation():
    store = Store()
    renewals = threading.Condition()
    renewal_count = 0
    original_renew = store.renew_lease

    def renew(*args):
        nonlocal renewal_count
        result = original_renew(*args)
        with renewals:
            renewal_count += 1
            renewals.notify_all()
        return result

    store.renew_lease = renew

    class LongReconciler:
        def reconcile_batch(self, proof, _limit):
            with renewals:
                assert renewals.wait_for(lambda: renewal_count >= 8, timeout=0.5)
            assert proof.token == store.proof.token
            store.events.append("fenced_mutation")
            stop.set()
            return ReconcileResult(1, True)

    stop = threading.Event()
    subject = coordinator(
        store, LongReconciler(), lease_duration=0.03, heartbeat_interval=0.004
    )
    subject.run(stop)
    assert store.events.count("renew") >= 8
    assert "fenced_mutation" in store.events


def test_heartbeat_lease_loss_invalidates_proof_and_worker_reacquires():
    store = Store()
    heartbeat_failed = threading.Event()
    acquire_count = 0

    def acquire(*_args):
        nonlocal acquire_count
        acquire_count += 1
        if acquire_count == 2:
            stop.set()
            raise RuntimeError("lease_unavailable")
        return store.proof

    def renew(*_args):
        heartbeat_failed.set()
        raise RuntimeError("lease_lost")

    store.acquire_lease = acquire
    store.renew_lease = renew

    class LosingReconciler:
        def reconcile_batch(self, proof, _limit):
            assert heartbeat_failed.wait(0.5)
            store.events.append("external_operation_returned")
            return ReconcileResult(1, False)

    stop = threading.Event()
    subject = coordinator(store, LosingReconciler())
    subject.run(stop)
    assert subject.lease is None
    assert acquire_count == 2
    assert store.events == ["initialize", "external_operation_returned"]


def test_takeover_generation_change_fences_old_coordinator_then_reacquires():
    store = Store()
    taken_over = threading.Event()
    acquired = []

    def acquire(*_args):
        acquired.append(store.proof)
        if len(acquired) == 2:
            stop.set()
        return store.proof

    def renew(proof, *_args):
        store.proof = replace(proof, token="successor", generation=proof.generation + 1)
        taken_over.set()
        raise RuntimeError("lease_lost")

    store.acquire_lease = acquire
    store.renew_lease = renew

    class TakeoverReconciler:
        def reconcile_batch(self, proof, _limit):
            assert taken_over.wait(0.5)
            assert proof != store.proof
            return ReconcileResult(1, False)

    stop = threading.Event()
    subject = coordinator(store, TakeoverReconciler())
    subject.run(stop)
    assert acquired == [Proof("token", 1), Proof("successor", 2)]
    assert subject.lease is None


def test_lease_unavailable_is_bounded_contention_and_retries_acquire():
    store = Store()
    attempts = 0

    def acquire(*_args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("lease_unavailable")
        return store.proof

    store.acquire_lease = acquire

    class StopReconciler(Reconciler):
        def reconcile_batch(self, *_args):
            stop.set()
            return ReconcileResult(0, True)

    stop = threading.Event()
    subject = coordinator(store, StopReconciler(store))
    subject.run(stop)
    assert attempts == 2
    assert store.events == ["initialize", "release"]


def test_unexpected_invariant_error_still_escapes():
    store = Store()

    class BrokenReconciler:
        def reconcile_batch(self, *_args):
            raise ValueError("semantic_identity_corrupt")

    with pytest.raises(ValueError, match="semantic_identity_corrupt"):
        coordinator(store, BrokenReconciler()).run(threading.Event())
    assert store.events == ["initialize", "acquire", "release"]


def test_sigterm_stops_active_heartbeat_without_orphan_or_late_renewal(monkeypatch):
    from requirement_scheduler import cli

    handlers = {}
    monkeypatch.setattr(
        signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler)
    )
    store = Store()
    entered = threading.Event()

    class BlockingReconciler:
        def reconcile_batch(self, *_args):
            entered.set()
            while not subject_stop.is_set():
                time.sleep(0.001)
            return ReconcileResult(0, True)

    subject = coordinator(store, BlockingReconciler(), heartbeat_interval=0.005)
    subject_stop = threading.Event()

    runner = threading.Thread(
        target=lambda: cli.run_handoff_worker(subject), name="handoff-test-runner"
    )
    runner.start()
    assert entered.wait(0.5)
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    subject_stop.set()
    runner.join(1)
    assert not runner.is_alive()
    renewals_at_shutdown = store.events.count("renew")
    time.sleep(0.02)
    assert store.events.count("renew") == renewals_at_shutdown
    assert not any(
        thread.name == "requirement-handoff-lease-heartbeat"
        for thread in threading.enumerate()
    )
    assert store.events[-1] == "release"
