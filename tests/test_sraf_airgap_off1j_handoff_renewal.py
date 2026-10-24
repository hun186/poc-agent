"""OFF-1J two-point DB heartbeat: no private SQL Server in Hosted CI."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1j_handoff_renewal as renewal
from tools import sraf_airgap_off1d_readiness_matrix as matrix


def cfg():
    return {
        "SRAF_OFF1G_SQL_HOST": "192.168.22.11",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "sraf_control",
        "SRAF_OFF1G_SQL_USER": "probe_reader",
        "SRAF_OFF1G_SQL_PASSWORD": "NEVER_LEAK_SECRET_123",
    }


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.closed = 0
        self.queries = []

    def execute(self, sql, domain):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "UPDATE " not in sql and "INSERT " not in sql
        self.queries.append((sql, domain))

    def fetchone(self):
        return next(self.rows, None)

    def close(self):
        self.closed += 1


class Connection:
    def __init__(self, rows):
        self.c = Cursor(rows)
        self.closed = 0
        self.timeout = None

    def cursor(self):
        return self.c

    def close(self):
        self.closed += 1


def fake_odbc(monkeypatch, *, snapshots=(((1, 1, 1, 7, 10000),),
                                        ((1, 1, 1, 7, 16000),)),
              fail_at=None, driver=True):
    connections = []
    configs = []
    queued = list(snapshots)

    def connect(connection, **kwargs):
        configs.append((connection, kwargs))
        if fail_at == len(configs):
            raise RuntimeError("HOST SECRET SQL NATIVE ERROR")
        result = Connection(queued.pop(0))
        connections.append(result)
        return result

    monkeypatch.setattr(renewal, "pyodbc", SimpleNamespace(
        drivers=lambda: [renewal.DRIVER] if driver else ["Other"],
        connect=connect,
    ))
    waits = []
    monkeypatch.setattr(renewal.time, "sleep", lambda s: waits.append(s))
    return connections, configs, waits


def test_two_db_snapshots_prove_same_generation_heartbeat_advance(monkeypatch):
    connections, configs, waits = fake_odbc(monkeypatch)
    outcome = renewal.probe_handoff_lease_renewal(cfg())
    assert outcome.status == "PASS"
    assert outcome.reason == "lease_renewal_advanced"
    assert outcome.evidence == {"renewal_observed": True}
    assert waits == [15] and len(connections) == len(configs) == 2
    assert all(c.closed == c.c.closed == 1 for c in connections)
    assert all(c.timeout == 3 for c in connections)
    assert all(x[1] == {"timeout": 3, "autocommit": True}
               for x in configs)
    assert all("Encrypt=Yes;TrustServerCertificate=No" in x[0]
               for x in configs)
    for conn in connections:
        assert len(conn.c.queries) == 1
        sql, domain = conn.c.queries[0]
        assert domain == "requirement-report-v1"
        assert "fencing_generation" in sql and "heartbeat_at" in sql
        assert "DATEDIFF_BIG" in sql and "SYSUTCDATETIME()" in sql
        assert "[sra_schedule].[requirement_handoff_coordinator_leases]" in sql
    report = json.dumps(outcome.serialize())
    for val in cfg().values():
        assert val not in report
    assert "10000" not in report and "16000" not in report
    assert "lease_token" not in report
    assert outcome.serialize()["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


@pytest.mark.parametrize("snapshots,reason,waits_expected", [
    (((),), "lease_renewal_row_unavailable", 0),
    ((((1, 1, 1, 7, 10000), (1, 1, 1, 7, 10100)),),
     "lease_renewal_rows_ambiguous", 0),
    ((((1, 0, 1, 7, 10000),),),
     "lease_renewal_snapshot_inactive", 0),
    ((((1, 1, 1, 7, 10000),), ()),
     "lease_renewal_row_unavailable", 1),
    ((((1, 1, 1, 7, 10000),), ((1, 1, 1, 8, 16000),)),
     "lease_renewal_generation_changed", 1),
    ((((1, 1, 1, 7, 10000),), ((1, 1, 1, 7, 10000),)),
     "lease_renewal_not_advanced", 1),
    ((((1, 1, 1, 7, 10000),), ((1, 1, 1, 7, 9000),)),
     "lease_renewal_not_advanced", 1),
    ((((1, 1, 1, True, 10000),),),
     "lease_renewal_result_invalid", 0),
    ((((1, 1, 1, 7, None),),),
     "lease_renewal_result_invalid", 0),
    ((((1, 1, 1, 7, 10000),), ((1, 1, 0, 7, 16000),)),
     "lease_renewal_snapshot_inactive", 1),
])
def test_no_false_renewal_on_missing_stale_or_changed_rows(
        monkeypatch, snapshots, reason, waits_expected):
    connections, configs, waits = fake_odbc(
        monkeypatch, snapshots=snapshots)
    outcome = renewal.probe_handoff_lease_renewal(cfg())
    assert (outcome.status, outcome.reason) == ("SKIP", reason)
    assert outcome.evidence["renewal_observed"] is False
    assert len(waits) == waits_expected
    assert len(configs) == len(connections)
    assert all(x.closed == x.c.closed == 1 for x in connections)


@pytest.mark.parametrize("schema", ["", "dbo;DROP", "[sra_schedule]", None,
                                     "sra.schedule", "z" * 65])
def test_invalid_schema_never_connects_or_waits(monkeypatch, schema):
    connections, configs, waits = fake_odbc(monkeypatch)
    outcome = renewal.probe_handoff_lease_renewal(cfg(), schema=schema)
    assert outcome.reason == "lease_renewal_schema_invalid"
    assert not connections and not configs and not waits


def test_missing_driver_or_unsafe_host_is_no_network(monkeypatch):
    _, configs, waits = fake_odbc(monkeypatch, driver=False)
    assert renewal.probe_handoff_lease_renewal(cfg()).reason == (
        "lease_renewal_driver_unavailable")
    assert not configs and not waits
    _, configs, waits = fake_odbc(monkeypatch)
    bad = {**cfg(), "SRAF_OFF1G_SQL_HOST": "8.8.8.8"}
    assert renewal.probe_handoff_lease_renewal(bad).reason == (
        "lease_renewal_config_invalid")
    assert not configs and not waits


def test_sql_error_second_sample_closes_first_and_redacts(monkeypatch):
    connections, configs, waits = fake_odbc(monkeypatch, fail_at=2)
    outcome = renewal.probe_handoff_lease_renewal(cfg())
    assert outcome.reason == "lease_renewal_sql_unverified"
    assert len(configs) == 2 and waits == [15]
    assert connections[0].closed == connections[0].c.closed == 1
    assert "SECRET" not in json.dumps(outcome.serialize())


def test_wait_error_no_second_sql(monkeypatch):
    connections, configs, waits = fake_odbc(monkeypatch)
    monkeypatch.setattr(renewal.time, "sleep",
                        lambda x: (_ for _ in ()).throw(RuntimeError("secret")))
    outcome = renewal.probe_handoff_lease_renewal(cfg())
    assert outcome.reason == "lease_renewal_wait_interrupted"
    assert len(configs) == 1
    assert connections[0].closed == 1


def _observation(*, status="PASS", reason="lease_renewal_advanced",
                 renewed=True):
    return SimpleNamespace(
        check_id="LEASE-02", probe="handoff-lease-renewal",
        aspect="two_sample_db_heartbeat_advance_only",
        status=status, reason=reason, executed=True,
        evidence={"renewal_observed": renewed},
    )


@pytest.mark.parametrize("network,sql,lease,renewal_opt,lease_status,expected", [
    (False, False, False, False, "PASS", "NOT_TESTED"),
    (True, True, True, False, "PASS", "NOT_TESTED"),
    (False, True, True, True, "PASS", "NOT_TESTED"),
    (True, False, True, True, "PASS", "NOT_TESTED"),
    (True, True, False, True, "PASS", "NOT_TESTED"),
    (True, True, True, True, "SKIP", "SKIP"),
    (True, True, True, True, "FAIL", "SKIP"),
    (True, True, True, True, "PASS", "PASS"),
])
def test_matrix_four_opt_ins_existing_lease_pass_required(
        monkeypatch, network, sql, lease, renewal_opt, lease_status, expected):
    calls = []
    monkeypatch.setattr(matrix, "probe_handoff_lease_renewal",
                        lambda *a, **k: (calls.append((a, k)) or _observation()))
    row = matrix._handoff_lease_renewal(
        probe_network=network, probe_sql_read=sql,
        probe_worker_lease=lease, probe_lease_renewal=renewal_opt,
        lease_status=lease_status, sql_config=cfg(), lease_schema=None)
    assert row["status"] == expected
    assert row["feature_acceptance"] == "NOT_TESTED"
    assert row["depends_on"] == ["SQL-READ", "HANDOFF-LEASE"]
    assert len(calls) == int(expected == "PASS")


def test_matrix_forged_provider_pass_and_secret_error_safe(monkeypatch):
    opts = dict(probe_network=True, probe_sql_read=True,
                probe_worker_lease=True, probe_lease_renewal=True,
                lease_status="PASS", sql_config=cfg(), lease_schema=None)
    monkeypatch.setattr(matrix, "probe_handoff_lease_renewal",
                        lambda *a, **kw: _observation(renewed=False))
    row = matrix._handoff_lease_renewal(**opts)
    assert row["status"] == "SKIP"
    monkeypatch.setattr(matrix, "probe_handoff_lease_renewal",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            RuntimeError("SECRET SQL native diagnostic")))
    row = matrix._handoff_lease_renewal(**opts)
    assert row["status"] == "SKIP"
    assert "SECRET" not in json.dumps(row)


def test_cli_renewal_flag_alone_no_network_no_15second_wait(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: {})
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda key, component, aspect, fn:
                        matrix._record(key, component, aspect, "SKIP",
                                       "network_disabled"))
    monkeypatch.setattr(matrix, "_tcp_probe",
                        lambda service, cfg, *, probe_network:
                        matrix._record(
                            {"api": "API-TCP", "es": "ES-TCP", "llm": "LLM-TCP"}[service],
                            service, "configured_tcp_only", "SKIP",
                            "network_disabled"))
    monkeypatch.setattr(matrix, "_api_health",
                        lambda *a, **k: matrix._record(
                            "API-HEALTH", "api", "healthz_http_only", "SKIP",
                            "network_disabled"))
    monkeypatch.setattr(matrix, "probe_handoff_lease_renewal",
                        lambda *a, **k: pytest.fail("unexpected SQL renewal"))
    for flags in ([], ["--probe-lease-renewal"], ["--probe-network"]):
        assert matrix.main(flags) == 2
        results = json.loads(capsys.readouterr().out)
        row = {x["id"]: x for x in results["results"]}["HANDOFF-RENEWAL"]
        assert row["status"] == "NOT_TESTED"
        assert results["feature_acceptance"] == "NOT_TESTED"
