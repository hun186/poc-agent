"""OFF-1H Worker identity: canonical real /proc verifier, fail closed by default."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from operator_e2e import requirement_e2e_support as canonical
from tools import sraf_airgap_off1h_worker_identity as worker
from tools import sraf_airgap_off1d_readiness_matrix as matrix


def _identity(root, role):
    path = root / worker.IDENTITY_FILES[role]
    path.write_text(f"role={role}\npid=1234\nprocess_start_time=98765\n")
    path.chmod(0o600)
    return path


def _prepare(tmp_path):
    for role in ("schedule", "handoff"):
        _identity(tmp_path, role)
    return tmp_path


def _canonical(monkeypatch, *, overrides=None):
    calls = []
    overrides = overrides or {}
    def verify(path, role, project_root):
        calls.append((path, role, project_root))
        assert path == project_root / worker.IDENTITY_FILES[role]
        if role in overrides:
            value = overrides[role]
            if isinstance(value, Exception):
                raise value
            return value
        return {"role": role, "pid": 1001 if role == "schedule" else 1002,
                "process_start_time": "98765", "alive": True}
    monkeypatch.setattr(worker, "verify_worker_identity", verify)
    return calls


def test_two_worker_identities_are_verified_using_canonical_code(
        tmp_path, monkeypatch):
    root = _prepare(tmp_path)
    calls = _canonical(monkeypatch)
    result = worker.probe_worker_process_identities(root)
    assert result.status == "PASS"
    assert result.executed is True
    assert result.reason == "worker_process_identities_verified"
    assert result.evidence == {"verified_role_count": 2}
    assert [role for _, role, _ in calls] == ["schedule", "handoff"]
    assert "1234" not in json.dumps(result.serialize())
    assert str(root) not in json.dumps(result.serialize())
    assert "98765" not in json.dumps(result.serialize())
    assert result.serialize()["mode"] == "PARTIAL_ONLY_NOT_ACCEPTANCE"


@pytest.mark.parametrize("role", ["schedule", "handoff"])
def test_absent_identity_is_not_positive(tmp_path, monkeypatch, role):
    root = _prepare(tmp_path)
    (root / worker.IDENTITY_FILES[role]).unlink()
    _canonical(monkeypatch)
    result = worker.probe_worker_process_identities(root)
    assert result.status == "SKIP"
    assert result.reason == "worker_process_identity_unverified"
    assert result.evidence["verified_role_count"] == (
        0 if role == "schedule" else 1)


@pytest.mark.parametrize("role", ["schedule", "handoff"])
def test_identity_symlink_must_not_reach_canonical_verifier(
        tmp_path, monkeypatch, role):
    root = _prepare(tmp_path)
    identity = root / worker.IDENTITY_FILES[role]
    identity.unlink()
    identity.symlink_to(root / worker.IDENTITY_FILES[
        "handoff" if role == "schedule" else "schedule"])
    calls = _canonical(monkeypatch)
    result = worker.probe_worker_process_identities(root)
    assert result.status == "SKIP"
    assert [item[1] for item in calls] == (
        [] if role == "schedule" else ["schedule"])


def test_unbounded_identity_file_is_rejected(tmp_path, monkeypatch):
    root = _prepare(tmp_path)
    (root / worker.IDENTITY_FILES["handoff"]).write_bytes(b"x" * 500)
    calls = _canonical(monkeypatch)
    result = worker.probe_worker_process_identities(root)
    assert result.status == "SKIP"
    assert [c[1] for c in calls] == ["schedule"]


@pytest.mark.parametrize("bad_value", [
    {"role": "handoff", "pid": 222, "process_start_time": "42", "alive": True},
    {"role": "schedule", "pid": 0, "process_start_time": "42", "alive": True},
    {"role": "schedule", "pid": True, "process_start_time": "42", "alive": True},
    {"role": "schedule", "pid": 333, "process_start_time": "-1", "alive": True},
    {"role": "schedule", "pid": 333, "process_start_time": "42", "alive": False},
    {"role": "schedule", "pid": 333, "process_start_time": 42, "alive": True},
    None,
    RuntimeError("SECRET worker path /srv/private"),
])
def test_forged_or_invalid_canonical_schedule_never_passes(
        tmp_path, monkeypatch, bad_value):
    root = _prepare(tmp_path)
    _canonical(monkeypatch, overrides={"schedule": bad_value})
    result = worker.probe_worker_process_identities(root)
    assert result.status == "SKIP"
    assert result.executed
    assert "SECRET" not in json.dumps(result.serialize())
    assert result.evidence["verified_role_count"] == 0


def test_both_roles_must_not_share_one_pid(tmp_path, monkeypatch):
    root = _prepare(tmp_path)
    _canonical(monkeypatch, overrides={
        "handoff": {"role": "handoff", "pid": 1001,
                    "process_start_time": "98765", "alive": True}
    })
    result = worker.probe_worker_process_identities(root)
    assert result.status == "SKIP"
    assert result.evidence["verified_role_count"] == 1


def test_non_linux_or_non_root_never_reads_identities(tmp_path, monkeypatch):
    monkeypatch.setattr(worker.sys, "platform", "win32")
    monkeypatch.setattr(worker, "verify_worker_identity",
                        lambda *a: pytest.fail("unsupported platform"))
    result = worker.probe_worker_process_identities(tmp_path)
    assert result.status == "SKIP" and not result.executed
    assert result.reason == "worker_process_host_unsupported"


def test_matrix_independent_local_opt_in_redacts_nested_provider(monkeypatch):
    observations = []
    def nested(root):
        observations.append(root)
        return SimpleNamespace(
            status="PASS", reason="worker_process_identities_verified",
            check_id="WORKER-01", probe="worker-identities",
            aspect="schedule_handoff_process_identity_only",
            executed=True, evidence={"verified_role_count": 2},
        )
    monkeypatch.setattr(matrix, "probe_worker_process_identities", nested)
    assert matrix._worker_identities(probe_worker_identities=False)["status"] == "NOT_TESTED"
    assert observations == []
    row = matrix._worker_identities(probe_worker_identities=True)
    assert row["status"] == "PASS"
    assert row["aspect"] == "schedule_handoff_process_identity_only"
    assert row["feature_acceptance"] == "NOT_TESTED"
    assert row["depends_on"] == ["API-HEALTH", "SQL-READ"]
    assert len(observations) == 1


@pytest.mark.parametrize("bad", [
    {"verified_role_count": 1}, {"verified_role_count": True},
    {"verified_role_count": "2"},
])
def test_forged_nested_pass_is_downgraded(monkeypatch, bad):
    monkeypatch.setattr(
        matrix, "probe_worker_process_identities",
        lambda root: SimpleNamespace(
            status="PASS", reason="worker_process_identities_verified",
            check_id="WORKER-01", probe="worker-identities",
            aspect="schedule_handoff_process_identity_only",
            executed=True, evidence=bad,
        ),
    )
    row = matrix._worker_identities(probe_worker_identities=True)
    assert row["status"] == "SKIP"
    assert row["reason"] == "unexpected_probe_result"


def test_nested_worker_error_does_not_leak_native_details(monkeypatch):
    monkeypatch.setattr(matrix, "probe_worker_process_identities",
                        lambda root: (_ for _ in ()).throw(
                            RuntimeError("PRIVATE PID command line")))
    row = matrix._worker_identities(probe_worker_identities=True)
    assert row["status"] == "SKIP"
    assert "PRIVATE" not in json.dumps(row)


def test_cli_default_is_off_and_explicit_identity_flag_never_requests_network(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(matrix, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(matrix.tcp, "_effective_runtime_config",
                        lambda root: {})
    monkeypatch.setattr(
        matrix, "_local_probe",
        lambda key, component, aspect, fn:
        matrix._record(key, component, aspect, "SKIP", "network_disabled"),
    )
    monkeypatch.setattr(
        matrix, "_tcp_probe",
        lambda service, cfg, *, probe_network:
        matrix._record(
            {"api": "API-TCP", "es": "ES-TCP", "llm": "LLM-TCP"}[service],
            service, "configured_tcp_only", "SKIP", "network_disabled"),
    )
    monkeypatch.setattr(
        matrix, "_api_health",
        lambda *a, **k: matrix._record("API-HEALTH", "api",
                                       "healthz_http_only", "SKIP",
                                       "network_disabled"),
    )
    called = []
    def probe(root):
        called.append(root)
        return SimpleNamespace(
            status="SKIP", reason="worker_process_identity_unverified",
            executed=True,
        )
    monkeypatch.setattr(matrix, "probe_worker_process_identities", probe)
    assert matrix.main([]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["network_mode"] == "LOCAL_ONLY_NO_NETWORK"
    assert {r["id"]: r for r in report["results"]}["WORKERS"]["status"] == "NOT_TESTED"
    assert called == []
    assert matrix.main(["--probe-worker-identities"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["network_mode"] == "LOCAL_ONLY_NO_NETWORK"
    assert {r["id"]: r for r in report["results"]}["WORKERS"]["status"] == "SKIP"
    assert called == [tmp_path]
    assert report["feature_acceptance"] == "NOT_TESTED"


def _stub_proc(monkeypatch, root):
    monkeypatch.setattr(canonical, "_proc_start_time", lambda pid: "98765")
    monkeypatch.setattr(canonical, "_proc_uid", lambda pid: os.geteuid())
    monkeypatch.setattr(canonical, "_proc_cwd", lambda pid: root)
    monkeypatch.setattr(canonical, "_worker_argv_matches",
                        lambda pid, role: pid in (1234, 5678) and role in ("schedule", "handoff"))


def test_canonical_fd_bound_identity_matches_real_inode(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    record = _identity(root, "schedule")
    _stub_proc(monkeypatch, root)
    info = canonical.verify_worker_identity(record, "schedule", root)
    assert info["role"] == "schedule"
    assert info["pid"] == 1234
    assert info["alive"] is True


def test_canonical_symlink_and_fifo_never_read_or_hang(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    record = _identity(root, "schedule")
    _stub_proc(monkeypatch, root)
    target = root / "secret"
    target.write_text(record.read_text())
    record.unlink()
    record.symlink_to(target)
    with pytest.raises(canonical.HarnessFailure) as exc:
        canonical.verify_worker_identity(record, "schedule", root)
    assert exc.value.category == "worker_unavailable"
    record.unlink()
    os.mkfifo(record)
    with pytest.raises(canonical.HarnessFailure) as exc:
        canonical.verify_worker_identity(record, "schedule", root)
    assert exc.value.category == "worker_unavailable"


def test_canonical_post_directory_open_swap_to_symlink_fails_closed(
        tmp_path, monkeypatch):
    root = tmp_path.resolve()
    record = _identity(root, "schedule")
    _stub_proc(monkeypatch, root)
    external = root / "other.txt"
    external.write_text(record.read_text())
    real_open = os.open
    swapped = []
    def substitute_open(path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is not None and not swapped:
            swapped.append(True)
            record.unlink()
            record.symlink_to(external)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(canonical.os, "open", substitute_open)
    with pytest.raises(canonical.HarnessFailure):
        canonical.verify_worker_identity(record, "schedule", root)
    assert swapped == [True]


def test_canonical_oversized_and_duplicate_record_rejected(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    record = _identity(root, "schedule")
    _stub_proc(monkeypatch, root)
    for data in (b"x" * 300,
                 b"role=schedule\npid=1234\npid=1234\nprocess_start_time=98765\n",
                 b"role=schedule\npid=1234\nprocess_start_time=98765"):
        record.write_bytes(data)
        with pytest.raises(canonical.HarnessFailure):
            canonical.verify_worker_identity(record, "schedule", root)


def _raw_argv(*args):
    return b"\0".join(arg.encode("utf-8") for arg in args) + b"\0"


@pytest.mark.parametrize("argv,expected", [
    (["python", "-c", canonical._UNIFIED_WORKER_BOOTSTRAP, "schedule-worker"], True),
    (["python3.11", "-m", "requirement_scheduler.cli", "schedule-worker"], True),
    (["python3", "-m", "requirement_scheduler", "schedule-worker"], True),
    (["python", "-c", "import time; time.sleep(60)",
      "requirement_scheduler.cli", "schedule-worker"], False),
    (["python", "-c", "import time; time.sleep(60)",
      "schedule-worker requirement_scheduler.cli"], False),
    (["python", "-c", canonical._UNIFIED_WORKER_BOOTSTRAP, "handoff-worker"], False),
    (["python", "-m", "other.script", "schedule-worker"], False),
    (["bash", "-m", "requirement_scheduler.cli", "schedule-worker"], False),
    (["python", "-c", canonical._UNIFIED_WORKER_BOOTSTRAP,
      "schedule-worker", "--unused"], False),
])
def test_canonical_exact_nul_delimited_argv_not_substring_spoofed(
        monkeypatch, argv, expected):
    content = _raw_argv(*argv)
    monkeypatch.setattr(canonical, "open", lambda *a, **k: io.BytesIO(content),
                        raising=False)
    assert canonical._worker_argv_matches(1234, "schedule") is expected


@pytest.mark.parametrize("contents", [
    b"",
    b"a" * (canonical._WORKER_ARGV_MAX_BYTES + 1),
    b"python\0-m\0requirement_scheduler.cli\0schedule-worker",
    b"\xff\0-m\0requirement_scheduler.cli\0schedule-worker\0",
])
def test_canonical_malformed_unbounded_argv_is_rejected(monkeypatch, contents):
    monkeypatch.setattr(canonical, "open", lambda *a, **k: io.BytesIO(contents),
                        raising=False)
    assert not canonical._worker_argv_matches(1234, "schedule")
