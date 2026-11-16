"""Regression tests: per-role SRAF Worker diagnostics remain passive/fail-closed."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from operator_e2e import requirement_e2e_support as authority
from tools import sraf_worker_identity_detail_readonly as detail


pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="live /proc file and owner semantics are Linux-only"
)


def _record(root: Path, role: str) -> Path:
    path = root / detail.IDENTITIES[role]
    path.write_text(
        f"role={role}\npid=1234\nprocess_start_time=98765\n",
        encoding="ascii",
    )
    path.chmod(0o600)
    return path


def _setup(root: Path) -> None:
    for role in detail.ROLES:
        _record(root, role)


def _verified(role: str, *, pid: int | None = None) -> dict:
    return {
        "role": role, "alive": True,
        "pid": pid if pid is not None else (1001 if role == "schedule" else 1002),
        "process_start_time": "98765",
    }


def test_both_verified_require_both_canonical_calls(tmp_path, monkeypatch):
    _setup(tmp_path)
    calls = []

    def verify(path, role, root):
        calls.append(role)
        assert root == tmp_path.resolve()
        assert path == root / detail.IDENTITIES[role]
        return _verified(role)

    monkeypatch.setattr(authority, "verify_worker_identity", verify)
    report = detail.inspect_workers(tmp_path)
    assert calls == ["schedule", "handoff"]
    assert report["overall_status"] == "PASS"
    assert report["verified_role_count"] == 2
    assert all(r["status"] == "VERIFIED" for r in report["roles"].values())
    dumped = json.dumps(report)
    assert "1234" not in dumped
    assert "98765" not in dumped
    assert str(tmp_path) not in dumped


def test_missing_schedule_does_not_hide_handoff(tmp_path, monkeypatch):
    _setup(tmp_path)
    (tmp_path / detail.IDENTITIES["schedule"]).unlink()
    calls = []

    def verify(path, role, root):
        calls.append(role)
        if role == "schedule":
            raise authority.HarnessFailure("worker_unavailable")
        return _verified(role)

    monkeypatch.setattr(authority, "verify_worker_identity", verify)
    report = detail.inspect_workers(tmp_path)
    assert calls == ["schedule", "handoff"]
    assert report["overall_status"] == "INCOMPLETE"
    assert report["verified_role_count"] == 1
    assert report["roles"]["schedule"] == {
        "status": "UNVERIFIED", "reason": "identity_file_missing"
    }
    assert report["roles"]["handoff"]["status"] == "VERIFIED"


def test_symlink_record_never_read_or_follow(tmp_path, monkeypatch):
    _setup(tmp_path)
    target = tmp_path / detail.IDENTITIES["handoff"]
    link = tmp_path / detail.IDENTITIES["schedule"]
    link.unlink()
    link.symlink_to(target)
    monkeypatch.setattr(authority, "verify_worker_identity",
                        lambda *args: (_ for _ in ()).throw(
                            authority.HarnessFailure("worker_unavailable")))
    report = detail.inspect_workers(tmp_path)
    assert report["roles"]["schedule"]["reason"] == "identity_file_invalid"
    assert report["roles"]["handoff"]["status"] == "UNVERIFIED"


@pytest.mark.parametrize("record,expected", [
    ("role=schedule\npid=1234\nprocess_start_time=98765", "identity_record_unreadable_or_invalid"),
    ("role=handoff\npid=1234\nprocess_start_time=98765\n", "identity_record_mismatch"),
    ("role=schedule\npid=1\nprocess_start_time=98765\n", "identity_record_mismatch"),
    ("role=schedule\npid=1234\npid=1234\n", "identity_record_unreadable_or_invalid"),
])
def test_invalid_identity_never_becomes_verified(tmp_path, monkeypatch, record, expected):
    _setup(tmp_path)
    (tmp_path / detail.IDENTITIES["schedule"]).write_text(record, encoding="ascii")
    monkeypatch.setattr(authority, "verify_worker_identity",
                        lambda *args: (_ for _ in ()).throw(
                            authority.HarnessFailure("worker_unavailable")))
    report = detail.inspect_workers(tmp_path)
    assert report["overall_status"] == "INCOMPLETE"
    assert report["roles"]["schedule"]["reason"] == expected


@pytest.mark.parametrize("part,reason", [
    ("start", "process_start_time_mismatch"),
    ("uid", "process_effective_uid_mismatch"),
    ("cwd", "process_workdir_mismatch"),
    ("argv", "process_command_role_mismatch"),
    ("all", "canonical_identity_unverified"),
])
def test_secondary_checks_only_classify_not_authorize(
        tmp_path, monkeypatch, part, reason):
    _setup(tmp_path)
    monkeypatch.setattr(authority, "verify_worker_identity",
                        lambda *args: (_ for _ in ()).throw(
                            authority.HarnessFailure("worker_unavailable")))
    monkeypatch.setattr(authority, "_proc_start_time",
                        lambda pid: "not-a-match" if part == "start" else "98765")
    monkeypatch.setattr(authority, "_proc_uid",
                        lambda pid: -1 if part == "uid" else os.geteuid())
    monkeypatch.setattr(authority, "_proc_cwd",
                        lambda pid: tmp_path / "elsewhere" if part == "cwd" else tmp_path)
    monkeypatch.setattr(authority, "_worker_argv_matches",
                        lambda pid, role: part != "argv")
    report = detail.inspect_workers(tmp_path)
    assert report["overall_status"] == "INCOMPLETE"
    assert report["verified_role_count"] == 0
    assert report["roles"]["schedule"]["reason"] == reason
    assert report["roles"]["handoff"]["reason"] == reason


def test_duplicate_pid_is_not_two_verified_roles(tmp_path, monkeypatch):
    _setup(tmp_path)
    monkeypatch.setattr(authority, "verify_worker_identity",
                        lambda path, role, root: _verified(role, pid=1111))
    report = detail.inspect_workers(tmp_path)
    assert report["overall_status"] == "INCOMPLETE"
    assert report["verified_role_count"] == 1
    assert report["roles"]["handoff"]["reason"] == "verified_roles_share_pid"


def test_canonical_unexpected_return_cannot_pass(tmp_path, monkeypatch):
    _setup(tmp_path)
    monkeypatch.setattr(authority, "verify_worker_identity",
                        lambda path, role, root: {"role": role, "pid": True,
                                                  "process_start_time": "98765",
                                                  "alive": True})
    report = detail.inspect_workers(tmp_path)
    assert report["overall_status"] == "INCOMPLETE"
    assert report["verified_role_count"] == 0
    assert report["roles"]["schedule"]["reason"] == "canonical_result_invalid"


def test_exceptions_never_leak_native_details(tmp_path, monkeypatch, capsys):
    _setup(tmp_path)

    def fail(*args):
        raise RuntimeError("PRIVATE-SECRET PID=3333 /srv/secret token=xyz")

    monkeypatch.setattr(authority, "verify_worker_identity", fail)
    monkeypatch.setattr(detail, "_suspected_reason", fail)
    monkeypatch.setattr(detail, "PROJECT_ROOT", tmp_path)
    assert detail.main() == 2
    output = capsys.readouterr().out
    assert "PRIVATE-SECRET" not in output
    assert "PID=3333" not in output
    assert "/srv/secret" not in output
    assert "token=xyz" not in output
    assert json.loads(output)["roles"]["schedule"]["reason"] == "secondary_diagnosis_unavailable"


def test_nonlinux_does_not_call_canonical(tmp_path, monkeypatch):
    _setup(tmp_path)
    monkeypatch.setattr(detail.sys, "platform", "win32")
    monkeypatch.setattr(authority, "verify_worker_identity",
                        lambda *a: pytest.fail("nonlinux invoked canonical"))
    report = detail.inspect_workers(tmp_path)
    assert report["overall_status"] == "INCOMPLETE"
    assert report["roles"]["schedule"]["reason"] == "unsupported_host"
