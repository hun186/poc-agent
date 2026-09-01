from __future__ import annotations
import hashlib, json, re, uuid
from typing import Any
from .report_job_store import ReportJobStore

DEFAULT_REPORT_MODEL = "SRA-Structured Retrieval Agent"

def sanitize_filename(value: str | None) -> str | None:
    if not value:
        return None
    name = re.sub(r"[\\/\x00-\x1f]+", "_", value).strip(" ._")[:180]
    if not name:
        name = "report.docx"
    if not name.lower().endswith(".docx"):
        name += ".docx"
    return name

def normalized_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def create_job(store: ReportJobStore, *, prompt: str, filename: str | None, session_id: str | None,
               model: str, options: dict, metadata: dict, idempotency_key: str | None):
    logical = sanitize_filename(filename)
    session = session_id.strip() if session_id and session_id.strip() else f"report-job-{uuid.uuid4().hex}"
    normalized = {"prompt": prompt.strip(), "filename": logical, "session_id": session_id.strip() if session_id and session_id.strip() else None,
                  "model": model, "options": options, "metadata": metadata}
    return store.create(job_id=f"rpt_{uuid.uuid4().hex}", request_hash=normalized_hash(normalized),
                        idempotency_key=idempotency_key.strip() if idempotency_key else None,
                        prompt=normalized["prompt"], filename=logical, session_id=session, model=model,
                        options=options, metadata=metadata)
