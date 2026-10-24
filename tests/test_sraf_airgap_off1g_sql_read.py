"""OFF-1G SQL Server constant SELECT: no real DB in Hosted CI."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1g_sql_read as sql
from tools import sraf_airgap_off1d_readiness_matrix as matrix


def cfg(**changes):
    values = {
        "SRAF_OFF1G_SQL_HOST": "192.168.20.40",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "sraf_reports",
        "SRAF_OFF1G_SQL_USER": "sraf_probe_reader",
        "SRAF_OFF1G_SQL_PASSWORD": "p;ass}word_Complex123",
    }
    values.update(changes)
    return values


class Cursor:
    def __init__(self, value=1):
        self.timeout = None
        self.value = value
        self.calls = []
        self.close_count = 0

    def execute(self, query):
        self.calls.append(query)

    def fetchone(self):
        if not hasattr(self, "_done"):
            self._done = True
            return [self.value]
        return None

    def close(self):
        self.close_count += 1


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = 0

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed += 1


def mock_odbc(monkeypatch, *, driver=True, value=1, raises=False):
    calls = []
    cursor = Cursor(value)
    connection = Connection(cursor)

    def connect(s, **kwargs):
        calls.append((s, kwargs))
        if raises:
            raise RuntimeError("SECRET native ODBC error with SQL host")
        return connection

    fake = SimpleNamespace(
        connect=connect,
        drivers=lambda: [sql.DRIVER] if driver else ["SQLite3"],
    )
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    return calls, cursor, connection


def test_positive_constant_sql_roundtrip_tls_only_and_cleanup(monkeypatch):
    calls, cursor, conn = mock_odbc(monkeypatch)
    obs = sql.probe_sql_constant_read(cfg())
    assert obs.status == "PASS"
    assert obs.executed
    assert obs.reason == "sql_constant_select_observed"
    assert obs.evidence == {"constant_select_observed": True}
    assert len(calls) == 1
    cs, kwargs = calls[0]
    assert cs.startswith("DRIVER={ODBC Driver 18 for SQL Server};")
    assert "SERVER=tcp:192.168.20.40,1433;" in cs
    assert "DATABASE={sraf_reports}" in cs
    assert "UID={sraf_probe_reader};" in cs
    assert "PWD={p;ass}}word_Complex123}" in cs
    assert "Encrypt=Yes;TrustServerCertificate=No" in cs
    assert "ApplicationIntent=ReadOnly" in cs
    assert "MultiSubnetFailover=No" in cs
    assert kwargs == {"timeout": 3, "autocommit": True}
    assert cursor.timeout == 3
    assert cursor.calls == [sql.QUERY]
    assert cursor.close_count == 1 and conn.closed == 1
    output = json.dumps(obs.serialize())
    for v in cfg().values():
        assert v not in output
    assert sql.QUERY not in output
    assert "FULL_LIVE" not in output


@pytest.mark.parametrize("changes", [
    {"SRAF_OFF1G_SQL_HOST": "8.8.8.8"},
    {"SRAF_OFF1G_SQL_HOST": "172.15.1.1"},
    {"SRAF_OFF1G_SQL_HOST": "example.com"},
    {"SRAF_OFF1G_SQL_HOST": "127.0.0.1;UID=admin"},
    {"SRAF_OFF1G_SQL_HOST": "0.0.0.0"},
    {"SRAF_OFF1G_SQL_HOST": "::1"},
    {"SRAF_OFF1G_SQL_HOST": "192.168.020.040"},
    {"SRAF_OFF1G_SQL_PORT": "0"},
    {"SRAF_OFF1G_SQL_PORT": "65536"},
    {"SRAF_OFF1G_SQL_PORT": "1433;TrustServerCertificate=Yes"},
    {"SRAF_OFF1G_SQL_PORT": "01433"},
    {"SRAF_OFF1G_SQL_DATABASE": "db;ATTACH=evil"},
    {"SRAF_OFF1G_SQL_DATABASE": "db}"},
    {"SRAF_OFF1G_SQL_USER": "admin;Role=sysadmin"},
    {"SRAF_OFF1G_SQL_USER": "name\n"},
    {"SRAF_OFF1G_SQL_PASSWORD": ""},
    {"SRAF_OFF1G_SQL_PASSWORD": "\x00secret"},
    {"SRAF_OFF1G_SQL_PASSWORD": "s" * 257},
])
def test_invalid_target_and_credential_config_never_connects(
        monkeypatch, changes):
    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(
        connect=lambda *a, **k: pytest.fail("must not connect"),
        drivers=lambda: [sql.DRIVER]))
    obs = sql.probe_sql_constant_read(cfg(**changes))
    assert obs.status == "SKIP"
    assert obs.reason == "sql_read_config_invalid"
    assert obs.executed is False


@pytest.mark.parametrize("ip,expected", [
    ("127.0.0.1", True), ("10.0.0.3", True),
    ("172.16.0.1", True), ("172.31.255.254", True),
    ("192.168.255.254", True), ("172.32.0.1", False),
    ("169.254.10.1", False), ("224.0.0.1", False),
    ("255.255.255.255", False),
])
def test_private_rfc1918_ipv4_scope(ip, expected):
    assert sql._private_ip(ip) is expected


def test_no_odbc_driver_exits_without_connect(monkeypatch):
    calls, cursor, conn = mock_odbc(monkeypatch, driver=False)
    obs = sql.probe_sql_constant_read(cfg())
    assert obs.status == "SKIP"
    assert obs.reason == "sql_read_driver_unavailable"
    assert calls == []


def test_connection_error_is_redacted_and_cannot_claim_db_rejected(monkeypatch):
    calls, _, _ = mock_odbc(monkeypatch, raises=True)
    obs = sql.probe_sql_constant_read(cfg())
    assert obs.status == "SKIP"
    assert obs.reason == "sql_read_connection_unverified"
    assert obs.executed is True
    assert "SECRET" not in json.dumps(obs.serialize())
    assert len(calls) == 1


@pytest.mark.parametrize("bad", [0, 2, True, "1", None])
def test_contradictory_constant_response_cannot_pass(monkeypatch, bad):
    calls, cur, conn = mock_odbc(monkeypatch, value=bad)
    obs = sql.probe_sql_constant_read(cfg())
    assert obs.status == "FAIL"
    assert obs.reason == "sql_read_response_invalid"
    assert cur.close_count == 1 and conn.closed == 1


def test_missing_sql_configuration_no_import_or_network(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", SimpleNamespace(
        connect=lambda *args, **kwargs: pytest.fail("not authorized")))
    obs = sql.probe_sql_constant_read({})
    assert obs.status == "SKIP" and not obs.executed


def _record(status="PASS", reason="sql_constant_select_observed",
            *, executed=True, success=True, check_id="SQL-01"):
    return SimpleNamespace(
        status=status, reason=reason, executed=executed,
        check_id=check_id, probe="sql-constant-read",
        aspect="sql_server_constant_select_only",
        evidence={"constant_select_observed": success},
    )


def _run_matrix(monkeypatch, *, network=True, sql_read=True,
                odbc="PASS", sql_config=None, observed=None):
    calls = []
    def probe(given):
        calls.append(given)
        return observed or _record()
    monkeypatch.setattr(matrix, "probe_sql_constant_read", probe)
    result = matrix._sql_constant_read(
        probe_network=network, probe_sql_read=sql_read,
        odbc_status=odbc, sql_config=cfg() if sql_config is None else sql_config)
    return result, calls


@pytest.mark.parametrize("network,sql_read,odbc,expected,reason", [
    (False, False, "PASS", "NOT_TESTED", "sql_read_not_requested"),
    (False, True, "PASS", "NOT_TESTED", "sql_read_not_requested"),
    (True, False, "PASS", "NOT_TESTED", "sql_read_not_requested"),
    (True, True, "FAIL", "SKIP", "sql_read_odbc_not_passed"),
    (True, True, "WARN", "SKIP", "sql_read_odbc_not_passed"),
    (True, True, "PASS", "PASS", "sql_constant_select_observed"),
])
def test_double_operator_flag_and_driver_preconditions(
        monkeypatch, network, sql_read, odbc, expected, reason):
    row, calls = _run_matrix(
        monkeypatch, network=network, sql_read=sql_read, odbc=odbc)
    assert row["status"] == expected and row["reason"] == reason
    assert row["feature_acceptance"] == "NOT_TESTED"
    assert row["depends_on"] == ["SQL-ODBC"]
    assert len(calls) == (1 if expected == "PASS" else 0)


@pytest.mark.parametrize("observation,expected", [
    (_record(success=False), "SKIP"),
    (_record(executed=False), "SKIP"),
    (_record(check_id="USER-FORGED"), "SKIP"),
    (_record(reason="faked SQL permission PASS"), "SKIP"),
    (_record(status="FAIL", reason="sql_read_response_invalid"), "FAIL"),
    (_record(status="SKIP", reason="sql_read_connection_unverified"), "SKIP"),
    (_record(status="FAIL", reason="native SQL SERVER SECRET"), "FAIL"),
])
def test_nested_sql_provider_cannot_upgrade_or_leak(
        monkeypatch, observation, expected):
    row, calls = _run_matrix(monkeypatch, observed=observation)
    assert row["status"] == expected
    assert row["feature_acceptance"] == "NOT_TESTED"
    assert "SECRET" not in json.dumps(row)
    assert len(calls) == 1


def test_missing_config_and_unrelated_network_do_not_trigger_sql(monkeypatch):
    row, calls = _run_matrix(monkeypatch, sql_config={})
    # Matrix passes deliberately provided empty config to nested provider;
    # nested config guard rejects before import/network.
    assert row["status"] == "PASS"  # provider stub only, not real SQL
    assert calls == [{}]


def test_cli_no_sql_flags_never_reads_operator_credentials(
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
    monkeypatch.setattr(matrix, "probe_sql_constant_read",
                        lambda *a: pytest.fail("no SQL operation expected"))
    for key, val in cfg().items():
        monkeypatch.setenv(key, val)
    for flags in ([], ["--probe-sql-read"], ["--probe-network"]):
        assert matrix.main(flags) == 2
        result = json.loads(capsys.readouterr().out)
        sql_row = {row["id"]: row for row in result["results"]}["SQL-READ"]
        assert sql_row["status"] == "NOT_TESTED"
        out = json.dumps(result)
        assert all(v not in out for v in cfg().values())


def test_cli_both_flags_sends_separate_operator_env_to_sql_probe(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: {})
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda key, component, aspect, fn:
                        matrix._record(key, component, aspect, "PASS",
                                       "disk_threshold_met"))
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
    got = []
    def nested(operator):
        got.append(operator)
        return _record()
    monkeypatch.setattr(matrix, "probe_sql_constant_read", nested)
    for key, val in cfg().items():
        monkeypatch.setenv(key, val)
    assert matrix.main(["--probe-network", "--probe-sql-read"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert got == [cfg()]
    row = {x["id"]: x for x in data["results"]}["SQL-READ"]
    assert row["status"] == "PASS"
    assert data["feature_acceptance"] == "NOT_TESTED"
    assert all(v not in json.dumps(data) for v in cfg().values())
