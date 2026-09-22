from __future__ import annotations

import threading
import time
from typing import Any


_RECOVERABLE_COORDINATION_ERRORS = frozenset({"lease_lost", "lease_unavailable"})


def _is_recoverable_coordination_error(exc: BaseException) -> bool:
    """Recognize only the store's explicit lease-contention/loss conditions."""
    return (
        isinstance(exc, RuntimeError)
        and len(exc.args) == 1
        and exc.args[0] in _RECOVERABLE_COORDINATION_ERRORS
    )


class RequirementHandoffCoordinator:
    def __init__(
        self,
        store: Any,
        reconciler: Any,
        service: Any,
        config: Any,
        *,
        owner_id: str,
        sleep=time.sleep,
    ):
        self.store, self.reconciler, self.service, self.config = (
            store,
            reconciler,
            service,
            config,
        )
        self.owner_id, self.sleep = owner_id, sleep
        self.lease = None
        self._lease_lock = threading.Lock()

    def _current_lease(self):
        with self._lease_lock:
            return self.lease

    def _replace_lease(self, lease) -> None:
        with self._lease_lock:
            self.lease = lease

    def _ensure_lease(self):
        lease = self._current_lease()
        if lease is None:
            lease = self.store.acquire_lease(
                self.owner_id, self.config.lease_duration
            )
        else:
            lease = self.store.renew_lease(lease, self.config.lease_duration)
        self._replace_lease(lease)
        return lease

    @staticmethod
    def _authority_identity(lease):
        return tuple(
            getattr(lease, field, None)
            for field in (
                "control_domain",
                "owner_id",
                "lease_token",
                "token",
                "fencing_generation",
                "generation",
            )
        )

    def _assert_current_authority(self, lease) -> None:
        current = self._current_lease()
        if current is None or self._authority_identity(current) != self._authority_identity(lease):
            raise RuntimeError("lease_lost")

    def _do_authoritative_work(self, lease, authority_check=None):
        authority_check = authority_check or (lambda: self._assert_current_authority(lease))
        authority_check()
        result = self.reconciler.reconcile_batch(lease, self.config.batch_size)
        authority_check()
        if result.remaining:
            return result
        prepared = self.service.prepare_next(lease)
        authority_check()
        if prepared is not None:
            self.service.submit_prepared(prepared, lease)
            authority_check()
        return result

    def run_once(self):
        """Run one cycle without owning a heartbeat lifecycle (primarily a test seam)."""
        return self._do_authoritative_work(self._ensure_lease())

    def _run_with_heartbeat(self, lease, stop_event: threading.Event):
        heartbeat_stop = threading.Event()
        heartbeat_error: list[BaseException] = []

        def heartbeat() -> None:
            while not heartbeat_stop.wait(self.config.heartbeat_interval):
                if stop_event.is_set():
                    return
                current = self._current_lease()
                if current is None:
                    return
                try:
                    renewed = self.store.renew_lease(
                        current, self.config.lease_duration
                    )
                except BaseException as exc:
                    heartbeat_error.append(exc)
                    if _is_recoverable_coordination_error(exc):
                        self._replace_lease(None)
                    return
                self._replace_lease(renewed)

        thread = threading.Thread(
            target=heartbeat,
            name="requirement-handoff-lease-heartbeat",
            daemon=False,
        )
        thread.start()
        work_error = None
        try:
            def authority_check() -> None:
                if heartbeat_error:
                    raise heartbeat_error[0]
                self._assert_current_authority(lease)

            result = self._do_authoritative_work(lease, authority_check)
        except BaseException as exc:
            work_error = exc
        finally:
            heartbeat_stop.set()
            thread.join()
        if heartbeat_error:
            raise heartbeat_error[0]
        if work_error is not None:
            raise work_error
        return result

    def run(self, stop_event: threading.Event) -> None:
        try:
            self.store.initialize()
            while not stop_event.is_set():
                try:
                    lease = self._ensure_lease()
                    if stop_event.is_set():
                        break
                    self._run_with_heartbeat(lease, stop_event)
                except RuntimeError as exc:
                    if not _is_recoverable_coordination_error(exc):
                        raise
                    self._replace_lease(None)
                stop_event.wait(self.config.poll_interval)
        finally:
            lease = self._current_lease()
            if lease is not None:
                self.store.release_lease(lease)
                self._replace_lease(None)
