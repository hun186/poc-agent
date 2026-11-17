"""Fail-closed SQLite checkpoint fence for a *future* SRAF N-round job.

Only durable, count-only state is stored. This is not the ReportJobWorker,
not a resume engine, and not authorization to execute ES, LLM or DOCX.
A process restart marks all in-flight rows INTERRUPTED; re-running requests
requires a new, separately authorized job. Intended for a single host.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any

from api.services.report_job_store import ReportJob, ReportJobStore

_JOB_ID = re.compile(r"rpt_[0-9a-f]{32}\Z")
_TABLE = "sraf_nround_checkpoints"
_COLUMNS = (
    "job_id", "state", "phase", "round_number", "completed_rounds",
    "es_calls_this_round", "termination", "lease_hash", "revision",
)
_EXPECTED_COLUMN_META = (
    # name, declared SQLite type, NOT NULL flag, DEFAULT expression, PK ordinal
    ("job_id", "TEXT", 0, None, 1),
    ("state", "TEXT", 1, None, 0),
    ("phase", "TEXT", 1, None, 0),
    ("round_number", "INTEGER", 1, "0", 0),
    ("completed_rounds", "INTEGER", 1, "0", 0),
    ("es_calls_this_round", "INTEGER", 1, "0", 0),
    ("termination", "TEXT", 1, "'NONE'", 0),
    ("lease_hash", "TEXT", 0, None, 0),
    ("revision", "INTEGER", 1, "0", 0),
)
_PHASES = frozenset(("SEARCHING", "ASSESSING", "ASSESSED", "PLANNING", "TERMINAL"))
# Per-round phase order; crossing into a *new* round restarts at SEARCHING.
_PHASE_ORDER = {phase: index for index, phase in enumerate(
    ("SEARCHING", "ASSESSING", "ASSESSED", "PLANNING", "TERMINAL")
)}
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
    "UNTRACKED_QUERY_ADMISSION",
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
                or audit["new_sources"] != audit["cumulative_sources"] - previous_sources
                or audit["new_sources"] > audit["new_verified"]):
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
            info = tuple(
                (row["name"], row["type"].upper(), row["notnull"],
                 row["dflt_value"], row["pk"])
                for row in con.execute(f"PRAGMA table_info({_TABLE})")
            )
            # Names alone are insufficient: an externally created same-shape
            # table without a PRIMARY KEY admits duplicate job IDs and makes
            # two-worker claim fencing unsafe. Refuse all schema variations.
            if info != _EXPECTED_COLUMN_META:
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

    @staticmethod
    def _running_report_job_matches(
        con: sqlite3.Connection, claimed_job: ReportJob,
    ) -> bool:
        """Read the existing Report Job claim in the SAME SQLite transaction.

        Compare owner, original prompt and all immutable admission fields,
        not just an untrusted job_id or status flag. No private field leaves
        this method. This is a single-machine, same-file SQLite authority
        check, NOT a substitute for actual owner index RBAC.
        """
        # Structural/index/version validation must happen inside the same
        # transaction BEFORE either sidecar claim or progress mutation.
        # A lookalike report_jobs table is never acceptable authority.
        ReportJobStore._validate_v2(con)
        if (type(claimed_job) is not ReportJob
                or claimed_job.status != "running"
                or claimed_job.phase != "agent_execution"
                or type(claimed_job.owner_kind) is not str
                or not claimed_job.owner_kind.strip()
                or type(claimed_job.owner_id) is not str
                or not claimed_job.owner_id.strip()
                or type(claimed_job.session_id) is not str
                or not claimed_job.session_id.strip()
                or type(claimed_job.started_at) is not str
                or not claimed_job.started_at):
            return False
        row = con.execute(
            """SELECT job_id,status,phase,prompt,filename,session_id,model,
                      options_json,metadata_json,idempotency_key,request_hash,
                      owner_kind,owner_id,created_at,started_at
               FROM report_jobs WHERE job_id=?""",
            (claimed_job.job_id,),
        ).fetchone()
        if row is None:
            return False
        fields = (
            "job_id", "prompt", "filename", "session_id", "model",
            "idempotency_key", "request_hash", "owner_kind", "owner_id",
            "created_at", "started_at",
        )
        return (
            row["status"] == "running"
            and row["phase"] == "agent_execution"
            and all(row[name] == getattr(claimed_job, name) for name in fields)
            and json.loads(row["options_json"]) == claimed_job.options
            and json.loads(row["metadata_json"]) == claimed_job.metadata
        )

    def _same_report_job_database(self, store: ReportJobStore) -> bool:
        return (
            type(store) is ReportJobStore
            and self.db_path.resolve() == store.db_path.resolve()
        )

    def claim_for_running_report_job(
        self, report_store: ReportJobStore, claimed_job: ReportJob,
    ) -> str | None:
        """Claim the queued sidecar ONLY if the actual Report Job is running.

        SELECT of canonical report_jobs and sidecar QUEUED→RUNNING CAS occur
        in ONE BEGIN IMMEDIATE SQLite transaction. No token is issued for a
        queued, interrupted, failed, owner-replaced or different-DB Job.
        Existing unbound claim() remains for historic isolated tests;
        production Worker must use this stricter method.
        """
        try:
            # Path.resolve(), mkdir/open and schema checks are all inside
            # the sanitized boundary; never expose private DB path details.
            if (not self._same_report_job_database(report_store)
                    or type(claimed_job) is not ReportJob
                    or not self._valid_id(claimed_job.job_id)):
                return None
            token = secrets.token_urlsafe(32)

            def op(con):
                if not self._running_report_job_matches(con, claimed_job):
                    return None
                cur = con.execute(
                    f"""UPDATE {_TABLE}
                        SET state='RUNNING', phase='SEARCHING', lease_hash=?,
                            revision=revision+1
                        WHERE job_id=? AND state='QUEUED'""",
                    (self._hash(token), claimed_job.job_id),
                )
                return token if cur.rowcount == 1 else None

            return self._write(op)
        except Exception:
            raise ValueError("nround_report_job_claim_unverified") from None

    def record_progress_for_running_report_job(
        self, report_store: ReportJobStore, claimed_job: ReportJob,
        lease_token: str, progress: dict[str, Any],
    ) -> bool:
        """Persist count-only N-round progress iff the same Job remains running.

        This checks the ReportJob identity AND hashed sidecar lease in the
        same write transaction. It never creates a Word and never marks the
        ReportJob completed or eligible for download.
        """
        try:
            phase, number, completed, es_calls, reason = _validated_counts(progress)
            if (not self._same_report_job_database(report_store)
                    or type(claimed_job) is not ReportJob
                    or not self._valid_id(claimed_job.job_id)
                    or type(lease_token) is not str
                    or re.fullmatch(r"[A-Za-z0-9_-]{43}", lease_token) is None):
                return False

            def op(con):
                if not self._running_report_job_matches(con, claimed_job):
                    return False
                return self._record_progress_locked(
                    con, claimed_job.job_id, lease_token,
                    phase, number, completed, es_calls, reason,
                )

            return self._write(op)
        except Exception:
            raise ValueError("nround_report_job_progress_unverified") from None

    def record_progress(self, job_id: str, lease_token: str,
                        progress: dict[str, Any]) -> bool:
        phase, number, completed, es_calls, reason = _validated_counts(progress)
        if (not self._valid_id(job_id) or type(lease_token) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", lease_token) is None):
            return False
        return self._write(lambda con: self._record_progress_locked(
            con, job_id, lease_token, phase, number, completed, es_calls, reason,
        ))

    def _record_progress_locked(
        self, con: sqlite3.Connection, job_id: str, lease_token: str,
        phase: str, number: int, completed: int, es_calls: int, reason: str,
    ) -> bool:
        """Shared monotonic lease-CAS, ALWAYS within caller's transaction."""
        row = con.execute(
            f"SELECT * FROM {_TABLE} WHERE job_id=? AND state='RUNNING'",
            (job_id,),
        ).fetchone()
        if row is None or row["lease_hash"] != self._hash(lease_token):
            return False
        old_round = row["round_number"]
        if (number == old_round
                and _PHASE_ORDER[phase] < _PHASE_ORDER[row["phase"]]):
            return False
        if (number < old_round or number > old_round + 1
                or completed < row["completed_rounds"]
                or completed > row["completed_rounds"] + 1
                or (number == old_round
                    and es_calls < row["es_calls_this_round"])
                or (number > old_round
                    and completed < number - 1)):
            return False
        new_state = "RETRIEVAL_STOPPED" if phase == "TERMINAL" else "RUNNING"
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
