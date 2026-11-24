"""Internal owner-scoped, read-only N-round checkpoint projection.

Used by the owner-scoped progress route; NOT a JWT/API-key authenticator
or report/Word capability. The caller must provide a *verified server-side* owner principal.
No source Evidence, original prompt, IDs or credentials leave this module.
"""
from __future__ import annotations

from contextlib import closing
import sqlite3

from api.services.report_job_store import ReportJobStore
from agent.adaptive_retrieval.job_checkpoint import (
    NroundCheckpointStore, _TABLE, _EXPECTED_COLUMN_META,
    _ALLOWED_REASONS,
)


class NroundOwnedProgressError(ValueError):
    """Fixed sanitized storage-error only; never print owner or DB paths."""


_REPORT_STATUSES = frozenset((
    "queued", "running", "completed", "failed", "interrupted", "cancelled",
))
_CHECKPOINT_STATUSES = frozenset((
    "QUEUED", "RUNNING", "RETRIEVAL_STOPPED", "INTERRUPTED", "FAILED", "CANCELLED",
))
_PHASES = frozenset((
    "CREATED", "SEARCHING", "ASSESSING", "ASSESSED", "PLANNING", "TERMINAL",
))




def get_owned_nround_progress(
    *, report_store: ReportJobStore, checkpoint_store: NroundCheckpointStore,
    job_id: str, owner_kind: str, owner_id: str,
) -> dict[str, str | int | bool] | None:
    """Read a single trusted principal's N-round *counts*, or return None.

    Unauthorized, unknown, unowned legacy rows and jobs without a checkpoint
    are intentionally indistinguishable. The owner parameters are NOT
    authenticated here: API handlers must derive them from actual
    server-side principal/REPORT_JOB_READ policy, never query/body input.
    """
    try:
        if (type(report_store) is not ReportJobStore
                or type(checkpoint_store) is not NroundCheckpointStore
                or not checkpoint_store._same_report_job_database(report_store)
                or not checkpoint_store._valid_id(job_id)
                or type(owner_kind) is not str
                or not 1 <= len(owner_kind) <= 128
                or owner_kind != owner_kind.strip()
                or type(owner_id) is not str
                or not 1 <= len(owner_id) <= 256
                or owner_id != owner_id.strip()):
            return None

        # mode=ro prevents creating/changing the canonical *database*, while
        # query_only=ON disallows SQL writes. SQLite's WAL implementation MAY
        # create/refresh -wal/-shm auxiliary files for concurrent readers.
        # That is normal engine-managed metadata, not a durable Job write.
        # Never use immutable=1 for active WAL: it can silently omit
        # uncheckpointed owner revocation or progress.
        uri = checkpoint_store.db_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            con.execute("BEGIN")
            ReportJobStore._validate_v2(con)
            table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (_TABLE,),
            ).fetchone()
            if table is None:
                return None
            meta = tuple(
                (row["name"], row["type"].upper(), row["notnull"],
                 row["dflt_value"], row["pk"])
                for row in con.execute(f"PRAGMA table_info({_TABLE})")
            )
            if meta != _EXPECTED_COLUMN_META:
                raise NroundOwnedProgressError("nround_owned_progress_unverified")
            report = con.execute(
                "SELECT status FROM report_jobs "
                "WHERE job_id=? AND owner_kind=? AND owner_id=?",
                (job_id, owner_kind, owner_id),
            ).fetchone()
            if report is None:
                return None
            if report["status"] not in _REPORT_STATUSES:
                raise NroundOwnedProgressError("nround_owned_progress_unverified")
            checkpoint = con.execute(
                f"""SELECT state,phase,round_number,completed_rounds,
                           es_calls_this_round,termination,revision
                    FROM {_TABLE} WHERE job_id=?""", (job_id,),
            ).fetchone()
            if checkpoint is None:
                return None
            result = dict(checkpoint)
            if (result["state"] not in _CHECKPOINT_STATUSES
                    or result["phase"] not in _PHASES
                    or result["termination"] not in _ALLOWED_REASONS
                    or any(type(result[field]) is not int
                           for field in ("round_number", "completed_rounds",
                                         "es_calls_this_round", "revision"))
                    or not 0 <= result["round_number"] <= 8
                    or not 0 <= result["completed_rounds"] <= result["round_number"]
                    or not 0 <= result["es_calls_this_round"] <= 1000
                    or result["revision"] < 0):
                raise NroundOwnedProgressError("nround_owned_progress_unverified")
            return {
                "schema": "sraf_nround_owned_progress_v1",
                "report_job_status": report["status"],
                **result,
                "checkpoint_resume_supported": False,
                "report_generation_authorized": False,
                "word_download_authorized": False,
            }
    except Exception:
        raise NroundOwnedProgressError("nround_owned_progress_unverified") from None
