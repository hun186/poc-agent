"""OFF-1L: SQL count-only observation and conservative identity claims."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1l_schedule_claim as claim
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "a" * 32
SECRET = "TOP_SECRET_SQL_PASSWORD"


def config():
    return {
        "SRAF_OFF1G_SQL_HOST": "10.2.3.4",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "control",
        "SRAF_OFF1G_SQL_USER": "sql_checker",
        "SRAF_OFF1G_SQL_PASSWORD": SECRET,
    }


class Cursor:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def execute(self, sql, *args):
        assert sql.lstrip().startswith("SELECT COUNT_BIG(*)")
        assert "WHERE schedule_id=?" in sql
        assert "created_by=N'requirement-schedule-worker'" in sql
        assert "UPDATE " not in sql and "INSERT " not in sql
        self.log.append((sql, args))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class Connection:
    def __init__(self, rows, log):
        self.cur = Cursor(rows, log)
        self.timeout = None

    def cursor(self):
        return self.cur

    def close(self):
        pass


def fake_db(monkeypatch, snapshots=((0,), (1,))):
    calls, sleeps = [], []
    values = iter(snapshots)
    monkeypatch.setattr(claim.pyodbc, "drivers", lambda: [claim.DRIVER])
    def connect(*a, **kwargs):
        calls.append(("connect", kwargs))
        return Connection([next(values)], calls)
    monkeypatch.setattr(claim.pyodbc, "connect", connect)
    monkeypatch.setattr(claim.time, "sleep", lambda n: sleeps.append(n))
    return calls, sleeps


def test_observed_increment_is_actor_label_only(monkeypatch):
    calls, sleeps = fake_db(monkeypatch, ((3,), (4,)))
    o = claim.probe_schedule_claim_ledger(config(), schedule_id=SID)
    assert (o.status, o.reason, o.evidence) == (
        "PASS", "claim_actor_labeled_run_added", {"run_increment_observed": True})
    assert sleeps == [15]
    assert len([x for x in calls if x[0] == "connect"]) == 2
    assert all(x[1] == (SID,) for x in calls if x[0].lstrip().startswith("SELECT"))
    assert SID not in json.dumps(o.__dict__) and SECRET not in json.dumps(o.__dict__)


@pytest.mark.parametrize("snapshots,reason", [
    (((3,), (3,)), "claim_not_advanced"),
    (((3,), (2,)), "claim_not_advanced"),
    (((3,), (True,)), "claim_result_invalid"),
    (((3,), ("secret",)), "claim_result_invalid"),
    (((3,), (2**63,)), "claim_result_invalid"),
])
def test_no_false_pass_from_no_growth_or_bad_sql_result(monkeypatch, snapshots, reason):
    fake_db(monkeypatch, snapshots)
    o = claim.probe_schedule_claim_ledger(config(), schedule_id=SID)
    assert o.status == "SKIP" and o.reason == reason
    assert o.evidence["run_increment_observed"] is False


@pytest.mark.parametrize("sid", [
    "", "sch_wrong", "SCH_" + "a" * 32, "sch_" + "A" * 32,
    "sch_" + "a" * 32 + ";DROP", "sch_" + "a" * 32 + "\n", None,
])
def test_invalid_schedule_never_opens_sql_or_waits(monkeypatch, sid):
    monkeypatch.setattr(claim.pyodbc, "connect", lambda *a, **k: pytest.fail("SQL"))
    monkeypatch.setattr(claim.time, "sleep", lambda *a: pytest.fail("sleep"))
    assert claim.probe_schedule_claim_ledger(config(), schedule_id=sid).reason == "claim_schedule_id_invalid"


def test_bad_schema_and_invalid_connection_do_not_contact_sql(monkeypatch):
    monkeypatch.setattr(claim.pyodbc, "connect", lambda *a, **k: pytest.fail("SQL"))
    assert claim.probe_schedule_claim_ledger(config(), schedule_id=SID,
           schema="sra_schedule];--").reason == "claim_schema_invalid"
    assert claim.probe_schedule_claim_ledger({}, schedule_id=SID).reason == "claim_sql_config_invalid"


def test_sql_exception_redacted_without_wait(monkeypatch):
    monkeypatch.setattr(claim.pyodbc, "drivers", lambda: [claim.DRIVER])
    monkeypatch.setattr(claim.pyodbc, "connect", lambda *a, **k:
        (_ for _ in ()).throw(RuntimeError("password=" + SECRET)))
    monkeypatch.setattr(claim.time, "sleep", lambda *a: pytest.fail("sleep"))
    o = claim.probe_schedule_claim_ledger(config(), schedule_id=SID)
    assert (o.status, o.reason) == ("SKIP", "claim_sql_unverified")
    assert SECRET not in json.dumps(o.__dict__)


def test_driver_missing_no_connection(monkeypatch):
    monkeypatch.setattr(claim.pyodbc, "drivers", lambda: [])
    monkeypatch.setattr(claim.pyodbc, "connect", lambda *a, **k: pytest.fail("SQL"))
    assert claim.probe_schedule_claim_ledger(config(), schedule_id=SID).reason == "claim_driver_unavailable"


def test_wait_failure_skips_second_read(monkeypatch):
    calls, _ = fake_db(monkeypatch)
    monkeypatch.setattr(claim.time, "sleep", lambda n: (_ for _ in ()).throw(RuntimeError("private")))
    o = claim.probe_schedule_claim_ledger(config(), schedule_id=SID)
    assert o.reason == "claim_wait_interrupted"
    assert len([x for x in calls if x[0] == "connect"]) == 1


@pytest.mark.parametrize("flags,sql,workers,expect", [
    ((False, False, False, False), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, True, False), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, False, True), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, True, True), "SKIP", "PASS", "SKIP"),
    ((True, True, True, True), "PASS", "SKIP", "SKIP"),
    ((True, True, True, True), "PASS", "PASS", "PASS"),
])
def test_matrix_four_opt_ins_and_dependencies(monkeypatch, flags, sql, workers, expect):
    calls = []
    def provider(*a, **k):
        calls.append((a, k))
        return SimpleNamespace(check_id="SCHEDULE-01", probe="schedule-claim-ledger",
            aspect="schedule_actor_labeled_run_increment_only", status="PASS",
            reason="claim_actor_labeled_run_added", executed=True,
            evidence={"run_increment_observed": True})
    monkeypatch.setattr(matrix, "probe_schedule_claim_ledger", provider)
    result = matrix._schedule_claim(
        probe_network=flags[0], probe_sql_read=flags[1],
        probe_worker_identities=flags[2], probe_schedule_claim=flags[3],
        sql_read_status=sql, worker_status=workers,
        sql_config=config(), schedule_id=SID, lease_schema="sra_schedule")
    assert result["status"] == expect
    assert bool(calls) == (expect == "PASS")
    assert result["depends_on"] == ["SQL-READ", "WORKERS"]


def test_matrix_rejects_forged_evidence_and_redacts(monkeypatch):
    monkeypatch.setattr(matrix, "probe_schedule_claim_ledger", lambda *a, **kw:
        SimpleNamespace(check_id="SCHEDULE-01", probe="schedule-claim-ledger",
           aspect="schedule_actor_labeled_run_increment_only", status="PASS",
           reason="claim_actor_labeled_run_added", executed=False,
           evidence={"run_increment_observed": True, "secret": SECRET}))
    result = matrix._schedule_claim(
        probe_network=True, probe_sql_read=True, probe_worker_identities=True,
        probe_schedule_claim=True, sql_read_status="PASS", worker_status="PASS",
        sql_config=config(), schedule_id=SID, lease_schema=None)
    assert result["status"] == "SKIP" and result["reason"] == "unexpected_probe_result"
    assert SECRET not in json.dumps(result)


def test_matrix_missing_schedule_id_no_sql(monkeypatch):
    monkeypatch.setattr(matrix, "probe_schedule_claim_ledger",
                        lambda *a, **k: pytest.fail("SQL"))
    result = matrix._schedule_claim(
        probe_network=True, probe_sql_read=True, probe_worker_identities=True,
        probe_schedule_claim=True, sql_read_status="PASS", worker_status="PASS",
        sql_config=config(), schedule_id=None, lease_schema=None)
    assert result["status"] == "SKIP" and result["reason"] == "claim_schedule_id_invalid"

def test_cli_schedule_only_honors_existing_schema_override_without_handoff_flags(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: {"safe": "value"})
    monkeypatch.setenv("SRAF_OFF1I_SQL_SCHEMA", "tenant_sched")
    monkeypatch.setenv("SRAF_OFF1L_SCHEDULE_ID", SID)
    observed = []

    def report(*args, **kwargs):
        observed.append(kwargs)
        return {"overall": "INCOMPLETE", "feature_acceptance": "NOT_TESTED"}
    monkeypatch.setattr(matrix, "build_report", report)
    assert matrix.main(["--probe-network", "--probe-sql-read",
                        "--probe-worker-identities", "--probe-schedule-claim"]) == 2
    assert len(observed) == 1
    assert observed[0]["lease_schema"] == "tenant_sched"
    assert observed[0]["schedule_id"] == SID
    assert observed[0]["probe_schedule_claim"] is True
    assert observed[0]["probe_worker_lease"] is False
    assert observed[0]["probe_lease_renewal"] is False
    assert json.loads(capsys.readouterr().out)["overall"] == "INCOMPLETE"
