"""OFF-1N: strict, non-mutating Handoff SQL acknowledgement diagnostics."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1n_handoff_ack as ack
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "c" * 32
SECRET = "NEVER_PRINT_THIS_PASSWORD"


def cfg():
    return {
        "SRAF_OFF1G_SQL_HOST": "10.2.3.4",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "control",
        "SRAF_OFF1G_SQL_USER": "readonly_diag",
        "SRAF_OFF1G_SQL_PASSWORD": SECRET,
    }


class Cursor:
    def __init__(self, rows, calls):
        self.rows = list(rows)
        self.calls = calls

    def execute(self, sql, *params):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "OUTER APPLY" in sql
        assert "INNER JOIN" in sql
        assert "requirement_handoff_submissions" in sql
        assert "i.remote_job_id IS NOT NULL" in sql
        assert "i.dispatched_at IS NOT NULL" in sql
        assert "h.workflow_id=N'report_v1'" in sql
        for token in ("UPDATE ", "INSERT ", "DELETE ", "MERGE ", "DROP "):
            assert token not in sql
        assert "semantic_manifest_json" not in sql
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class Connection:
    def __init__(self, rows, calls):
        self.cur = Cursor(rows, calls)
        self.timeout = None

    def cursor(self):
        return self.cur

    def close(self):
        pass


def mock_sql(monkeypatch, rows=((1, 1),)):
    calls = []
    monkeypatch.setattr(ack.pyodbc, "drivers", lambda: [ack.DRIVER])
    monkeypatch.setattr(ack.pyodbc, "connect",
                        lambda *args, **kwargs: Connection(rows, calls))
    return calls


def test_single_sql_predicate_query_only_and_redacted(monkeypatch):
    calls = mock_sql(monkeypatch)
    result = ack.probe_handoff_sql_ack(cfg(), schedule_id=SID, schema="tenant_sched")
    assert result.status == "PASS"
    assert result.reason == "ack_persisted_submission_observed"
    assert result.evidence == {"handoff_ack_persisted": True}
    assert len(calls) == 1
    assert "[tenant_sched].[requirement_handoff_submissions]" in calls[0][0]
    assert calls[0][1] == (SID,)
    assert SID not in json.dumps(result.__dict__)
    assert SECRET not in json.dumps(result.__dict__)


@pytest.mark.parametrize("rows,reason", [
    ((), "ack_schedule_not_observed"),
    (((0, 1),), "ack_predicates_unverified"),
    (((1, 0),), "ack_predicates_unverified"),
    (((True, 1),), "ack_result_invalid"),
    (((1, "secret"),), "ack_result_invalid"),
    (((1,),), "ack_result_invalid"),
    (((1, 1), (1, 1)), "ack_rows_ambiguous"),
])
def test_missing_or_invalid_sql_evidence_skips(monkeypatch, rows, reason):
    mock_sql(monkeypatch, rows)
    r = ack.probe_handoff_sql_ack(cfg(), schedule_id=SID)
    assert (r.status, r.reason) == ("SKIP", reason)
    assert r.evidence == {"handoff_ack_persisted": False}


@pytest.mark.parametrize("id_,schema,reason", [
    (None, "sra_schedule", "ack_schedule_id_invalid"),
    ("sch_"+"C"*32, "sra_schedule", "ack_schedule_id_invalid"),
    (SID+";DELETE", "sra_schedule", "ack_schedule_id_invalid"),
    (SID, "bad];--", "ack_schema_invalid"),
])
def test_invalid_inputs_do_not_touch_sql(monkeypatch, id_, schema, reason):
    monkeypatch.setattr(ack.pyodbc, "drivers", lambda: pytest.fail("Driver touched"))
    monkeypatch.setattr(ack.pyodbc, "connect", lambda *a, **k: pytest.fail("SQL"))
    assert ack.probe_handoff_sql_ack(cfg(), schedule_id=id_, schema=schema).reason == reason


def test_missing_driver_and_error_redaction(monkeypatch):
    monkeypatch.setattr(ack.pyodbc, "drivers", lambda: [])
    assert ack.probe_handoff_sql_ack(cfg(), schedule_id=SID).reason == "ack_driver_unavailable"
    monkeypatch.setattr(ack.pyodbc, "drivers", lambda: [ack.DRIVER])
    monkeypatch.setattr(ack.pyodbc, "connect", lambda *a, **k:
                        (_ for _ in ()).throw(RuntimeError(SECRET)))
    result = ack.probe_handoff_sql_ack(cfg(), schedule_id=SID)
    assert result.reason == "ack_sql_unverified"
    assert SECRET not in json.dumps(result.__dict__)


@pytest.mark.parametrize("flags,link,expect", [
    ((False, False, False, False, False, False), "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, False), "PASS", "NOT_TESTED"),
    ((True, True, True, True, False, True), "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, True), "SKIP", "SKIP"),
    ((True, True, True, True, True, True), "PASS", "PASS"),
])
def test_matrix_explicit_six_optins_and_prior_link(monkeypatch, flags, link, expect):
    calls = []
    def provider(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(check_id="HANDOFF-ACK-01", probe="handoff-sql-ack",
            aspect="latest_schedule_run_persisted_handoff_ack_only",
            status="PASS", reason="ack_persisted_submission_observed", executed=True,
            evidence={"handoff_ack_persisted": True})
    monkeypatch.setattr(matrix, "probe_handoff_sql_ack", provider)
    row = matrix._handoff_sql_ack(
        probe_network=flags[0], probe_sql_read=flags[1],
        probe_worker_identities=flags[2], probe_schedule_claim=flags[3],
        probe_schedule_link=flags[4], probe_handoff_ack=flags[5],
        link_status=link, sql_config=cfg(), schedule_id=SID,
        lease_schema="tenant_sched")
    assert row["status"] == expect
    assert len(calls) == (1 if expect == "PASS" else 0)
    assert row["depends_on"] == ["SQL-READ", "SCHEDULE-LINK"]


def test_untrusted_positive_provider_never_promoted(monkeypatch):
    monkeypatch.setattr(matrix, "probe_handoff_sql_ack", lambda *a, **k:
       SimpleNamespace(check_id="HANDOFF-ACK-01", probe="handoff-sql-ack",
            aspect="latest_schedule_run_persisted_handoff_ack_only",
            status="PASS", reason="ack_persisted_submission_observed", executed=False,
            evidence={"handoff_ack_persisted": True, "secret": SECRET}))
    row = matrix._handoff_sql_ack(
        probe_network=True, probe_sql_read=True, probe_worker_identities=True,
        probe_schedule_claim=True, probe_schedule_link=True,
        probe_handoff_ack=True, link_status="PASS",
        sql_config=cfg(), schedule_id=SID, lease_schema=None)
    assert row["status"] == "SKIP" and row["reason"] == "unexpected_probe_result"
    assert SECRET not in json.dumps(row)
