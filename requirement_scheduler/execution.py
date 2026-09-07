from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Any, Protocol


class ExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RECONCILING = "reconciling"
    RECOVERY_REQUIRED = "recovery_required"
    COMPLETED = "completed"
    FAILED = "failed"


class FailureCategory(StrEnum):
    TRANSPORT_AMBIGUOUS = "transport_ambiguous"
    REMOTE_UNAVAILABLE = "remote_unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTHORIZATION_FAILED = "authorization_failed"
    SEMANTIC_CONFLICT = "semantic_conflict"
    REMOTE_EXECUTION_FAILED = "remote_execution_failed"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    ARTIFACT_INVALID = "artifact_invalid"
    ARTIFACT_PUBLICATION_FAILED = "artifact_publication_failed"
    RECONCILIATION_UNKNOWN = "reconciliation_unknown"
    PERSISTENCE_FAILED = "persistence_failed"
    INTERNAL_CONTRACT_VIOLATION = "internal_contract_violation"


@dataclass(frozen=True)
class ExecutionFailure(Exception):
    category: FailureCategory
    safe_message: str
    retryable_operation: bool = False

    def __str__(self) -> str:
        return self.safe_message


@dataclass(frozen=True)
class ExecutionHandle:
    submission_id: str
    remote_job_id: str


@dataclass(frozen=True)
class ExecutionStatus:
    state: ExecutionState
    native_observed_at: datetime
    safe_error: ExecutionFailure | None = None


@dataclass(frozen=True)
class ExecutionManifest:
    source_identity: dict[str, Any]
    execution_input: dict[str, Any]
    execution_policy: dict[str, Any]
    contract_version: int = 1
    workflow_id: str = "report_v1"

    def as_dict(self) -> dict[str, Any]:
        return {"contract_version": self.contract_version, "workflow_id": self.workflow_id,
                "source_identity": self.source_identity, "execution_input": self.execution_input,
                "execution_policy": self.execution_policy}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


class ExecutionGateway(Protocol):
    def submit(self, manifest: ExecutionManifest, *, idempotency_key: str) -> ExecutionHandle: ...
    def inspect(self, handle: ExecutionHandle) -> ExecutionStatus: ...
    def download_artifact(self, handle: ExecutionHandle) -> bytes: ...


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def submission_id(run_item_id: str) -> str:
    digest = hashlib.sha256(("requirement-handoff-v1\0" + run_item_id).encode()).hexdigest()
    return "rhsub_" + digest[:48]


def semantic_fingerprint(manifest: ExecutionManifest | str) -> str:
    encoded = manifest if isinstance(manifest, str) else manifest.canonical_json()
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_seconds(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("deadline_timezone_naive")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_execution_manifest(source: dict[str, Any]) -> ExecutionManifest:
    required = ("schedule_id", "schedule_version_id", "batch_run_id", "run_item_id", "snapshot_id",
                "requirement_id", "requirement_version_id", "requirement_version_number", "resolved_prompt",
                "resolved_model", "deadline_at")
    if any(key not in source for key in required):
        raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "materialized_source_incomplete")
    sid = submission_id(str(source["run_item_id"]))
    number = source["requirement_version_number"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "requirement_version_invalid")
    safe_id = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(source["requirement_id"]))[:120]
    logical = source.get("logical_filename") or f"requirement-{safe_id}-v{number}.docx"
    return ExecutionManifest(
        source_identity={key: source[key] for key in required[:8]},
        execution_input={"resolved_prompt": source["resolved_prompt"], "resolved_model": source["resolved_model"],
                         "output_contract": "docx_v1", "logical_filename": logical},
        execution_policy={"deadline_at": _utc_seconds(source["deadline_at"]),
                          "legacy_session_id": "requirement-handoff:" + sid},
    )
