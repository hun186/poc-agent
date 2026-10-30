import sqlite3
import pytest
from api.services.report_job_store import ReportJobStore

LEGACY = """CREATE TABLE report_jobs (job_id TEXT PRIMARY KEY,status TEXT NOT NULL,prompt TEXT NOT NULL,filename TEXT,session_id TEXT NOT NULL,model TEXT NOT NULL,options_json TEXT NOT NULL,metadata_json TEXT NOT NULL,idempotency_key TEXT UNIQUE,request_hash TEXT NOT NULL,turn_id TEXT,docx_basename TEXT,error_type TEXT,error_message TEXT,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,updated_at TEXT NOT NULL)"""

def legacy(path):
    con=sqlite3.connect(path); con.execute(LEGACY); con.execute("INSERT INTO report_jobs(job_id,status,prompt,session_id,model,options_json,metadata_json,idempotency_key,request_hash,created_at,updated_at) VALUES('j','queued','p','s','m','{}','{}','key','h','now','now')"); con.commit(); con.close()

def test_fresh_and_legacy_migration(tmp_path):
    fresh=tmp_path/'fresh.db'; ReportJobStore(fresh).initialize()
    with sqlite3.connect(fresh) as con: assert con.execute('PRAGMA user_version').fetchone()[0] == 2
    old=tmp_path/'old.db'; legacy(old); ReportJobStore(old).initialize()
    with sqlite3.connect(old) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 2
        assert con.execute("SELECT owner_kind FROM report_jobs WHERE job_id='j'").fetchone()[0] is None

@pytest.mark.parametrize('checkpoint',["staged_validation","first_rename","index_creation","user_version"])
def test_migration_failure_rolls_back_every_step(tmp_path, checkpoint):
    path=tmp_path/(checkpoint+'.db'); legacy(path)
    class Failing(ReportJobStore):
        def _migration_checkpoint(self, name):
            if name == checkpoint: raise RuntimeError(name)
    with pytest.raises(RuntimeError): Failing(path).initialize()
    with sqlite3.connect(path) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 0
        assert con.execute("SELECT prompt FROM report_jobs WHERE job_id='j'").fetchone()[0] == 'p'
        assert not {'owner_kind','owner_id'} & {r[1] for r in con.execute('PRAGMA table_info(report_jobs)')}
        with pytest.raises(sqlite3.IntegrityError): con.execute("INSERT INTO report_jobs(job_id,status,prompt,session_id,model,options_json,metadata_json,idempotency_key,request_hash,created_at,updated_at) VALUES('j2','queued','p','s','m','{}','{}','key','h','now','now')")


@pytest.mark.parametrize("operation", ["copy", "rename_old", "rename_new", "create_index", "drop_old", "set_version"])
def test_sql_operation_failure_reopens_as_complete_legacy(tmp_path, operation):
    path = tmp_path / f"{operation}.db"; legacy(path)
    class Failing(ReportJobStore):
        def _migration_execute(self, con, name, sql):
            if name == operation: raise sqlite3.OperationalError(name)
            return super()._migration_execute(con, name, sql)
    with pytest.raises(sqlite3.OperationalError): Failing(path).initialize()
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 0
        assert con.execute("SELECT prompt FROM report_jobs").fetchone()[0] == "p"
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"report_jobs_new", "report_jobs_old"} & names


def test_malformed_version_one_is_rejected_on_reopen(tmp_path):
    path = tmp_path / "bad-v1.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE report_jobs(job_id TEXT PRIMARY KEY)")
        con.execute("PRAGMA user_version=1")
    with pytest.raises(RuntimeError, match="Canonical"):
        ReportJobStore(path).initialize()
