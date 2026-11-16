"""Synthetic no-network, no-write startup retry regression gates."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools import sraf_worker_startup_transition as starting
from tools import sraf_worker_identity_detail_readonly as detail
from tools import sraf_operator_diagnostics as operator


def _identity_fixture(tmp_path, *, mode=0o600):
    (tmp_path / "run_sra_api.sh").write_text("#!/bin/bash\n")
    uid = os.geteuid()
    (tmp_path / starting.LAUNCHER_RECORD).write_text(
        f"pid=1234\nprocess_start_time=1000\neffective_uid={uid}\n"
        f"cwd={tmp_path}\nlauncher_path={tmp_path}/run_sra_api.sh\n"
    )
    (tmp_path / starting.LAUNCHER_RECORD).chmod(mode)


def _fake_proc(monkeypatch, root, *, age=40, exe="bash", pid_tick="1000",
               argv=None, effective_uid=None, cwd=None):
    uid = os.geteuid() if effective_uid is None else effective_uid
    if argv is None:
        argv = ["bash", "./run_sra_api.sh"]
    encoded = b"\0".join(a.encode() for a in argv) + b"\0"
    def read_limited(path, limit=starting.MAX_READ):
        name = str(path)
        if name == "/proc/1234/status":
            return f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n".encode()
        if name == "/proc/1234/cmdline":
            return encoded
        if name == "/proc/uptime":
            return f"{10 + age}.00 10.00\n".encode()
        raise AssertionError(f"unexpected read: {name}")
    monkeypatch.setattr(starting, "_read_limited", read_limited)
    monkeypatch.setattr(starting, "_proc_start", lambda pid: pid_tick)
    monkeypatch.setattr(starting, "_proc_executable", lambda pid: exe)
    monkeypatch.setattr(starting, "_proc_cwd_stat",
                        lambda pid: (cwd or root).stat())
    monkeypatch.setattr(starting.os, "sysconf", lambda name: 100)


def _pending():
    return {
        "id": "worker_process_identity",
        "status": "INCOMPLETE",
        "reason": "worker_process_identity_unverified",
        "verified_role_count": 0,
    }


def _passed():
    return {
        "id": "worker_process_identity",
        "status": "PASS_PARTIAL",
        "reason": "recorded_schedule_handoff_process_identity_only",
        "verified_role_count": 2,
    }


def test_recent_launcher_requires_bound_identity_and_live_process(
        tmp_path, monkeypatch):
    _identity_fixture(tmp_path)
    _fake_proc(monkeypatch, tmp_path)
    assert starting.recent_verified_launcher(tmp_path) is True


@pytest.mark.parametrize("mutation", [
    "too_old", "other_exe", "wrong_tick", "wrong_uid", "wrong_argv",
    "wrong_cwd", "unsafe_permissions", "missing_record", "symlink_record",
])
def test_launcher_proof_fails_closed(tmp_path, monkeypatch, mutation):
    _identity_fixture(tmp_path)
    kwargs = {}
    if mutation == "too_old":
        kwargs["age"] = 200
    if mutation == "other_exe":
        kwargs["exe"] = "python"
    if mutation == "wrong_tick":
        kwargs["pid_tick"] = "1001"
    if mutation == "wrong_uid":
        kwargs["effective_uid"] = os.geteuid() + 1
    if mutation == "wrong_argv":
        kwargs["argv"] = ["bash", "-c", "run_sra_api.sh"]
    if mutation == "wrong_cwd":
        other = tmp_path / "other"
        other.mkdir()
        kwargs["cwd"] = other
    _fake_proc(monkeypatch, tmp_path, **kwargs)
    record = tmp_path / starting.LAUNCHER_RECORD
    if mutation == "unsafe_permissions":
        record.chmod(0o644)
    if mutation == "missing_record":
        record.unlink()
    if mutation == "symlink_record":
        target = tmp_path / "other-record"
        record.rename(target)
        record.symlink_to(target)
    assert starting.recent_verified_launcher(tmp_path) is False


def test_starting_requires_only_missing_or_canonically_verified_roles(
        tmp_path, monkeypatch):
    monkeypatch.setattr(starting, "recent_verified_launcher", lambda root: True)
    def fake(statuses):
        return {"roles": {
            role: {"status": status, "reason": reason}
            for role, (status, reason) in zip(("schedule", "handoff"), statuses)
        }}
    monkeypatch.setattr(detail, "inspect_workers",
                        lambda root: fake([
                            ("UNVERIFIED", "identity_file_missing"),
                            ("VERIFIED", "canonical_verified")]))
    assert starting.confirmed_starting(tmp_path) is True
    monkeypatch.setattr(detail, "inspect_workers",
                        lambda root: fake([
                            ("UNVERIFIED", "identity_file_missing"),
                            ("UNVERIFIED", "process_command_role_mismatch")]))
    assert starting.confirmed_starting(tmp_path) is False
    monkeypatch.setattr(detail, "inspect_workers",
                        lambda root: fake([
                            ("VERIFIED", "canonical_verified"),
                            ("VERIFIED", "canonical_verified")]))
    assert starting.confirmed_starting(tmp_path) is False


def test_normal_runtime_never_waits_or_rechecks(tmp_path, monkeypatch):
    monkeypatch.setattr(starting, "confirmed_starting",
                        lambda root: pytest.fail("should not inspect healthy worker"))
    assert starting.retry_worker_row(
        tmp_path, _passed(), lambda root: pytest.fail("no duplicate probe"),
        sleep=lambda seconds: pytest.fail("no sleep")) == _passed()


def test_unverified_launcher_never_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(starting, "confirmed_starting", lambda root: False)
    result = starting.retry_worker_row(
        tmp_path, _pending(), lambda root: pytest.fail("not authorized"),
        sleep=lambda seconds: pytest.fail("not authorized"))
    assert result == _pending()


def test_startup_retry_recovers_only_from_canonical_worker_pass(
        tmp_path, monkeypatch):
    monkeypatch.setattr(starting, "confirmed_starting", lambda root: True)
    calls = []
    def probe(root):
        calls.append("probe")
        return _passed() if len(calls) == 2 else _pending()
    sleeps = []
    result = starting.retry_worker_row(
        tmp_path, _pending(), probe, sleep=lambda seconds: sleeps.append(seconds))
    assert result["status"] == "PASS_PARTIAL"
    assert result["startup_phase"] == "STARTING"
    assert result["startup_retry_result"] == "RECOVERED"
    assert result["startup_retry_attempts"] == 2
    assert result["reason"] == "worker_process_identities_verified_after_startup_retry"
    assert sleeps == [2, 2]
    assert calls == ["probe", "probe"]


def test_startup_timeout_keeps_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(starting, "confirmed_starting", lambda root: True)
    observed = []
    result = starting.retry_worker_row(
        tmp_path, _pending(), lambda root: _pending(),
        sleep=lambda seconds: observed.append(seconds))
    assert len(observed) == 6
    assert sum(observed) == 12
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "worker_startup_retry_exhausted"
    assert result["startup_phase"] == "STARTING"
    assert result["startup_retry_attempts"] == 6


def test_mismatched_worker_terminates_retry_without_success(
        tmp_path, monkeypatch):
    observations = iter((True, False))
    monkeypatch.setattr(starting, "confirmed_starting", lambda root: next(observations))
    result = starting.retry_worker_row(
        tmp_path, _pending(), lambda root: _pending(),
        sleep=lambda seconds: None)
    assert result["status"] == "INCOMPLETE"
    assert result["startup_retry_result"] == "UNVERIFIED"
    assert result["startup_retry_attempts"] == 1


def test_worker_completes_between_probe_and_starting_gate(tmp_path, monkeypatch):
    """The stale first probe must not hide a real canonical readiness recovery."""
    transitions = iter((True, False))
    monkeypatch.setattr(starting, "confirmed_starting",
                        lambda root: next(transitions))
    results = iter((_pending(), _passed()))
    calls = []
    def canonical_probe(root):
        calls.append("canonical")
        return next(results)
    report = starting.retry_worker_row(
        tmp_path, _pending(), canonical_probe, sleep=lambda seconds: None)
    assert calls == ["canonical", "canonical"]
    assert report["status"] == "PASS_PARTIAL"
    assert report["reason"] == "worker_process_identities_verified_after_startup_retry"
    assert report["startup_retry_attempts"] == 1
    assert report["startup_phase"] == "STARTING"


def test_invalid_identity_still_fails_after_boundary_recheck(tmp_path, monkeypatch):
    transitions = iter((True, False))
    monkeypatch.setattr(starting, "confirmed_starting",
                        lambda root: next(transitions))
    calls = []
    def canonical_probe(root):
        calls.append("canonical")
        return {
            **_pending(),
            "reason": "worker_process_identity_unverified",
        }
    report = starting.retry_worker_row(
        tmp_path, _pending(), canonical_probe, sleep=lambda seconds: None)
    assert calls == ["canonical", "canonical"]
    assert report["status"] == "INCOMPLETE"
    assert report["startup_retry_result"] == "UNVERIFIED"


def test_partial_or_forged_result_not_promoted_to_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(starting, "confirmed_starting", lambda root: True)
    suspect = {**_passed(), "verified_role_count": 1}
    result = starting.retry_worker_row(
        tmp_path, _pending(), lambda root: suspect, sleep=lambda seconds: None)
    assert result["status"] == "INCOMPLETE"


def test_integrated_operator_local_rows_recheck_only_worker(
        monkeypatch, tmp_path):
    from tools import sraf_local_deploy_quickcheck as quick
    monkeypatch.setattr(operator, "ROOT", tmp_path)
    checks = []
    for name in operator.L0_CHECKS:
        checks.append({
            "id": name,
            "status": "INCOMPLETE" if name == "worker_process_identity" else "PASS_PARTIAL",
            "reason": "worker_process_identity_unverified"
                if name == "worker_process_identity" else "observed",
        })
    monkeypatch.setattr(quick, "observe", lambda root, *, api_port: {
        "schema": quick.SCHEMA, "status": "INCOMPLETE", "checks": checks})
    monkeypatch.setattr(starting, "retry_worker_row",
                        lambda root, initial, probe: {
                            **_passed(),
                            "reason": "worker_process_identities_verified_after_startup_retry",
                            "startup_phase": "STARTING",
                            "startup_retry_result": "RECOVERED",
                            "startup_retry_attempts": 2,
                        })
    status, rows = operator._local_rows(None)
    assert status == "PASS_PARTIAL"
    worker = next(r for r in rows if r["id"] == "L0.worker_process_identity")
    assert worker["status"] == "PASS_PARTIAL"
    assert worker["startup_phase"] == "STARTING"
    assert worker["startup_retry_result"] == "RECOVERED"


def test_chinese_report_explains_startup_without_claiming_live_e2e():
    from tools.sraf_diagnostics_report import render_report
    rows = [
        operator._row("L0." + n, "PASS_PARTIAL",
                      "worker_process_identities_verified_after_startup_retry"
                      if n == "worker_process_identity" else "observed")
        for n in operator.L0_CHECKS
    ]
    rows.extend(operator._row("L1." + n, "PASS", "configured_tcp_connected")
                for n in operator.L1_CHECKS)
    rows.extend(operator._row("L2." + n, "NOT_TESTED", "probe_not_requested")
                for n in operator.L2_CHECKS)
    rows.extend(operator._row("L3." + n, "NOT_TESTED", "probe_not_requested")
                for n in ("report_job_docx", "requirement_schedule_handoff_e2e"))
    report = render_report({"level": "L1", "status": "PASS_PARTIAL", "checks": rows})
    assert "STARTING" in report
    assert "不代表業務執行已驗收" in report
    assert "FULL_LIVE" in report
