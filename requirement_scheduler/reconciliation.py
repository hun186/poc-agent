from dataclasses import dataclass
from typing import Any
from .execution import ExecutionState

@dataclass(frozen=True)
class ReconcileResult:
    processed: int
    remaining: bool

class RequirementReconciler:
    def __init__(self, store: Any, service: Any): self.store,self.service=store,service
    def reconcile_batch(self, lease, limit: int, now_utc=None) -> ReconcileResult:
        rows=self.store.list_unfinished_handoffs(lease=lease,limit=max(1,min(limit,100)))
        for row in rows:
            if row.get("remote_job_id") is None: self.service.submit_prepared(row["prepared"],lease); continue
            status=self.service.gateway.inspect(row["handle"])
            self.store.record_reconciliation(row,status,lease)
        return ReconcileResult(len(rows),len(rows)==limit)
