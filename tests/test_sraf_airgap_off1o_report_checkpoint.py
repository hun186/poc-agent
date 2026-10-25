"""OFF-1O: SQL-only Report Job checkpoint evidence is conservative."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1o_report_checkpoint as ck
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "d" * 32
SECRET = "SECRET_NEVER_ECHO"


def cfg():
    return {"SRAF_OFF1G_SQL_HOST": "10.2.3.4",
            "SRAF_OFF1G_SQL_PORT": "1433",
            "SRAF_OFF1G_SQL_DATABASE": "control",
            "SRAF_OFF1G_SQL_USER": "readonly_diag",
            "SRAF_OFF1G_SQL_PASSWORD": SECRET}


class Cursor:
    def __init__(self, rows, calls):
        self.rows, self.calls = list(rows), calls

    def execute(self, sql, *params):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "requirement_handoff_submissions" in sql
        assert "h.run_item_id=i.run_item_id" in sql
        assert "i.remote_job_state=N'completed'" in sql
        assert "i.execution_state=N'completed'" in sql
        assert "i.remote_completed_at IS NOT NULL" in sql
        assert "i.artifact_reconciled_at IS NOT NULL" in sql
        assert "DATALENGTH(i.artifact_sha256)=64" in sql
        assert "r.created_by=N'requirement-schedule-worker'" in sql
        assert "semantic_manifest_json" not in sql
        for op in ("UPDATE ", "INSERT ", "DELETE ", "MERGE ", "DROP "):
            assert op not in sql
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class Connection:
    def __init__(self, rows, calls):
        self.cur, self.timeout = Cursor(rows, calls), None

    def cursor(self):
        return self.cur

    def close(self):
        pass


def fake_sql(monkeypatch, rows=((1, 1),)):
    calls = []
    monkeypatch.setattr(ck.pyodbc, "drivers", lambda: [ck.DRIVER])
    monkeypatch.setattr(ck.pyodbc, "connect",
                        lambda *a, **kw: Connection(rows, calls))
    return calls


def test_only_server_computed_fields_redacted(monkeypatch):
    calls = fake_sql(monkeypatch)
    result = ck.probe_report_sql_checkpoint(cfg(), schedule_id=SID,
                                             schema="tenant_sched")
    assert (result.status, result.reason, result.evidence) == (
        "PASS", "report_checkpoint_persisted",
        {"report_checkpoint_persisted": True})
    assert len(calls) == 1
    assert "[tenant_sched].[requirement_batch_run_items]" in calls[0][0]
    assert calls[0][1] == (SID,)
    assert SID not in json.dumps(result.__dict__)
    assert SECRET not in json.dumps(result.__dict__)


@pytest.mark.parametrize("rows,why", [
    ((), "report_checkpoint_schedule_absent"),
    (((1, 0),), "report_checkpoint_not_observed"),
    (((0, 1),), "report_checkpoint_not_observed"),
    (((True, 1),), "report_checkpoint_result_invalid"),
    (((1, "secret"),), "report_checkpoint_result_invalid"),
    (((1,),), "report_checkpoint_result_invalid"),
    (((1, 1), (1, 1)), "report_checkpoint_rows_ambiguous"),
])
def test_missing_malformed_or_partial_sql_cannot_pass(monkeypatch, rows, why):
    fake_sql(monkeypatch, rows)
    r = ck.probe_report_sql_checkpoint(cfg(), schedule_id=SID)
    assert (r.status, r.reason) == ("SKIP", why)
    assert r.evidence == {"report_checkpoint_persisted": False}


@pytest.mark.parametrize("schedule_id,schema,why", [
    (None, "sra_schedule", "report_checkpoint_schedule_id_invalid"),
    ("sch_"+"D"*32, "sra_schedule", "report_checkpoint_schedule_id_invalid"),
    (SID+";DROP", "sra_schedule", "report_checkpoint_schedule_id_invalid"),
    (SID, "bad];--", "report_checkpoint_schema_invalid"),
])
def test_invalid_inputs_never_contact_sql(monkeypatch, schedule_id, schema, why):
    monkeypatch.setattr(ck.pyodbc, "drivers", lambda: pytest.fail("driver accessed"))
    monkeypatch.setattr(ck.pyodbc, "connect", lambda *a, **k: pytest.fail("SQL contacted"))
    assert ck.probe_report_sql_checkpoint(cfg(), schedule_id=schedule_id, schema=schema).reason == why


def test_missing_odbc_and_exception_redacted(monkeypatch):
    monkeypatch.setattr(ck.pyodbc, "drivers", lambda: [])
    assert ck.probe_report_sql_checkpoint(cfg(), schedule_id=SID).reason == "report_checkpoint_driver_unavailable"
    monkeypatch.setattr(ck.pyodbc, "drivers", lambda: [ck.DRIVER])
    monkeypatch.setattr(ck.pyodbc, "connect", lambda *a, **k:
                        (_ for _ in ()).throw(RuntimeError(SECRET)))
    r = ck.probe_report_sql_checkpoint(cfg(), schedule_id=SID)
    assert (r.status, r.reason) == ("SKIP", "report_checkpoint_sql_unverified")
    assert SECRET not in json.dumps(r.__dict__)


@pytest.mark.parametrize("flags,ack,expected", [
    ((False, False, False, False, False, False, False), "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, True, False), "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, False, True), "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, True, True), "SKIP", "SKIP"),
    ((True, True, True, True, True, True, True), "PASS", "PASS"),
])
def test_matrix_requires_seven_flags_and_actual_prior_ack(monkeypatch, flags, ack, expected):
    calls = []
    def provider(*a, **kw):
        calls.append(kw)
        return SimpleNamespace(check_id="REPORT-CHECKPOINT-01",
            probe="report-sql-checkpoint",
            aspect="latest_schedule_run_one_item_persisted_completion_only",
            status="PASS", reason="report_checkpoint_persisted",
            executed=True, evidence={"report_checkpoint_persisted": True})
    monkeypatch.setattr(matrix, "probe_report_sql_checkpoint", provider)
    r = matrix._report_checkpoint(
        probe_network=flags[0], probe_sql_read=flags[1],
        probe_worker_identities=flags[2],
        probe_schedule_claim=flags[3], probe_schedule_link=flags[4],
        probe_handoff_ack=flags[5], probe_report_checkpoint=flags[6],
        ack_status=ack, sql_config=cfg(), schedule_id=SID,
        lease_schema="tenant_sched")
    assert r["status"] == expected
    assert len(calls) == (1 if expected == "PASS" else 0)
    assert r["depends_on"] == ["SQL-READ", "HANDOFF-ACK"]


def test_forged_positive_evidence_denied(monkeypatch):
    monkeypatch.setattr(matrix, "probe_report_sql_checkpoint", lambda *a, **kw:
        SimpleNamespace(check_id="REPORT-CHECKPOINT-01",
           probe="report-sql-checkpoint",
           aspect="latest_schedule_run_one_item_persisted_completion_only",
           status="PASS", reason="report_checkpoint_persisted",
           executed=False,
           evidence={"report_checkpoint_persisted": True, "password": SECRET}))
    r = matrix._report_checkpoint(
        probe_network=True, probe_sql_read=True,
        probe_worker_identities=True, probe_schedule_claim=True,
        probe_schedule_link=True, probe_handoff_ack=True,
        probe_report_checkpoint=True, ack_status="PASS",
        sql_config=cfg(), schedule_id=SID, lease_schema=None)
    assert (r["status"], r["reason"]) == ("SKIP", "unexpected_probe_result")
    assert SECRET not in json.dumps(r)
