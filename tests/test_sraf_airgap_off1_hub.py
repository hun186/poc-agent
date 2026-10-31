"""Synthetic, no-network OFF-1 hub regression tests; never execute a live Job."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1_hub as hub


def _prepare(monkeypatch, tmp_path, *, suite_status="PASS", disk_status="PASS",
             odbc_status="SKIP", listener=True):
    monkeypatch.setattr(hub, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hub, "probe_disk", lambda: SimpleNamespace(
        status=disk_status, reason="disk_space_low" if disk_status != "PASS"
        else "disk_threshold_met"))
    monkeypatch.setattr(hub, "probe_odbc_library", lambda: SimpleNamespace(
        status=odbc_status, reason="odbc_library_unavailable"))
    monkeypatch.setattr(hub, "probe_worker_process_identities",
                        lambda root: SimpleNamespace(
                            status="PASS",
                            reason="worker_process_identities_verified",
                            evidence={"verified_role_count": 2}))
    monkeypatch.setattr(hub.report_jobs, "_effective_runtime_config", lambda root: {})
    monkeypatch.setattr(hub.report_jobs, "_api_bind_endpoint", lambda cfg: (
        {"configuration": "RESOLVED", "port": 9002}, "127.0.0.1"))
    calls = []
    def fake_quick(port, cfg, rows, suite, no_network):
        calls.append((suite, no_network))
        for name in ("api_health", "ui_page", "ui_javascript", "ui_stylesheet"):
            rows.append(hub.report_jobs._row(
                name, "SKIP" if no_network else suite_status,
                "network_disabled" if no_network else "asset_observed"))
        if suite == "diagnose":
            for name in ("tcp_api", "tcp_es", "tcp_llm"):
                rows.append(hub.report_jobs._row(
                    name, "SKIP" if no_network else suite_status,
                    "network_disabled" if no_network else "configured_tcp_connected"))
        rows.append(hub.report_jobs._row(
            "api_listener", "PASS" if listener and not no_network else "SKIP",
            "api_listener_attested" if listener and not no_network else "api_listener_unverified"))
        return object() if listener and not no_network else None
    monkeypatch.setattr(hub.report_jobs, "_quick", fake_quick)
    return calls


def _evidence(tmp_path):
    files = list((tmp_path / "private-output").glob("off1-hub-*.json"))
    assert len(files) == 1
    stat = files[0].stat()
    assert stat.st_mode & 0o777 == 0o600
    return json.loads(files[0].read_text(encoding="utf-8"))


def _run(tmp_path, *args):
    return hub.main(["--output-dir", str(tmp_path / "private-output"), *args])


def test_quick_is_readonly_partial_with_fixed_manual_gates(monkeypatch, tmp_path):
    calls = _prepare(monkeypatch, tmp_path)
    def forbidden(*a, **kw):
        raise AssertionError("live Report Job must never run by default")
    monkeypatch.setattr(hub.report_jobs, "_live", forbidden)
    assert _run(tmp_path) == 0
    evidence = _evidence(tmp_path)
    assert calls == [("quick", False)]
    assert evidence["result"] == "PASS_PARTIAL"
    assert evidence["exit_code"] == 0
    assert evidence["live_report_observation"] == "NOT_TESTED"
    assert evidence["production_release_ready"] is False
    assert evidence["full_airgap_acceptance"] == "NOT_TESTED"
    assert len(evidence["manual_gates"]) == len(hub.MANUAL_GATES) == 8
    assert all(g["status"] == "NOT_TESTED" for g in evidence["manual_gates"])
    assert evidence["counts"] == {"PASS": 6, "FAIL": 0, "SKIP": 1, "WARN": 0}
    assert "private" not in json.dumps(evidence).lower()


def test_readonly_diagnose_propagates_tcp_failure(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, suite_status="FAIL")
    assert _run(tmp_path, "--suite", "diagnose") == 1
    evidence = _evidence(tmp_path)
    assert evidence["result"] == "FAIL"
    assert evidence["counts"]["FAIL"] == 7
    assert all(g["status"] == "NOT_TESTED" for g in evidence["manual_gates"])


def test_without_network_always_incomplete_and_never_goes_live(monkeypatch, tmp_path):
    calls = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub.report_jobs, "_live", lambda *a, **kw: pytest.fail("live"))
    assert _run(tmp_path, "--suite", "diagnose", "--no-network") == 2
    evidence = _evidence(tmp_path)
    assert calls == [("diagnose", True)]
    assert evidence["result"] == "INCOMPLETE"
    assert evidence["network_mode"] == "NONE"
    assert evidence["counts"]["SKIP"] >= 9


def test_explicit_live_only_after_all_prerequisites(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    seen = []
    def fake_live(port, proof, args, rows, result_fd):
        seen.append((port, bool(proof), args.max_seconds, args.token_env))
        rows.append(hub.report_jobs._row("report_docx", "PASS", "docx_integrity_checked"))
        return 0
    monkeypatch.setattr(hub.report_jobs, "_live", fake_live)
    assert _run(tmp_path, "--live-report", "--token-env",
                "SRAF_OPERATOR_TEST", "--max-seconds", "180") == 0
    assert seen == [(9002, True, 180, "SRAF_OPERATOR_TEST")]
    assert _evidence(tmp_path)["live_report_observation"] == "OBSERVED_PARTIAL"


def test_failed_prerequisite_skips_live_without_credentials(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, disk_status="WARN")
    monkeypatch.setattr(hub.report_jobs, "_live", lambda *a, **kw: pytest.fail("live"))
    assert _run(tmp_path, "--live-report") == 2
    ev = _evidence(tmp_path)
    assert ev["live_report_observation"] == "INCOMPLETE"
    assert any(row["check"] == "live_report" and row["status"] == "SKIP"
               for row in ev["checks"])


def test_odbc_advisory_does_not_fake_sql_acceptance(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, odbc_status="WARN")
    assert _run(tmp_path) == 0
    ev = _evidence(tmp_path)
    assert ev["counts"]["WARN"] == 1
    assert next(g for g in ev["manual_gates"]
                if g["check"] == "sql_schema_source_permissions")["status"] == "NOT_TESTED"


def test_rejected_output_symlink_writes_no_evidence(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (tmp_path / "private-output").symlink_to(target, target_is_directory=True)
    assert _run(tmp_path) == 2
    assert list(target.iterdir()) == []


def test_no_network_and_live_are_incompatible(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, "--no-network", "--live-report")
    assert exc.value.code == 2
    assert not (tmp_path / "private-output").exists()


def test_unavailable_runtime_still_produces_incomplete_evidence(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    def fail(*a):
        raise OSError("PRIVATE_SECRET_RAW_PATH_MUST_NOT_LEAK")
    monkeypatch.setattr(hub.report_jobs, "_effective_runtime_config", fail)
    assert _run(tmp_path) == 2
    ev = _evidence(tmp_path)
    assert ev["result"] == "INCOMPLETE"
    assert any(r["reason"] == "operator_environment_or_transport_unavailable"
               for r in ev["checks"])
    assert "PRIVATE_SECRET" not in json.dumps(ev)


def test_diagnose_includes_off1h_worker_identity_without_full_acceptance(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    assert _run(tmp_path, "--suite", "diagnose") == 0
    evidence = _evidence(tmp_path)
    worker = next(r for r in evidence["checks"]
                  if r["check"] == "worker_process_identity")
    assert worker == {
        "check": "worker_process_identity", "status": "PASS",
        "reason": "worker_process_identities_verified", "verified_role_count": 2,
    }
    assert next(g for g in evidence["manual_gates"]
                if g["check"] == "schedule_handoff_workers")["status"] == "NOT_TESTED"
    assert evidence["production_release_ready"] is False


def test_quick_does_not_run_worker_observer(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "probe_worker_process_identities",
                        lambda *a: pytest.fail("quick must not inspect Workers"))
    assert _run(tmp_path) == 0
    assert not any(r["check"] == "worker_process_identity"
                   for r in _evidence(tmp_path)["checks"])


def test_diagnose_no_network_still_permits_local_proc_observation(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    touched = []
    def observe(root):
        touched.append(root)
        return SimpleNamespace(status="PASS", reason="worker_process_identities_verified",
                               evidence={"verified_role_count": 2})
    monkeypatch.setattr(hub, "probe_worker_process_identities", observe)
    assert _run(tmp_path, "--suite", "diagnose", "--no-network") == 2
    assert touched == [tmp_path]
    ev = _evidence(tmp_path)
    assert ev["network_mode"] == "NONE"
    assert any(r["check"] == "worker_process_identity" and r["status"] == "PASS"
               for r in ev["checks"])


def test_unverified_workers_are_advisory_not_fake_success(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "probe_worker_process_identities",
                        lambda root: SimpleNamespace(
                            status="SKIP", reason="worker_process_identity_unverified",
                            evidence={"verified_role_count": 1}))
    assert _run(tmp_path, "--suite", "diagnose") == 0
    ev = _evidence(tmp_path)
    assert next(r for r in ev["checks"]
                if r["check"] == "worker_process_identity")["status"] == "SKIP"
    assert next(g for g in ev["manual_gates"]
                if g["check"] == "schedule_handoff_workers")["status"] == "NOT_TESTED"


def test_worker_observer_errors_are_redacted(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    def failure(root):
        raise OSError("SECRET /proc/1234/cmdline --pass=fake")
    monkeypatch.setattr(hub, "probe_worker_process_identities", failure)
    assert _run(tmp_path, "--suite", "diagnose") == 0
    ev = _evidence(tmp_path)
    assert next(r for r in ev["checks"] if r["check"] == "worker_process_identity") == {
        "check": "worker_process_identity", "status": "SKIP",
        "reason": "worker_process_identity_unverified", "verified_role_count": 0,
    }
    assert "SECRET" not in json.dumps(ev)


def test_invalid_worker_probe_status_cannot_be_trusted(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "probe_worker_process_identities",
                        lambda root: SimpleNamespace(
                            status="PASS", reason="unvalidated_reason_with_secret",
                            evidence={"verified_role_count": 2}))
    assert _run(tmp_path, "--suite", "diagnose") == 0
    ev = _evidence(tmp_path)
    worker = next(r for r in ev["checks"] if r["check"] == "worker_process_identity")
    assert worker["status"] == "SKIP"
    assert "unvalidated_reason_with_secret" not in json.dumps(ev)


def test_contradictory_pass_and_bad_role_count_fail_closed(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "probe_worker_process_identities",
                        lambda root: SimpleNamespace(
                            status="PASS", reason="worker_process_identities_verified",
                            evidence={"verified_role_count": 1}))
    assert _run(tmp_path, "--suite", "diagnose") == 0
    ev = _evidence(tmp_path)
    worker = next(r for r in ev["checks"] if r["check"] == "worker_process_identity")
    assert worker["status"] == "SKIP"
    assert worker["verified_role_count"] == 0
    assert next(g for g in ev["manual_gates"]
                if g["check"] == "schedule_handoff_workers")["status"] == "NOT_TESTED"


def test_es_strict_probe_is_never_triggered_without_explicit_flag(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "strict_mapping_observation",
                        lambda *a: pytest.fail("credentials must remain untouched"))
    assert _run(tmp_path) == 0
    assert _run(tmp_path, "--suite", "diagnose") == 0
    # Different output timestamps for quick and diagnose are allowed; no ES probe called.


@pytest.mark.parametrize("args", [
    ("--probe-es-tls-mapping",),
    ("--suite", "quick", "--probe-es-tls-mapping"),
    ("--suite", "diagnose", "--no-network", "--probe-es-tls-mapping"),
    ("--suite", "diagnose", "--live-report", "--probe-es-tls-mapping"),
])
def test_strict_es_flag_requires_separate_safe_diagnose_mode(
        monkeypatch, tmp_path, args):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "strict_mapping_observation",
                        lambda *a: pytest.fail("invalid mode touched ES"))
    with pytest.raises(SystemExit) as err:
        _run(tmp_path, *args)
    assert err.value.code == 2
    assert not (tmp_path / "private-output").exists()


def test_explicit_es_strict_partial_maintains_manual_gate(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    calls = []
    def observe(cfg, root):
        calls.append((cfg, root))
        return {"check": "es_strict_tls_mapping", "status": "SKIP",
                "reason": "es_tls_mapping_observed_auth_not_verified",
                "https_probe": "PASS", "tls_validation": "PASS",
                "mapping_probe": "PASS", "auth": "NOT_VERIFIED",
                "credential_control": "NOT_RUN"}
    monkeypatch.setattr(hub, "strict_mapping_observation", observe)
    assert _run(tmp_path, "--suite", "diagnose", "--probe-es-tls-mapping") == 2
    ev = _evidence(tmp_path)
    assert calls == [({}, tmp_path)]
    assert ev["result"] == "INCOMPLETE"
    assert next(r for r in ev["checks"] if r["check"] == "es_strict_tls_mapping") == observe({}, tmp_path)
    assert next(g for g in ev["manual_gates"]
                if g["check"] == "es_tls_ca_san_mapping")["status"] == "NOT_TESTED"
    assert ev["production_release_ready"] is False


def test_explicit_es_strict_failure_propagates(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "strict_mapping_observation",
                        lambda cfg, root: {
                            "check": "es_strict_tls_mapping", "status": "FAIL",
                            "reason": "es_tls_identity_failed",
                            "https_probe": "FAIL", "tls_validation": "FAIL",
                            "mapping_probe": "SKIP", "auth": "NOT_TESTED",
                            "credential_control": "NOT_RUN",
                        })
    assert _run(tmp_path, "--suite", "diagnose", "--probe-es-tls-mapping") == 1
    ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL"
    assert ev["counts"]["FAIL"] == 1


def test_sql_read_not_invoked_without_explicit_flag(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "sql_constant_read_observation",
                        lambda: pytest.fail("default must not inspect SQL credentials"))
    assert _run(tmp_path, "--suite", "diagnose") == 0


@pytest.mark.parametrize("args", [
    ("--probe-sql-read",),
    ("--suite", "quick", "--probe-sql-read"),
    ("--suite", "diagnose", "--no-network", "--probe-sql-read"),
    ("--suite", "diagnose", "--live-report", "--probe-sql-read"),
])
def test_sql_read_requires_explicit_diagnose_network_no_live(monkeypatch, tmp_path, args):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "sql_constant_read_observation",
                        lambda: pytest.fail("forbidden flag combination"))
    with pytest.raises(SystemExit) as err:
        _run(tmp_path, *args)
    assert err.value.code == 2
    assert not (tmp_path / "private-output").exists()


def test_sql_read_pass_is_partial_and_schema_not_tested(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    called = []
    def probe():
        called.append(True)
        return {"check": "sql_constant_read", "status": "PASS",
                "reason": "sql_constant_select_observed",
                "constant_select_observed": True}
    monkeypatch.setattr(hub, "sql_constant_read_observation", probe)
    assert _run(tmp_path, "--suite", "diagnose", "--probe-sql-read") == 0
    ev = _evidence(tmp_path)
    assert called == [True]
    assert ev["result"] == "PASS_PARTIAL"
    assert next(r for r in ev["checks"] if r["check"] == "sql_constant_read")["status"] == "PASS"
    assert next(g for g in ev["manual_gates"]
                if g["check"] == "sql_schema_source_permissions")["status"] == "NOT_TESTED"
    assert ev["production_release_ready"] is False


@pytest.mark.parametrize("status,reason,expected", [
    ("SKIP", "sql_read_config_invalid", 2),
    ("FAIL", "sql_read_response_invalid", 1),
])
def test_sql_read_incomplete_or_failure_propagates(monkeypatch, tmp_path,
                                                  status, reason, expected):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "sql_constant_read_observation",
                        lambda: {"check": "sql_constant_read", "status": status,
                                 "reason": reason, "constant_select_observed": False})
    assert _run(tmp_path, "--suite", "diagnose", "--probe-sql-read") == expected
    ev = _evidence(tmp_path)
    assert ev["exit_code"] == expected
    assert next(g for g in ev["manual_gates"]
                if g["check"] == "sql_schema_source_permissions")["status"] == "NOT_TESTED"


def test_sql_read_independent_of_unavailable_api_endpoint(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(hub, "sql_constant_read_observation",
                        lambda: (calls.append("sql") or {
                            "check": "sql_constant_read", "status": "PASS",
                            "reason": "sql_constant_select_observed",
                            "constant_select_observed": True}))
    monkeypatch.setattr(hub.report_jobs, "_api_bind_endpoint",
                        lambda cfg: ({"configuration": "INVALID"}, None))
    assert _run(tmp_path, "--suite", "diagnose", "--probe-sql-read") == 1
    ev = _evidence(tmp_path)
    assert calls == ["sql"]
    assert any(r["check"] == "sql_constant_read" for r in ev["checks"])
    assert any(r["check"] == "operator" for r in ev["checks"])


@pytest.mark.parametrize("flag,check,reason,manual_gate", [
    ("--probe-sql-read", "sql_constant_read", "sql_read_response_invalid",
     "sql_schema_source_permissions"),
    ("--probe-es-tls-mapping", "es_strict_tls_mapping", "es_tls_identity_failed",
     "es_tls_ca_san_mapping"),
])
def test_database_failure_survives_later_runtime_configuration_error(
        monkeypatch, tmp_path, flag, check, reason, manual_gate):
    """Codex P2: later APP_ENV errors cannot turn observed DB FAIL into exit 2."""
    _prepare(monkeypatch, tmp_path)
    failure = {"check": check, "status": "FAIL", "reason": reason}
    if flag == "--probe-sql-read":
        failure["constant_select_observed"] = False
        monkeypatch.setattr(hub, "sql_constant_read_observation",
                            lambda: dict(failure))
    else:
        failure.update(https_probe="FAIL", tls_validation="FAIL",
                       mapping_probe="SKIP", auth="NOT_TESTED",
                       credential_control="NOT_RUN")
        monkeypatch.setattr(hub, "strict_mapping_observation",
                            lambda cfg, root: dict(failure))
    def later_runtime_failure(root):
        raise ValueError("APP_ENV invalid; SECRET_SQL_USER_NOT_FOR_LOGGING")
    # SQL executes before _effective_runtime_config. ES must instead be
    # exercised after the config but before the subsequent API error.
    if flag == "--probe-es-tls-mapping":
        monkeypatch.setattr(hub.report_jobs, "_api_bind_endpoint",
                            lambda cfg: (_ for _ in ()).throw(
                                ValueError("SECRET_API_CONFIG")))
    else:
        monkeypatch.setattr(hub.report_jobs, "_effective_runtime_config",
                            later_runtime_failure)
    assert _run(tmp_path, "--suite", "diagnose", flag) == 1
    ev = _evidence(tmp_path)
    assert ev["result"] == "FAIL"
    assert ev["exit_code"] == 1
    assert any(row["check"] == check and row["status"] == "FAIL"
               for row in ev["checks"])
    assert next(g for g in ev["manual_gates"] if g["check"] == manual_gate)[
        "status"] == "NOT_TESTED"
    assert "SECRET" not in json.dumps(ev)


def test_sql_incomplete_is_not_promoted_after_runtime_config_error(
        monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "sql_constant_read_observation",
                        lambda: {"check": "sql_constant_read", "status": "SKIP",
                                 "reason": "sql_read_connection_unverified",
                                 "constant_select_observed": False})
    monkeypatch.setattr(hub.report_jobs, "_effective_runtime_config",
                        lambda root: (_ for _ in ()).throw(ValueError("SECRET")))
    assert _run(tmp_path, "--suite", "diagnose", "--probe-sql-read") == 2
    evidence = _evidence(tmp_path)
    assert evidence["result"] == "INCOMPLETE"
    assert evidence["exit_code"] == 2
    assert "SECRET" not in json.dumps(evidence)
