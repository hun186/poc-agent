from __future__ import annotations
import threading, time
from typing import Any

class RequirementHandoffCoordinator:
    def __init__(self, store: Any, reconciler: Any, service: Any, config: Any, *, owner_id: str, sleep=time.sleep):
        self.store,self.reconciler,self.service,self.config=store,reconciler,service,config
        self.owner_id,self.sleep=owner_id,sleep; self.lease=None
    def run_once(self):
        if self.lease is None: self.lease=self.store.acquire_lease(self.owner_id,self.config.lease_duration)
        else: self.lease=self.store.renew_lease(self.lease,self.config.lease_duration)
        result=self.reconciler.reconcile_batch(self.lease,self.config.batch_size)
        if result.remaining: return result
        prepared=self.service.prepare_next(self.lease)
        if prepared is not None: self.service.submit_prepared(prepared,self.lease)
        return result
    def run(self, stop_event: threading.Event) -> None:
        try:
            self.store.initialize()
            while not stop_event.is_set():
                self.run_once(); stop_event.wait(self.config.poll_interval)
        finally:
            if self.lease is not None: self.store.release_lease(self.lease)
