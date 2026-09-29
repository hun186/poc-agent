from __future__ import annotations
import os, threading, time, zipfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from api.routers.chat_support import ChatMessage
from api.services.export_word_service import ExportWordService
from api.services.turn_execution import execute_agent_turn
from agent.external_capabilities import (
    requirement_acceptance_scope, split_requirement_e2e_model,
)
from .report_job_store import ReportJobStore

class ReportJobWorker:
    def __init__(self, store: ReportJobStore, reports_root: str | Path, poll_seconds: float = .2):
        self.store, self.root, self.poll_seconds = store, Path(reports_root), poll_seconds
        self.stop_event = threading.Event(); self.thread = None
    def start(self):
        if self.thread and self.thread.is_alive(): return
        from agent.external_capabilities import frozen_plan, resolve_environment_plan
        frozen_plan(resolve_environment_plan)
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
            is_acceptance, effective_model = split_requirement_e2e_model(job.model)
            scope = requirement_acceptance_scope() if is_acceptance else nullcontext()
            with scope:
                payload = SimpleNamespace(model=effective_model, messages=[ChatMessage(role="user", content=job.prompt)], stream=False)
                turn = execute_agent_turn(payload=payload, request=None, session_id=job.session_id)
            content, _ = ExportWordService().build_docx_bytes(turn.output, filename=job.filename)
            with open(temp, "wb") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            if not zipfile.is_zipfile(temp): raise ValueError("Generated report is not a valid DOCX")
            os.replace(temp, final)
            self.store.complete(job.job_id, turn.turn_id, final.name)
        except Exception as exc:
            temp.unlink(missing_ok=True); final.unlink(missing_ok=True)
            self.store.fail(job.job_id, type(exc).__name__[:80], "Report generation failed")
