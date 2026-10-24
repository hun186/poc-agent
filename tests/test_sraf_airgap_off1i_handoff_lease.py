"""OFF-1I SQL Handoff snapshot tests; no real database in Hosted CI."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1i_handoff_lease as lease
from tools import sraf_airgap_off1d_readiness_matrix as matrix


def cfg():
    return {
        "SRAF_OFF1G_SQL_HOST": "192.168.1.20",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "sraf_control",
        "SRAF_OFF1G_SQL_USER": "readonly_monitor",
        "SRAF_OFF1G_SQL_PASSWORD": "SENTINEL-VERY-PRIVATE-SECRET",
    }


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []
        self.closed = 0

    def execute(self, query, *args):
        self.calls.append((query, args))
        if "UPDATE" in query or "INSERT" in query or "DELETE" in query:
            pytest.fail("SQL mutation forbidden")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        self.closed += 1


class Connection:
    def __init__(self, rows):
        self._cursor = Cursor(rows)
        self.timeout = None
        self.closed = 0

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed += 1


def odbc(monkeypatch, rows=((1, 1, 1),), *, fail=False, driver=True):
    observed = []
    conn = Connection(rows)

    def connect(string, **kwargs):
        observed.append((string, kwargs))
        if fail:
            raise RuntimeError("SECRET SQL native error host and password")
        return conn

    monkeypatch.setattr(lease, "pyodbc", SimpleNamespace(
        connect=connect,
        drivers=lambda: [lease.DRIVER] if driver else ["another"],
    ))
    return observed, conn


def test_active_lease_snapshot_one_fixed_sql_read_no_data_leak(monkeypatch):
    observed, conn = odbc(monkeypatch)
    result = lease.probe_handoff_lease_snapshot(cfg())
    assert (result.status, result.reason, result.executed) == (
        "PASS", "lease_active_snapshot_observed", True)
    assert result.evidence == {"active_lease_observed": True}
    assert len(observed) == 1
    cs, options = observed[0]
    assert "Encrypt=Yes;TrustServerCertificate=No" in cs
    assert options == {"timeout": 3, "autocommit": True}
    assert conn.timeout == 3
    assert conn.closed == 1 and conn._cursor.closed == 1
    assert len(conn._cursor.calls) == 1
    sql, params = conn._cursor.calls[0]
    assert "[sra_schedule].[requirement_handoff_coordinator_leases]" in sql
    assert "TOP (2)" in sql and "SYSUTCDATETIME" in sql
    assert "DATETIME" in sql.upper() and "DATEDIFF" in sql
    assert "CROSS JOIN" in sql and "WHERE control_domain=?" in sql
    assert "SELECT " in sql
    assert params == ("requirement-report-v1",)
    report = json.dumps(result.serialize())
    assert all(v not in report for v in cfg().values())
    assert "owner_id" not in report and "lease_token" not in report
    assert "FULL_LIVE" not in report


@pytest.mark.parametrize("rows,status,reason", [
    ([], "SKIP", "lease_row_not_observed"),
    ([(1, 0, 1)], "SKIP", "lease_active_state_unverified"),
    ([(1, 1, 0)], "SKIP", "lease_active_state_unverified"),
    ([(0, 1, 1)], "SKIP", "lease_active_state_unverified"),
    ([(1, 1, 1), (1, 1, 1)], "FAIL", "lease_row_ambiguous"),
    ([("1", 1, 1)], "FAIL", "lease_result_invalid"),
    ([(True, 1, 1)], "FAIL", "lease_result_invalid"),
    ([(1, 1)], "FAIL", "lease_result_invalid"),
    ([(None, 1, 1)], "FAIL", "lease_result_invalid"),
])
def test_missing_stale_invalid_lease_cannot_claim_progress(
        monkeypatch, rows, status, reason):
    _, conn = odbc(monkeypatch, rows)
    result = lease.probe_handoff_lease_snapshot(cfg())
    assert result.status == status
    assert result.reason == reason
    assert result.evidence["active_lease_observed"] is False
    assert conn._cursor.closed == 1 and conn.closed == 1


@pytest.mark.parametrize("schema", [
    "", "dbo;DROP", "sra_schedule]", "[dbo]", "sra.schedule",
    "x" * 65, "_private", "schema schema", "é", None,
])
def test_schema_invalid_no_sql_connection(monkeypatch, schema):
    calls, _ = odbc(monkeypatch)
    result = lease.probe_handoff_lease_snapshot(cfg(), schema=schema)
    assert result.status == "SKIP" and result.reason == "lease_schema_invalid"
    assert calls == []


def test_valid_custom_schema_is_single_bracketed_identifier(monkeypatch):
    _, conn = odbc(monkeypatch)
    result = lease.probe_handoff_lease_snapshot(cfg(), schema="control_02")
    assert result.status == "PASS"
    assert "[control_02].[requirement_handoff_coordinator_leases]" in conn._cursor.calls[0][0]


def test_incomplete_or_unsafe_sql_config_no_connection(monkeypatch):
    calls, _ = odbc(monkeypatch)
    result = lease.probe_handoff_lease_snapshot({
        **cfg(), "SRAF_OFF1G_SQL_HOST": "8.8.8.8"})
    assert result.reason == "lease_sql_config_invalid"
    assert not calls


def test_odbc_missing_or_connection_failure_redacted(monkeypatch):
    observed, _ = odbc(monkeypatch, driver=False)
    result = lease.probe_handoff_lease_snapshot(cfg())
    assert result.reason == "lease_driver_unavailable" and not observed
    observed, _ = odbc(monkeypatch, fail=True)
    result = lease.probe_handoff_lease_snapshot(cfg())
    assert result.reason == "lease_sql_unverified"
    assert "SECRET" not in json.dumps(result.serialize())


def obs(*, status="PASS", reason="lease_active_snapshot_observed",
        executed=True, active=True):
    return SimpleNamespace(
        check_id="LEASE-01", probe="handoff-lease-snapshot",
        aspect="handoff_db_lease_snapshot_only",
        status=status, reason=reason, executed=executed,
        evidence={"active_lease_observed": active},
    )


@pytest.mark.parametrize("network,sql_read,worker_lease,sql_status,expected", [
    (False, False, False, "PASS", "NOT_TESTED"),
    (False, True, True, "PASS", "NOT_TESTED"),
    (True, False, True, "PASS", "NOT_TESTED"),
    (True, True, False, "PASS", "NOT_TESTED"),
    (True, True, True, "SKIP", "SKIP"),
    (True, True, True, "FAIL", "SKIP"),
    (True, True, True, "PASS", "PASS"),
])
def test_matrix_all_optins_and_real_sql_dependency(
        monkeypatch, network, sql_read, worker_lease, sql_status, expected):
    calls = []
    def probe(config, *, schema):
        calls.append((config, schema))
        return obs()
    monkeypatch.setattr(matrix, "probe_handoff_lease_snapshot", probe)
    row = matrix._handoff_lease_snapshot(
        probe_network=network, probe_sql_read=sql_read,
        probe_worker_lease=worker_lease, sql_read_status=sql_status,
        sql_config=cfg(), lease_schema=None,
    )
    assert row["status"] == expected
    assert row["depends_on"] == ["SQL-READ"]
    assert row["feature_acceptance"] == "NOT_TESTED"
    assert len(calls) == (1 if expected == "PASS" else 0)


def test_matrix_rejects_fake_nested_pass_and_redacts_errors(monkeypatch):
    monkeypatch.setattr(matrix, "probe_handoff_lease_snapshot",
                        lambda *a, **k: obs(active=False))
    opts = dict(probe_network=True, probe_sql_read=True,
                probe_worker_lease=True, sql_read_status="PASS",
                sql_config=cfg(), lease_schema=None)
    row = matrix._handoff_lease_snapshot(**opts)
    assert row["status"] == "SKIP"
    monkeypatch.setattr(matrix, "probe_handoff_lease_snapshot",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("SENTINEL-SQL-PASSWORD")))
    row = matrix._handoff_lease_snapshot(**opts)
    assert row["reason"] == "lease_sql_unverified"
    assert "SENTINEL" not in json.dumps(row)


def test_cli_worker_lease_flag_alone_never_touches_sql(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: {})
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda *a, **k: matrix._record(
                            a[0], "host", "diagnostic", "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_tcp_probe",
                        lambda service, cfg, *, probe_network:
                        matrix._record({
                            "api":"API-TCP", "es":"ES-TCP", "llm":"LLM-TCP"
                        }[service], service, "tcp", "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_api_health",
                        lambda *a, **k: matrix._record(
                            "API-HEALTH", "api", "healthz_http_only",
                            "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "probe_handoff_lease_snapshot",
                        lambda *a, **k: pytest.fail("no SQL read permitted"))
    assert matrix.main(["--probe-worker-lease"]) == 2
    data = json.loads(capsys.readouterr().out)
    row = {x["id"]: x for x in data["results"]}["HANDOFF-LEASE"]
    assert row["status"] == "NOT_TESTED"
    assert data["network_mode"] == "LOCAL_ONLY_NO_NETWORK"
    assert data["feature_acceptance"] == "NOT_TESTED"
