from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

DEFAULT_MODEL = "SRA-Structured Retrieval Agent"

class BatchValidationError(ValueError): pass


def parse_scheduled_at(value: object) -> datetime | None:
    if value is None or value == "": return None
    if not isinstance(value, str): raise BatchValidationError("scheduled_at must be an ISO-8601 string")
    try: result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc: raise BatchValidationError("scheduled_at must be valid ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise BatchValidationError("scheduled_at must include a UTC offset")
    return result

@dataclass(frozen=True)
class BatchTaskSpec:
    task_id: str
    prompt: str
    filename: str | None = None
    session_id: str | None = None
    model: str = DEFAULT_MODEL
    scheduled_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id.strip(): raise BatchValidationError("task_id must not be blank")
        if not isinstance(self.prompt, str) or not self.prompt.strip(): raise BatchValidationError("prompt must not be blank")
        if self.scheduled_at is not None and (self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None): raise BatchValidationError("scheduled_at must include a UTC offset")
        if not isinstance(self.metadata, dict): raise BatchValidationError("metadata must be an object")
