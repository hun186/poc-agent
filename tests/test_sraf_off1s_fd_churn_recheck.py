"""Synthetic OFF-1S FD churn acceptance: always revalidate whole procfs scan."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from tools import sraf_airgap_off1s_api_listener as listener

PID, OTHER_PID, INODE = 12345, 12346, "safe_fixture_inode"
TICK = "1234567"


class Listing:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return iter(self.rows)

    def __exit__(self, *unused):
        return False


def _mount_fake_proc(monkeypatch, *, other_socket=False, disappear="first"):
    state = {"reads": 0, "proc_scans": 0}
    all_pids = [PID, OTHER_PID] if other_socket else [PID]

    def scandir(path):
        path = str(path)
        if path == "/proc":
            state["proc_scans"] += 1
            return Listing([SimpleNamespace(name=str(pid)) for pid in all_pids])
        for pid in all_pids:
            if path == f"/proc/{pid}/task":
                return Listing([SimpleNamespace(name=str(pid))])
            if path == f"/proc/{pid}/task/{pid}/fd":
                return Listing([SimpleNamespace(
                    name="3", path=f"/proc/{pid}/task/{pid}/fd/3")])
        raise AssertionError("unexpected procfs access")

    def readlink(path):
        state["reads"] += 1
        if disappear == "always" or (disappear == "first" and state["reads"] == 1):
            raise FileNotFoundError("DO_NOT_EXPOSE_PRIVATE_PROC_PATH")
        return f"socket:[{INODE}]"

    monkeypatch.setattr(listener, "_procfs_unfiltered", lambda: True)
    monkeypatch.setattr(listener.os, "scandir", scandir)
    monkeypatch.setattr(listener.os, "readlink", readlink)
    return state


def test_vanished_fd_rechecks_entire_scan_once(monkeypatch):
    state = _mount_fake_proc(monkeypatch, disappear="first")
    budget = [1]
    assert listener._exclusive_owner_with_churn_recheck(PID, INODE, budget)
    assert state["proc_scans"] == 2
    assert state["reads"] == 2
    assert budget == [0]
    assert listener._FD_CHURN_MARKER.get() is None


def test_vanished_fd_with_zero_budget_remains_fail_closed(monkeypatch):
    state = _mount_fake_proc(monkeypatch, disappear="always")
    assert not listener._exclusive_owner_with_churn_recheck(PID, INODE, [0])
    assert state["proc_scans"] == 1
    assert listener._FD_CHURN_MARKER.get() is None


def test_recheck_is_not_a_loop_when_host_keeps_closing_fds(monkeypatch):
    state = _mount_fake_proc(monkeypatch, disappear="always")
    budget = [1]
    assert not listener._exclusive_owner_with_churn_recheck(PID, INODE, budget)
    assert state["proc_scans"] == 2
    assert budget == [0]


def test_co_owner_is_never_retried_or_accepted(monkeypatch):
    state = _mount_fake_proc(
        monkeypatch, other_socket=True, disappear="never")
    budget = [1]
    assert not listener._exclusive_owner_with_churn_recheck(PID, INODE, budget)
    assert state["proc_scans"] == 1
    assert budget == [1]


def test_scan_budget_limit_is_not_retried(monkeypatch):
    state = _mount_fake_proc(monkeypatch, disappear="never")
    monkeypatch.setattr(listener, "MAX_GLOBAL_FDS", 0)
    budget = [1]
    assert not listener._exclusive_owner_with_churn_recheck(PID, INODE, budget)
    assert state["proc_scans"] == 1
    assert budget == [1]


def test_no_retry_on_unreadable_fd(monkeypatch):
    state = _mount_fake_proc(monkeypatch, disappear="never")
    def denied(path):
        state["reads"] += 1
        raise PermissionError("DO_NOT_EXPOSE_PRIVATE_PROC_PATH")
    monkeypatch.setattr(listener.os, "readlink", denied)
    budget = [1]
    assert not listener._exclusive_owner_with_churn_recheck(PID, INODE, budget)
    assert state["proc_scans"] == 1
    assert budget == [1]


def _identity_setup(monkeypatch, root):
    monkeypatch.setattr(listener, "_pin_root_directory",
                        lambda _: os.open(root, os.O_RDONLY | os.O_DIRECTORY))
    monkeypatch.setattr(listener, "_identity", lambda *_: (PID, TICK))
    monkeypatch.setattr(listener, "_same_process", lambda *_: True)
    monkeypatch.setattr(listener, "_listener_inode", lambda *_: INODE)
    monkeypatch.setattr(listener, "_owns_socket", lambda *_: True)


def test_attestation_shares_one_retry_across_both_strict_passes(monkeypatch, tmp_path):
    _identity_setup(monkeypatch, tmp_path)
    calls = []

    def exclusive(*_):
        calls.append(1)
        if len(calls) == 2:
            marker = listener._FD_CHURN_MARKER.get()
            assert marker is not None
            marker.append(True)
            return False
        return True

    monkeypatch.setattr(listener, "_exclusive_socket_owner", exclusive)
    proof = listener.attest_api_listener(tmp_path, "9002")
    assert proof == listener.ListenerProof(PID, TICK, 9002, INODE)
    assert len(calls) == 3
    assert listener._FD_CHURN_MARKER.get() is None


def test_attestation_does_not_grant_second_retry(monkeypatch, tmp_path):
    _identity_setup(monkeypatch, tmp_path)
    calls = []

    def exclusive(*_):
        calls.append(1)
        if len(calls) in (1, 3):
            marker = listener._FD_CHURN_MARKER.get()
            if marker is not None:
                marker.append(True)
            return False
        return True

    monkeypatch.setattr(listener, "_exclusive_socket_owner", exclusive)
    assert listener.attest_api_listener(tmp_path, "9002") is None
    assert len(calls) == 3
    assert listener._FD_CHURN_MARKER.get() is None
