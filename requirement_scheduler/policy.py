from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import RunPolicy


@dataclass(frozen=True)
class Checkpoint:
    last_seen_requirement_version_id: str | None = None
    last_seen_requirement_version_number: int | None = None
    last_successful_requirement_version_id: str | None = None
    last_successful_requirement_version_number: int | None = None

    def __post_init__(self):
        for identity, number in (
            (self.last_seen_requirement_version_id, self.last_seen_requirement_version_number),
            (self.last_successful_requirement_version_id, self.last_successful_requirement_version_number),
        ):
            if (identity is None) != (number is None) or (number is not None and number < 1):
                raise ValueError("checkpoint_version_pair_invalid")


@dataclass(frozen=True)
class SelectionDecision:
    selected: bool
    reason: str
    expired_at_selection: bool = False


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError("timezone_naive")


def evaluate_selection(policy: RunPolicy | str, requirement_version_id: str, requirement_version_number: int, checkpoint: Checkpoint, expires_at: datetime | None, evaluation_time: datetime) -> SelectionDecision:
    _aware(evaluation_time)
    if expires_at is not None:
        _aware(expires_at)
        if expires_at <= evaluation_time:
            return SelectionDecision(False, "expired_at_selection", True)
    policy = RunPolicy(policy)
    if policy is RunPolicy.ALL_ACTIVE: return SelectionDecision(True, "all_active")
    current = (requirement_version_id, requirement_version_number)
    if policy is RunPolicy.NEW_OR_CHANGED:
        successful = (checkpoint.last_successful_requirement_version_id, checkpoint.last_successful_requirement_version_number)
        return SelectionDecision(current != successful, "new_or_changed" if current != successful else "unchanged_since_success")
    seen = (checkpoint.last_seen_requirement_version_id, checkpoint.last_seen_requirement_version_number)
    return SelectionDecision(current != seen, "changed_only" if current != seen else "unchanged_since_seen")
