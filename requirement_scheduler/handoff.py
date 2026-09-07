from __future__ import annotations
from dataclasses import dataclass
import hmac
from pathlib import Path
from typing import Any

from .artifacts import output_root_fingerprint
from .execution import ExecutionFailure, ExecutionHandle, ExecutionManifest, FailureCategory, semantic_fingerprint, submission_id
from .lease import LeaseProof

@dataclass(frozen=True)
class PreparedHandoff:
    run_item_id: str
    submission_id: str
    manifest: ExecutionManifest
    semantic_manifest_json: str
    semantic_fingerprint: str
    legacy_session_id: str

def prepared_handoff(run_item_id: str, manifest: ExecutionManifest) -> PreparedHandoff:
    sid=submission_id(run_item_id); encoded=manifest.canonical_json()
    expected="requirement-handoff:"+sid
    if manifest.execution_policy.get("legacy_session_id") != expected: raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION,"legacy_session_mismatch")
    return PreparedHandoff(run_item_id,sid,manifest,encoded,semantic_fingerprint(encoded),expected)

def verify_prepared(stored: PreparedHandoff, candidate: PreparedHandoff) -> None:
    fields=("run_item_id","submission_id","semantic_manifest_json","semantic_fingerprint","legacy_session_id")
    if any(not hmac.compare_digest(str(getattr(stored,k)).encode(),str(getattr(candidate,k)).encode()) for k in fields):
        raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION,"submission_semantic_drift")

def checkpoint_outcome(stored_number: int | None, stored_version_id: str | None,
                       incoming_number: int, incoming_version_id: str) -> str:
    """Return advance/noop and fail closed only on equal-number identity ambiguity."""
    if stored_number is None: return "advance"
    if incoming_number > stored_number: return "advance"
    if incoming_number < stored_number: return "noop"
    if stored_version_id == incoming_version_id: return "noop"
    raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION,"checkpoint_identity_inconsistent")

class RequirementHandoffService:
    """Coordinates SQL intent and HTTP/filesystem effects without overlapping them."""
    def __init__(self, store: Any, gateway: Any, output_root: Path): self.store,self.gateway,self.output_root=store,gateway,Path(output_root)
    def prepare_next(self, lease: LeaseProof, now_utc=None):
        return self.store.prepare_next_handoff(lease=lease, now_utc=now_utc,
            output_root_fingerprint=output_root_fingerprint(self.output_root))
    def submit_prepared(self, prepared: PreparedHandoff, lease: LeaseProof) -> ExecutionHandle:
        try: handle=self.gateway.submit(prepared.manifest,idempotency_key=prepared.submission_id)
        except ExecutionFailure as exc:
            if exc.category == FailureCategory.TRANSPORT_AMBIGUOUS: self.store.mark_reconciling(prepared.run_item_id,lease,exc.category.value)
            raise
        self.store.acknowledge_submission(prepared,handle,lease)
        return handle
