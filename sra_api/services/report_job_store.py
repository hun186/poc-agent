"""SQLite persistence for single-machine report jobs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any


class IdempotencyConflict(Exception):
    pass

REPORT_JOB_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReportJob:
    job_id: str
    status: str
    prompt: str
    filename: str | None
    session_id: str
    model: str
    options: dict[str, Any]
    metadata: dict[str, Any]
    idempotency_key: str | None
    request_hash: str
    owner_kind: str | None = None
    owner_id: str | None = None
    turn_id: str | None = None
    docx_basename: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReportJobStore:
    def __init__(self, db_path: str | Path, busy_timeout_ms: int = 5000):
        self.db_path = Path(db_path)
        self.busy_timeout_ms = busy_timeout_ms

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=self.busy_timeout_ms / 1000)
        con.row_factory = sqlite3.Row
        con.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _migration_checkpoint(self, name: str) -> None:
        """Test seam for proving transactional rollback; production is a no-op."""

    def initialize(self) -> None:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_jobs'").fetchone()
            if not exists:
                self._create_v1(con, "report_jobs")
                self._create_owner_index(con)
                con.execute(f"PRAGMA user_version={REPORT_JOB_SCHEMA_VERSION}")
            elif version == 0:
                self._migrate_v0(con)
            elif version != REPORT_JOB_SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported report job schema version: {version}")
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _create_v1(con, name):
        con.execute(f"""CREATE TABLE {name} (
              job_id TEXT PRIMARY KEY, status TEXT NOT NULL, prompt TEXT NOT NULL,
              filename TEXT, session_id TEXT NOT NULL, model TEXT NOT NULL,
              options_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
              idempotency_key TEXT, request_hash TEXT NOT NULL,
              owner_kind TEXT, owner_id TEXT,
              turn_id TEXT, docx_basename TEXT, error_type TEXT, error_message TEXT,
              created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL)""")

    @staticmethod
    def _create_owner_index(con):
        con.execute("CREATE UNIQUE INDEX uq_report_jobs_owner_idempotency ON report_jobs(owner_kind, owner_id, idempotency_key) WHERE idempotency_key IS NOT NULL")

    def _migrate_v0(self, con):
        cols = [r[1] for r in con.execute("PRAGMA table_info(report_jobs)")]
        legacy = ["job_id","status","prompt","filename","session_id","model","options_json","metadata_json","idempotency_key","request_hash","turn_id","docx_basename","error_type","error_message","created_at","started_at","finished_at","updated_at"]
        if cols != legacy: raise RuntimeError("Unsupported legacy report_jobs schema")
        count = con.execute("SELECT COUNT(*) FROM report_jobs").fetchone()[0]
        self._create_v1(con, "report_jobs_new")
        fields = ",".join(legacy)
        con.execute(f"INSERT INTO report_jobs_new ({fields},owner_kind,owner_id) SELECT {fields},NULL,NULL FROM report_jobs")
        staged = con.execute("SELECT COUNT(*) FROM report_jobs_new").fetchone()[0]
        missing = con.execute("SELECT COUNT(*) FROM report_jobs l LEFT JOIN report_jobs_new n ON n.job_id=l.job_id WHERE n.job_id IS NULL").fetchone()[0]
        if staged != count or missing: raise RuntimeError("Staged report job validation failed")
        self._migration_checkpoint("staged_validation")
        con.execute("ALTER TABLE report_jobs RENAME TO report_jobs_old")
        self._migration_checkpoint("first_rename")
        con.execute("ALTER TABLE report_jobs_new RENAME TO report_jobs")
        self._create_owner_index(con)
        self._migration_checkpoint("index_creation")
        newcols = [r[1] for r in con.execute("PRAGMA table_info(report_jobs)")]
        idx = con.execute("PRAGMA index_list(report_jobs)").fetchall()
        named = [r for r in idx if r[1] == "uq_report_jobs_owner_idempotency" and r[2] == 1]
        idxcols = [r[2] for r in con.execute("PRAGMA index_info(uq_report_jobs_owner_idempotency)")]
        if not {"owner_kind","owner_id"}.issubset(newcols) or not named or idxcols != ["owner_kind","owner_id","idempotency_key"] or con.execute("SELECT COUNT(*) FROM report_jobs").fetchone()[0] != count:
            raise RuntimeError("Canonical report job validation failed")
        con.execute("DROP TABLE report_jobs_old")
        con.execute(f"PRAGMA user_version={REPORT_JOB_SCHEMA_VERSION}")
        self._migration_checkpoint("user_version")
        if con.execute("PRAGMA user_version").fetchone()[0] != REPORT_JOB_SCHEMA_VERSION: raise RuntimeError("Schema version update failed")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> ReportJob | None:
        if row is None:
            return None
        data = dict(row)
        data["options"] = json.loads(data.pop("options_json"))
        data["metadata"] = json.loads(data.pop("metadata_json"))
        return ReportJob(**data)

    def create(self, *, job_id: str, prompt: str, filename: str | None, session_id: str,
               model: str, options: dict, metadata: dict, idempotency_key: str | None,
               request_hash: str, owner_kind: str | None = None, owner_id: str | None = None) -> tuple[ReportJob, bool]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("INSERT INTO report_jobs (job_id,status,prompt,filename,session_id,model,options_json,metadata_json,idempotency_key,request_hash,owner_kind,owner_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (job_id,"queued",prompt,filename,session_id,model,json.dumps(options,sort_keys=True),json.dumps(metadata,sort_keys=True),idempotency_key,request_hash,owner_kind,owner_id,now,now))
                return self.get(job_id, connection=con), True
            except sqlite3.IntegrityError:
                if not idempotency_key:
                    raise
                row = con.execute("SELECT * FROM report_jobs WHERE owner_kind IS ? AND owner_id IS ? AND idempotency_key=?", (owner_kind,owner_id,idempotency_key)).fetchone()
                if row is None or row["request_hash"] != request_hash:
                    raise IdempotencyConflict("Idempotency-Key was already used for a different request")
                return self._row(row), False

    def get(self, job_id: str, connection: sqlite3.Connection | None = None) -> ReportJob | None:
        if connection is not None:
            return self._row(connection.execute("SELECT * FROM report_jobs WHERE job_id=?", (job_id,)).fetchone())
        with self._connect() as con:
            return self._row(con.execute("SELECT * FROM report_jobs WHERE job_id=?", (job_id,)).fetchone())

    def claim_next(self) -> ReportJob | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT job_id FROM report_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            changed = con.execute("UPDATE report_jobs SET status='running',started_at=?,updated_at=? WHERE job_id=? AND status='queued'", (now,now,row[0])).rowcount
            return self.get(row[0], connection=con) if changed == 1 else None

    def recover_running(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            return con.execute("UPDATE report_jobs SET status='interrupted',error_type='service_restart',error_message='Execution interrupted by service restart',finished_at=?,updated_at=? WHERE status='running'", (now,now)).rowcount

    def complete(self, job_id: str, turn_id: str, basename: str) -> None:
        self._finish(job_id, "completed", turn_id=turn_id, basename=basename)

    def fail(self, job_id: str, error_type: str, message: str) -> None:
        self._finish(job_id, "failed", error_type=error_type, message=message)

    def _finish(self, job_id: str, status: str, *, turn_id=None, basename=None, error_type=None, message=None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute("UPDATE report_jobs SET status=?,turn_id=?,docx_basename=?,error_type=?,error_message=?,finished_at=?,updated_at=? WHERE job_id=? AND status='running'", (status,turn_id,basename,error_type,message,now,now,job_id))
