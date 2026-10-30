from __future__ import annotations
import os, threading, time, zipfile
from contextlib import nullcontext

import requests
from pathlib import Path
from types import SimpleNamespace
from api.routers.chat_support import ChatMessage
from api.services.export_word_service import ExportWordService
from api.services.turn_execution import execute_agent_turn
from .report_job_store import ReportJobStore

def _failure_category(exc: Exception) -> str:
    """Best-effort classified *actual* failure, never infer a timeout by duration.

    Inspect only exception objects, not exception string or provider response.
    """
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending and len(seen) < 12:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, (TimeoutError, requests.exceptions.Timeout)):
            return "timeout"
        if isinstance(item, requests.exceptions.HTTPError):
            response = item.response
            status = getattr(response, "status_code", None)
            if status == 429:
                return "rate_limited"
            if status == 503:
                return "provider_unavailable"
        cls = type(item)
        if cls.__module__.startswith("litellm."):
            if cls.__name__ in ("Timeout", "APITimeoutError"):
                return "timeout"
            if cls.__name__ == "RateLimitError":
                return "rate_limited"
            if cls.__name__ == "ServiceUnavailableError":
                return "provider_unavailable"
        for other in (item.__cause__, item.__context__, *item.args[:4]):
            if isinstance(other, BaseException) and id(other) not in seen:
                pending.append(other)
    return "execution_error"


class ReportJobWorker:
    def __init__(self, store: ReportJobStore, reports_root: str | Path, poll_seconds: float = .2):
        self.store, self.root, self.poll_seconds = store, Path(reports_root), poll_seconds
        self.stop_event = threading.Event(); self.thread = None
    def start(self):
        if self.thread and self.thread.is_alive(): return
        # Production jobs must not require a live E2E capability probe.
        self.root.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self.run, name="report-job-worker", daemon=True); self.thread.start()
    def stop(self, timeout=5):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout)
    def run(self):
        while not self.stop_event.is_set():
            job = self.store.claim_next()
            if not job: self.stop_event.wait(self.poll_seconds); continue
            self.execute(job)
    def execute(self, job):
        self.root.mkdir(parents=True, exist_ok=True)
        final = self.root / f"{job.job_id}.docx"
        temp = self.root / f".{job.job_id}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            from agent.external_capabilities import (
                CapabilityError, frozen_plan, requirement_acceptance_scope,
                verified_requirement_e2e_job_model,
            )
            is_acceptance, effective_model = verified_requirement_e2e_job_model(job)
            admitted_plan = frozen_plan() if is_acceptance else None
            if is_acceptance and admitted_plan is None:
                raise CapabilityError("external_capability_plan_unresolved")
            # Carry the exact plan admitted before the operator's next
            # revalidation into this job's whole Agent/ES/Word execution.
            scope = (requirement_acceptance_scope(admitted_plan)
                     if is_acceptance else nullcontext())
            with scope:
                payload = SimpleNamespace(model=effective_model, messages=[ChatMessage(role="user", content=job.prompt)], stream=False)
                turn = execute_agent_turn(payload=payload, request=None, session_id=job.session_id)
            if not self.store.update_phase(job.job_id, "docx_export"):
                raise RuntimeError("report_job_phase_unavailable")
            content, _ = ExportWordService().build_docx_bytes(turn.output, filename=job.filename)
            if not self.store.update_phase(job.job_id, "finalizing"):
                raise RuntimeError("report_job_phase_unavailable")
            with open(temp, "wb") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            if not zipfile.is_zipfile(temp): raise ValueError("Generated report is not a valid DOCX")
            os.replace(temp, final)
            self.store.complete(job.job_id, turn.turn_id, final.name)
        except Exception as exc:
            temp.unlink(missing_ok=True); final.unlink(missing_ok=True)
            self.store.fail(
                job.job_id, type(exc).__name__[:80],
                "Report generation failed", failure_category=_failure_category(exc),
            )
