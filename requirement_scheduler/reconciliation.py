from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from .execution import ExecutionFailure, ExecutionState, FailureCategory

@dataclass(frozen=True)
class ReconcileResult:
    processed: int
    remaining: bool

class RequirementReconciler:
    def __init__(self, store: Any, service: Any): self.store,self.service=store,service
    def reconcile_batch(self, lease, limit: int, now_utc=None) -> ReconcileResult:
        rows=self.store.list_unfinished_handoffs(lease=lease,limit=max(1,min(limit,100)))
        for row in rows:
            try:
                if row.get("remote_job_id") is None:
                    self.service.submit_prepared(row["prepared"],lease); continue
                status=self.service.gateway.inspect(row["handle"])
                self.store.record_reconciliation(row,status,lease)
                if status.state == ExecutionState.COMPLETED:
                    self.service.reconcile_completed(row,lease)
            except ExecutionFailure as exc:
                if exc.category in {FailureCategory.AUTHENTICATION_FAILED,FailureCategory.AUTHORIZATION_FAILED,FailureCategory.SEMANTIC_CONFLICT}:
                    self.store.close_failed_or_recovery_item(lease,row["run_item_id"],"recovery_required",exc.category.value)
                    raise
                deadline=datetime.fromisoformat(row["prepared"].manifest.execution_policy["deadline_at"].replace("Z","+00:00"))
                observed=now_utc or datetime.now(timezone.utc)
                if observed >= deadline or exc.category in {FailureCategory.ARTIFACT_INVALID,FailureCategory.ARTIFACT_PUBLICATION_FAILED,FailureCategory.INTERNAL_CONTRACT_VIOLATION}:
                    self.store.close_failed_or_recovery_item(lease,row["run_item_id"],"recovery_required",exc.category.value)
                    continue
                self.store.mark_reconciling(row["run_item_id"],lease,exc.category.value)
        return ReconcileResult(len(rows),len(rows)==limit)
