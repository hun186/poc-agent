"""Fail-closed SQLite checkpoint fence for a *future* SRAF N-round job.

Only durable, count-only state is stored. This is not the ReportJobWorker,
not a resume engine, and not authorization to execute ES, LLM or DOCX.
A process restart marks all in-flight rows INTERRUPTED; re-running requests
requires a new, separately authorized job. Intended for a single host.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any

_JOB_ID = re.compile(r"rpt_[0-9a-f]{32}\Z")
_TABLE = "sraf_nround_checkpoints"
_COLUMNS = (
    "job_id", "state", "phase", "round_number", "completed_rounds",
    "es_calls_this_round", "termination", "lease_hash", "revision",
)
_PHASES = frozenset(("SEARCHING", "ASSESSING", "ASSESSED", "PLANNING", "TERMINAL"))
_AUDIT_FIELDS = frozenset((
    "round", "candidate_sources", "parser_output", "validated_rows",
    "fallback", "verified_in_round", "new_verified", "new_sources",
    "cumulative_verified", "cumulative_sources", "complete",
    "request_wide_attested",
))
_PROGRESS_FIELDS = frozenset((
    "schema", "phase", "round", "es_calls_admitted_this_round",
    "completed_rounds", "termination",
    "ready_for_external_report_generation", "canonical_evidence_history",
    "live_es", "report_job", "checkpoint_resume",
))
_ALLOWED_REASONS = frozenset((
    "NONE", "SUFFICIENT", "CANCELLED", "ROUND_BUDGET_EXHAUSTED",
    "RESOURCE_BUDGET_EXHAUSTED", "SAME_PLAN_SEARCH_INCOMPLETE",
    "REQUEST_LEVEL_ASSESSMENT_REQUIRED", "EVIDENCE_VALIDATION_FAILED",
    "PLANNER_FAILED_CLOSED", "DIMINISHING_RETURNS", "NO_EXPECTED_GAIN",
    "USER_KEYWORDS_LOCKED", "NO_NEW_QUERY_PLAN", "DATE_PARSE_SUSPECTED",
    "INVALID_CONTEXT", "INCONSISTENT_ROUND_HISTORY", "PLANNER_STOPPED",
    "UNTRUSTED_NEXT_ROUND_SCOPE", "LATE_BUDGET_EXHAUSTED",
    "STALE_ROUND_HISTORY", "NO_NEW_STRATEGY",
))


def _validated_counts(progress: dict[str, Any]) -> tuple[str, int, int, int, str]:
    """Accept only the existing coordinator's fixed, private-data-free shape."""
    if type(progress) is not dict or set(progress) != _PROGRESS_FIELDS:
        raise ValueError("untrusted_nround_progress")
    phase, reason = progress["phase"], progress["termination"]
    round_number, completed = progress["round"], progress["completed_rounds"]
    es_calls = progress["es_calls_admitted_this_round"]
    if (progress["schema"] != "sraf_nround_coordinator_progress_v1"
            or type(phase) is not str or phase not in _PHASES
            or type(reason) is not str or reason not in _ALLOWED_REASONS
            or type(round_number) is not int or not 0 <= round_number <= 8
            or type(completed) is not int or not 0 <= completed <= round_number
            or type(es_calls) is not int or not 0 <= es_calls <= 1000
            or type(progress["ready_for_external_report_generation"]) is not bool
            or progress["live_es"] != "NOT_EXECUTED_BY_COORDINATOR"
            or progress["report_job"] != "NOT_INTEGRATED"
            or progress["checkpoint_resume"] != "NOT_IMPLEMENTED"
            or (phase == "TERMINAL") != (reason != "NONE")):
        raise ValueError("untrusted_nround_progress")
    # The coordinator legitimately terminates at round zero when cancelled
    # before start or denied its very first budget admission. Never pretend
    # that this terminal state represents completed Evidence or a report.
    if round_number == 0 and (
            phase != "TERMINAL"
            or reason not in ("CANCELLED", "RESOURCE_BUDGET_EXHAUSTED")
            or completed != 0 or es_calls != 0
            or progress["ready_for_external_report_generation"]):
        raise ValueError("untrusted_nround_progress")
    audits = progress["canonical_evidence_history"]
    if type(audits) is not tuple or len(audits) != completed:
        raise ValueError("untrusted_nround_audit")
    previous_verified = previous_sources = 0
    for expected_round, audit in enumerate(audits, 1):
        if type(audit) is not dict or set(audit) != _AUDIT_FIELDS:
            raise ValueError("untrusted_nround_audit")
        if any(type(v) is not bool for k, v in audit.items()
               if k in ("complete", "request_wide_attested")):
            raise ValueError("untrusted_nround_audit")
        if any(type(v) is not int or not 0 <= v <= 1_000_000
               for k, v in audit.items()
               if k not in ("complete", "request_wide_attested")):
            raise ValueError("untrusted_nround_audit")
        if (audit["round"] != expected_round
                or audit["cumulative_verified"] < previous_verified
                or audit["cumulative_sources"] < previous_sources
                or audit["cumulative_sources"] > audit["cumulative_verified"]
                or audit["new_verified"] != audit["cumulative_verified"] - previous_verified
                or audit["new_sources"] != audit["cumulative_sources"] - previous_sources):
            raise ValueError("untrusted_nround_audit")
        previous_verified = audit["cumulative_verified"]
        previous_sources = audit["cumulative_sources"]
    if phase == "ASSESSED" and completed != round_number:
        raise ValueError("untrusted_nround_progress")
    if phase == "SEARCHING" and completed != round_number - 1:
        raise ValueError("untrusted_nround_progress")
    if phase == "PLANNING" and completed != round_number:
        raise ValueError("untrusted_nround_progress")
    if phase == "ASSESSING" and completed != round_number - 1:
        raise ValueError("untrusted_nround_progress")
    # Caller readiness is deliberately NOT trusted or persisted.
    return phase, round_number, completed, es_calls, reason


class NroundCheckpointStore:
    """Durable sidecar table; does not migrate or modify report_jobs."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def _write(self, fn):
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                result = fn(con)
                con.commit()
                return result
            except BaseException:
                con.rollback()
                raise

    def initialize(self) -> None:
        def init(con):
            found = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (_TABLE,),
            ).fetchone()
            if not found:
                con.execute(f"""CREATE TABLE {_TABLE} (
                    job_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK(state IN (
                        'QUEUED','RUNNING','RETRIEVAL_STOPPED',
                        'INTERRUPTED','FAILED','CANCELLED')),
                    phase TEXT NOT NULL,
                    round_number INTEGER NOT NULL DEFAULT 0,
                    completed_rounds INTEGER NOT NULL DEFAULT 0,
                    es_calls_this_round INTEGER NOT NULL DEFAULT 0,
                    termination TEXT NOT NULL DEFAULT 'NONE',
                    lease_hash TEXT,
                    revision INTEGER NOT NULL DEFAULT 0
                )""")
            actual = tuple(row["name"] for row in con.execute(
                f"PRAGMA table_info({_TABLE})"))
            if actual != _COLUMNS:
                raise RuntimeError("incompatible_nround_checkpoint_schema")
        self._write(init)

    @staticmethod
    def _valid_id(job_id: str) -> bool:
        return type(job_id) is str and _JOB_ID.fullmatch(job_id) is not None

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create(self, job_id: str) -> bool:
        if not self._valid_id(job_id):
            raise ValueError("invalid_report_job_id")
        def op(con):
            cur = con.execute(
                f"INSERT OR IGNORE INTO {_TABLE} (job_id,state,phase) VALUES (?,?,?)",
                (job_id, "QUEUED", "CREATED"),
            )
            return cur.rowcount == 1
        return self._write(op)

    def claim(self, job_id: str) -> str | None:
        """Once-only claim; store only SHA256(token), never the bearer secret."""
        if not self._valid_id(job_id):
            return None
        token = secrets.token_urlsafe(32)
        def op(con):
            cur = con.execute(
                f"""UPDATE {_TABLE}
                    SET state='RUNNING', phase='SEARCHING', lease_hash=?,
                        revision=revision+1
                    WHERE job_id=? AND state='QUEUED'""",
                (self._hash(token), job_id),
            )
            return token if cur.rowcount == 1 else None
        return self._write(op)

    def record_progress(self, job_id: str, lease_token: str,
                        progress: dict[str, Any]) -> bool:
        phase, number, completed, es_calls, reason = _validated_counts(progress)
        if (not self._valid_id(job_id) or type(lease_token) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", lease_token) is None):
            return False
        new_state = "RETRIEVAL_STOPPED" if phase == "TERMINAL" else "RUNNING"
        def op(con):
            row = con.execute(
                f"SELECT * FROM {_TABLE} WHERE job_id=? AND state='RUNNING'",
                (job_id,),
            ).fetchone()
            if row is None or row["lease_hash"] != self._hash(lease_token):
                return False
            old_round = row["round_number"]
            if (number < old_round or number > old_round + 1
                    or completed < row["completed_rounds"]
                    or completed > row["completed_rounds"] + 1
                    or (number == old_round
                        and es_calls < row["es_calls_this_round"])
                    or (number > old_round
                        and completed < number - 1)):
                return False
            con.execute(
                f"""UPDATE {_TABLE}
                    SET state=?,phase=?,round_number=?,completed_rounds=?,
                        es_calls_this_round=?,termination=?,revision=revision+1,
                        lease_hash=CASE WHEN ?='RETRIEVAL_STOPPED' THEN NULL ELSE lease_hash END
                    WHERE job_id=?""",
                (new_state, phase, number, completed, es_calls, reason,
                 new_state, job_id),
            )
            return True
        return self._write(op)

    def interrupt_running(self) -> int:
        """Startup recovery: no automatic replay, never fabricate completion."""
        def op(con):
            cur = con.execute(
                f"""UPDATE {_TABLE} SET state='INTERRUPTED', lease_hash=NULL,
                    revision=revision+1 WHERE state='RUNNING'""",
            )
            return cur.rowcount
        return self._write(op)

    def cancel_queued(self, job_id: str) -> bool:
        if not self._valid_id(job_id):
            return False
        return self._write(lambda con: con.execute(
            f"""UPDATE {_TABLE} SET state='CANCELLED', revision=revision+1
                WHERE job_id=? AND state='QUEUED'""",
            (job_id,),
        ).rowcount == 1)

    def get_public(self, job_id: str) -> dict[str, Any] | None:
        """Count-only; no owner data, prompt, identifiers of evidence or token."""
        if not self._valid_id(job_id):
            return None
        with closing(self._connect()) as con:
            row = con.execute(
                f"""SELECT state,phase,round_number,completed_rounds,
                    es_calls_this_round,termination,revision
                    FROM {_TABLE} WHERE job_id=?""", (job_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.update({
            "schema": "sraf_nround_durable_fence_v1",
            "checkpoint_resume_supported": False,
            "report_generation_authorized": False,
        })
        return result
