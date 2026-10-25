"""OFF-1M strictly scoped, read-only Schedule SQL association regressions."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1m_schedule_run_link as link
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "b" * 32
SECRET = "UNPRINTED_PRIVATE_PASSWORD"


def cfg():
    return {
        "SRAF_OFF1G_SQL_HOST": "10.2.3.4",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "control",
        "SRAF_OFF1G_SQL_USER": "sql_checker",
        "SRAF_OFF1G_SQL_PASSWORD": SECRET,
    }


class Cursor:
    def __init__(self, values, calls):
        self.values, self.calls = list(values), calls

    def execute(self, sql, *params):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "OUTER APPLY" in sql
        assert "r.schedule_version_id=s.active_version_id" in sql
        assert "s.next_run_at > r.scheduled_for" in sql
        assert "r.created_by=N'requirement-schedule-worker'" in sql
        assert "UPDATE " not in sql and "INSERT " not in sql and "DELETE " not in sql
        self.calls.append((sql, params))

    def fetchone(self):
        return self.values.pop(0) if self.values else None

    def close(self):
        pass


class Connection:
    def __init__(self, values, calls):
        self.cursor_obj = Cursor(values, calls)
        self.timeout = None

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


def mocked(monkeypatch, values=((1, 1, 1),)):
    calls = []
    monkeypatch.setattr(link.pyodbc, "drivers", lambda: [link.DRIVER])
    monkeypatch.setattr(link.pyodbc, "connect", lambda *args, **kwargs:
                        Connection(values, calls))
    return calls


def test_link_only_three_server_computed_predicates(monkeypatch):
    calls = mocked(monkeypatch)
    obs = link.probe_schedule_run_link(cfg(), schedule_id=SID, schema="tenant_sched")
    assert obs.status == "PASS"
    assert obs.reason == "link_current_schedule_run_observed"
    assert obs.evidence == {"link_predicates_observed": True}
    assert len(calls) == 1
    assert "[tenant_sched].[requirement_schedules]" in calls[0][0]
    assert calls[0][1] == (SID,)
    assert SID not in json.dumps(obs.__dict__)
    assert SECRET not in json.dumps(obs.__dict__)


@pytest.mark.parametrize("values,why", [
    ((), "link_schedule_not_observed"),
    (((1, 1, 0),), "link_predicates_unverified"),
    (((1, 0, 1),), "link_predicates_unverified"),
    (((0, 1, 1),), "link_predicates_unverified"),
    (((True, 1, 1),), "link_result_invalid"),
    (((1, "secret", 1),), "link_result_invalid"),
    (((1, 1),), "link_result_invalid"),
    (((1, 1, 1), (1, 1, 1)), "link_rows_ambiguous"),
])
def test_bad_database_rows_never_pass(monkeypatch, values, why):
    mocked(monkeypatch, values)
    o = link.probe_schedule_run_link(cfg(), schedule_id=SID)
    assert (o.status, o.reason) == ("SKIP", why)
    assert o.evidence == {"link_predicates_observed": False}


@pytest.mark.parametrize("schedule_id,schema,reason", [
    (None, "sra_schedule", "link_schedule_id_invalid"),
    ("sch_"+"B"*32, "sra_schedule", "link_schedule_id_invalid"),
    ("sch_"+"b"*32+";DROP TABLE", "sra_schedule", "link_schedule_id_invalid"),
    (SID, "bad];--", "link_schema_invalid"),
])
def test_invalid_input_stops_before_odbc(monkeypatch, schedule_id, schema, reason):
    monkeypatch.setattr(link.pyodbc, "drivers", lambda: pytest.fail("Driver touched"))
    monkeypatch.setattr(link.pyodbc, "connect", lambda *a, **kw: pytest.fail("SQL contacted"))
    assert link.probe_schedule_run_link(cfg(), schedule_id=schedule_id, schema=schema).reason == reason


def test_driver_missing_and_untrusted_error_are_redacted(monkeypatch):
    monkeypatch.setattr(link.pyodbc, "drivers", lambda: [])
    assert link.probe_schedule_run_link(cfg(), schedule_id=SID).reason == "link_driver_unavailable"
    monkeypatch.setattr(link.pyodbc, "drivers", lambda: [link.DRIVER])
    monkeypatch.setattr(link.pyodbc, "connect", lambda *a, **k:
                        (_ for _ in ()).throw(RuntimeError(SECRET)))
    result = link.probe_schedule_run_link(cfg(), schedule_id=SID)
    assert result.status == "SKIP" and result.reason == "link_sql_unverified"
    assert SECRET not in json.dumps(result.__dict__)


@pytest.mark.parametrize("flags,claim,expect", [
    ((False, False, False, False, False), "PASS", "NOT_TESTED"),
    ((True, True, True, True, False), "PASS", "NOT_TESTED"),
    ((True, True, True, False, True), "PASS", "NOT_TESTED"),
    ((True, True, True, True, True), "SKIP", "SKIP"),
    ((True, True, True, True, True), "PASS", "PASS"),
])
def test_matrix_requires_five_optins_and_claim_evidence(monkeypatch, flags, claim, expect):
    calls = []
    def provider(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(check_id="SCHEDULE-02", probe="schedule-run-link",
          aspect="latest_actor_labeled_run_schedule_link_only",
          status="PASS", reason="link_current_schedule_run_observed",
          executed=True, evidence={"link_predicates_observed": True})
    monkeypatch.setattr(matrix, "probe_schedule_run_link", provider)
    result = matrix._schedule_link(
        probe_network=flags[0], probe_sql_read=flags[1],
        probe_worker_identities=flags[2], probe_schedule_claim=flags[3],
        probe_schedule_link=flags[4], claim_status=claim,
        sql_config=cfg(), schedule_id=SID, lease_schema="tenant_sched")
    assert result["status"] == expect
    assert len(calls) == (1 if expect == "PASS" else 0)
    assert result["depends_on"] == ["SQL-READ", "SCHEDULE-CLAIM"]


def test_forged_positive_evidence_rejected_without_exposing_secrets(monkeypatch):
    monkeypatch.setattr(matrix, "probe_schedule_run_link", lambda *a, **kw:
      SimpleNamespace(check_id="SCHEDULE-02", probe="schedule-run-link",
        aspect="latest_actor_labeled_run_schedule_link_only",
        status="PASS", reason="link_current_schedule_run_observed",
        executed=False, evidence={"link_predicates_observed": True, "private": SECRET}))
    result = matrix._schedule_link(
        probe_network=True, probe_sql_read=True, probe_worker_identities=True,
        probe_schedule_claim=True, probe_schedule_link=True,
        claim_status="PASS", sql_config=cfg(), schedule_id=SID,
        lease_schema=None)
    assert result["status"] == "SKIP"
    assert result["reason"] == "unexpected_probe_result"
    assert SECRET not in json.dumps(result)
