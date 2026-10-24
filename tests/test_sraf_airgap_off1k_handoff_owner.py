"""OFF-1K tests: NUL env, canonical PID evidence, parameterized SQL owner."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1k_handoff_owner as owner
from tools import sraf_airgap_off1d_readiness_matrix as matrix


def cfg():
    return {
        "SRAF_OFF1G_SQL_HOST": "10.2.3.4",
        "SRAF_OFF1G_SQL_PORT": "1433",
        "SRAF_OFF1G_SQL_DATABASE": "control",
        "SRAF_OFF1G_SQL_USER": "sql_checker",
        "SRAF_OFF1G_SQL_PASSWORD": "ULTRA_PRIVATE_PASSWORD",
    }


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.called = []
        self.closes = 0

    def execute(self, sql, *args):
        self.called.append((sql, args))
        assert sql.lstrip().startswith("SELECT TOP (2)")
        for keyword in ("UPDATE ", "INSERT ", "DELETE ", "DROP "):
            assert keyword not in sql

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        self.closes += 1


class Connection:
    def __init__(self, rows):
        self.c = Cursor(rows)
        self.timeout = None
        self.closes = 0

    def cursor(self):
        return self.c

    def close(self):
        self.closes += 1


def fake_odbc(monkeypatch, rows=((1, 1, 1),), *, fail=False, driver=True):
    seen = []
    db = Connection(rows)

    def connect(string, **kwargs):
        seen.append((string, kwargs))
        if fail:
            raise RuntimeError("SECRET DRIVER USER HOST")
        return db

    monkeypatch.setattr(owner, "pyodbc", SimpleNamespace(
        connect=connect, drivers=lambda: [owner.DRIVER] if driver else [],
    ))
    return seen, db


def trusted(monkeypatch, *, name="custom:handoff@alpha"):
    calls = []
    def probe(root):
        calls.append(root)
        return (1234, "9988", name)
    monkeypatch.setattr(owner, "_trusted_local_owner", probe)
    return calls


def test_explicit_owner_correlates_to_only_sql_computed_predicates(
        tmp_path, monkeypatch):
    calls = trusted(monkeypatch)
    seen, db = fake_odbc(monkeypatch)
    result = owner.probe_handoff_local_owner(
        cfg(), project_root=tmp_path, schema="sra_schedule")
    assert (result.status, result.reason, result.executed) == (
        "PASS", "owner_local_sql_match_observed", True)
    assert result.evidence == {"local_owner_match_observed": True}
    assert calls == [tmp_path, tmp_path]
    assert len(seen) == 1
    assert "Encrypt=Yes;TrustServerCertificate=No" in seen[0][0]
    assert seen[0][1] == {"timeout": 3, "autocommit": True}
    assert db.timeout == 3
    assert db.closes == db.c.closes == 1
    assert len(db.c.called) == 1
    sql, params = db.c.called[0]
    assert params == ("custom:handoff@alpha", "requirement-report-v1")
    assert "CONVERT(varbinary(256), owner_id)" in sql
    assert "CAST(? AS nvarchar(128))" in sql
    assert "[sra_schedule].[requirement_handoff_coordinator_leases]" in sql
    assert "SYSUTCDATETIME()" in sql
    assert "owner_id" not in json.dumps(result.serialize())
    assert "custom:handoff@alpha" not in json.dumps(result.serialize())
    assert "ULTRA_PRIVATE_PASSWORD" not in json.dumps(result.serialize())
    assert result.serialize()["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


@pytest.mark.parametrize("rows,reason", [
    ([], "owner_row_unavailable"),
    ([(0, 1, 1)], "owner_binding_unverified"),
    ([(1, 0, 1)], "owner_binding_unverified"),
    ([(1, 1, 0)], "owner_binding_unverified"),
    ([(1, 1, 1), (1, 1, 1)], "owner_rows_ambiguous"),
    ([("1", 1, 1)], "owner_result_invalid"),
    ([(True, 1, 1)], "owner_result_invalid"),
    ([(1, 1)], "owner_result_invalid"),
    ([(None, 1, 1)], "owner_result_invalid"),
])
def test_never_assert_owner_when_sql_row_missing_or_malformed(
        monkeypatch, tmp_path, rows, reason):
    trusted(monkeypatch)
    _, db = fake_odbc(monkeypatch, rows)
    result = owner.probe_handoff_local_owner(cfg(), project_root=tmp_path)
    assert result.status == "SKIP" and result.reason == reason
    assert result.evidence["local_owner_match_observed"] is False
    assert db.closes == db.c.closes == 1


def test_local_process_changes_during_sql_downgrades_result(tmp_path, monkeypatch):
    seen = []
    def provider(root):
        seen.append(root)
        return (222, "34", "custom-A") if len(seen) == 1 else (333, "35", "custom-A")
    monkeypatch.setattr(owner, "_trusted_local_owner", provider)
    _, db = fake_odbc(monkeypatch)
    result = owner.probe_handoff_local_owner(cfg(), project_root=tmp_path)
    assert result.status == "SKIP"
    assert result.reason == "owner_local_identity_changed"
    assert db.closes == db.c.closes == 1


def test_local_process_owner_changed_mid_sql_downgrades(tmp_path, monkeypatch):
    out = [(222, "34", "owner-A"), (222, "34", "owner-B")]
    monkeypatch.setattr(owner, "_trusted_local_owner", lambda root: out.pop(0))
    fake_odbc(monkeypatch)
    result = owner.probe_handoff_local_owner(cfg(), project_root=tmp_path)
    assert result.reason == "owner_local_identity_changed"


def test_missing_local_attestation_no_sql_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(owner, "_trusted_local_owner", lambda root: None)
    seen, _ = fake_odbc(monkeypatch)
    result = owner.probe_handoff_local_owner(cfg(), project_root=tmp_path)
    assert result.reason == "owner_local_identity_unverified"
    assert not seen


def test_driver_failure_and_sql_failure_both_redacted(tmp_path, monkeypatch):
    trusted(monkeypatch)
    seen, _ = fake_odbc(monkeypatch, driver=False)
    result = owner.probe_handoff_local_owner(cfg(), project_root=tmp_path)
    assert result.reason == "owner_driver_unavailable" and not seen
    seen, _ = fake_odbc(monkeypatch, fail=True)
    result = owner.probe_handoff_local_owner(cfg(), project_root=tmp_path)
    assert result.reason == "owner_sql_unverified"
    assert "SECRET" not in json.dumps(result.serialize())


@pytest.mark.parametrize("schema", [
    None, "", "sra_schedule]; DROP TABLE x", "dbo.private", "x" * 65,
    "[sra_schedule]", "é", "invalid whitespace",
])
def test_reject_untrusted_sql_schema_before_connection(
        tmp_path, monkeypatch, schema):
    seen, _ = fake_odbc(monkeypatch)
    result = owner.probe_handoff_local_owner(
        cfg(), project_root=tmp_path, schema=schema)
    assert result.reason == "owner_schema_invalid"
    assert not seen


def test_reject_public_host_before_proc_or_db(tmp_path, monkeypatch):
    seen, _ = fake_odbc(monkeypatch)
    monkeypatch.setattr(owner, "_trusted_local_owner",
                        lambda root: pytest.fail("no proc should be read"))
    result = owner.probe_handoff_local_owner(
        {**cfg(), "SRAF_OFF1G_SQL_HOST": "8.8.8.8"},
        project_root=tmp_path)
    assert result.reason == "owner_sql_config_invalid"
    assert not seen


@pytest.mark.parametrize("payload,expected", [
    (b"A=B\0REQUIREMENT_HANDOFF_OWNER_ID=handoff:node-01\0C=D\0",
     "handoff:node-01"),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=handoff-1\0",
     "handoff-1"),
    (b"A=B\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=owner a\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=owner\nx\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=" + b"a" * 129 + b"\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=ok\0REQUIREMENT_HANDOFF_OWNER_ID=evil\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=\xff\0", None),
    (b"REQUIREMENT_HANDOFF_OWNER_ID=owner", None),
])
def test_strict_initial_os_environment_parser(payload, expected):
    assert owner._parse_inherited_owner(payload) == expected


def test_bounded_proc_environ_reader_closes_fd(monkeypatch):
    raw = b"A=SECRET\0REQUIREMENT_HANDOFF_OWNER_ID=trusted\0"
    reads = []
    closed = []
    monkeypatch.setattr(owner.os, "open",
                        lambda path, flags: (reads.append((path, flags)) or 42))
    chunks = iter((raw, b""))
    monkeypatch.setattr(owner.os, "read", lambda fd, size: next(chunks))
    monkeypatch.setattr(owner.os, "close", lambda fd: closed.append(fd))
    assert owner._initial_owner_from_proc(1234) == "trusted"
    assert reads[0][0] == "/proc/1234/environ"
    assert closed == [42]


def test_oversized_proc_env_rejected(monkeypatch):
    monkeypatch.setattr(owner.os, "open", lambda path, flags: 42)
    chunks = iter((b"a" * (owner.ENV_MAX_BYTES + 1), b""))
    monkeypatch.setattr(owner.os, "read", lambda fd, size: next(chunks))
    monkeypatch.setattr(owner.os, "close", lambda fd: None)
    assert owner._initial_owner_from_proc(1234) is None


def test_trusted_identity_uses_fixed_path_and_two_canonical_checks(
        tmp_path, monkeypatch):
    canonical = []
    def verify(record, role, root):
        canonical.append((record, role, root))
        return {"role": "handoff", "alive": True, "pid": 4455,
                "process_start_time": "98765"}
    monkeypatch.setattr(owner, "verify_worker_identity", verify)
    monkeypatch.setattr(owner, "_initial_owner_from_proc",
                        lambda pid: "custom-worker-4455")
    local = owner._trusted_local_owner(tmp_path)
    assert local == (4455, "98765", "custom-worker-4455")
    assert canonical == [(tmp_path / owner.IDENTITY_FILE, "handoff", tmp_path)]
    assert owner._same_local_owner(tmp_path, local)
    assert len(canonical) == 2


def _observation(*, matched=True):
    return SimpleNamespace(
        check_id="LEASE-03", probe="handoff-local-owner",
        aspect="local_inherited_owner_matches_db_lease_only",
        status="PASS", executed=True,
        reason="owner_local_sql_match_observed",
        evidence={"local_owner_match_observed": matched},
    )


@pytest.mark.parametrize("flags,worker,renewal,expect", [
    ((False, False, False, False, False, False), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, False), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, True, True, False, True), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, True, False, True, True), "PASS", "PASS", "NOT_TESTED"),
    ((True, True, True, True, True, True), "SKIP", "PASS", "SKIP"),
    ((True, True, True, True, True, True), "PASS", "SKIP", "SKIP"),
    ((True, True, True, True, True, True), "PASS", "PASS", "PASS"),
])
def test_matrix_requires_six_flags_and_positive_both_dependencies(
        monkeypatch, flags, worker, renewal, expect):
    calls = []
    monkeypatch.setattr(matrix, "probe_handoff_local_owner",
                        lambda *a, **k: (calls.append((a, k)) or _observation()))
    row = matrix._handoff_local_owner(
        probe_network=flags[0], probe_sql_read=flags[1],
        probe_worker_lease=flags[2], probe_lease_renewal=flags[3],
        probe_worker_identities=flags[4], probe_handoff_owner=flags[5],
        worker_status=worker, renewal_status=renewal,
        sql_config=cfg(), lease_schema=None)
    assert row["status"] == expect
    assert row["feature_acceptance"] == "NOT_TESTED"
    assert row["depends_on"] == ["WORKERS", "HANDOFF-RENEWAL"]
    assert len(calls) == (1 if expect == "PASS" else 0)


def test_matrix_rejects_forged_nested_pass_and_error_leak(monkeypatch):
    kwargs = dict(probe_network=True, probe_sql_read=True,
                  probe_worker_lease=True, probe_lease_renewal=True,
                  probe_worker_identities=True, probe_handoff_owner=True,
                  worker_status="PASS", renewal_status="PASS",
                  sql_config=cfg(), lease_schema=None)
    monkeypatch.setattr(matrix, "probe_handoff_local_owner",
                        lambda *a, **k: _observation(matched=False))
    assert matrix._handoff_local_owner(**kwargs)["status"] == "SKIP"
    monkeypatch.setattr(matrix, "probe_handoff_local_owner",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("secret-private-owner-id")))
    row = matrix._handoff_local_owner(**kwargs)
    assert row["status"] == "SKIP"
    assert "private-owner-id" not in json.dumps(row)


def test_cli_owner_flag_alone_never_reads_proc_or_sql(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: {})
    monkeypatch.setattr(matrix, "_local_probe",
                        lambda k, c, a, f: matrix._record(
                            k, c, a, "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_tcp_probe",
                        lambda service, cfg, *, probe_network:
                        matrix._record({"api":"API-TCP","es":"ES-TCP",
                                        "llm":"LLM-TCP"}[service],
                                       service, "tcp", "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "_api_health",
                        lambda *a, **k: matrix._record(
                            "API-HEALTH", "api", "healthz_http_only",
                            "SKIP", "network_disabled"))
    monkeypatch.setattr(matrix, "probe_handoff_local_owner",
                        lambda *a, **k: pytest.fail("no SQL/proc authorized"))
    assert matrix.main(["--probe-handoff-owner"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["network_mode"] == "LOCAL_ONLY_NO_NETWORK"
    assert {r["id"]: r for r in data["results"]}["HANDOFF-OWNER"]["status"] == "NOT_TESTED"
    assert data["feature_acceptance"] == "NOT_TESTED"
