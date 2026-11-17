"""Synthetic, no-network regressions for sanitized OFF-1S host stage inspection."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools import sraf_off1s_stage_diagnostic_readonly as diag


def test_scan_reason_contract_tracks_known_source():
    tags = diag._false_return_map(diag.listener._exclusive_socket_owner)
    assert list(tags.values()) == list(diag.SCAN_FALSE_REASONS)
    assert all(type(line) is int for line in tags)


@pytest.mark.parametrize(
    ("source_pid", "owner", "missing", "expected_status", "reason"),
    [
        (42, 42, False, "PASS", "NONE"),
        (42, 41, False, "INCOMPLETE", "another_socket_owner"),
        (42, 42, True, "INCOMPLETE", "fd_disappeared"),
    ],
)
def test_live_attestation_probe_never_prints_sensitive_values(
        monkeypatch, source_pid, owner, missing, expected_status, reason):
    """Retain the genuine scan and its fail-closed branches; fake procfs only."""
    inode = "SENSITIVE_SOCKET_ID_NEVER_PRINT"
    secret = "SECRET_TOKEN_NEVER_PRINT"
    pid = source_pid

    class Dir:
        def __init__(self, items):
            self.items = items

        def __enter__(self):
            return iter(self.items)

        def __exit__(self, exc_type, exc, tb):
            return False

    def scandir(path):
        if path == "/proc":
            return Dir([SimpleNamespace(name=str(pid))])
        if path == f"/proc/{pid}/task":
            return Dir([SimpleNamespace(name=str(pid))])
        if path == f"/proc/{pid}/task/{pid}/fd":
            return Dir([SimpleNamespace(
                name="3",
                path=f"/proc/{pid}/task/{pid}/fd/3",
            )])
        raise AssertionError("unexpected procfs path")

    def readlink(path):
        assert path == f"/proc/{pid}/task/{pid}/fd/3"
        if missing:
            raise FileNotFoundError("SENSITIVE_PATH_NEVER_PRINT")
        return f"socket:[{inode}]"

    def fake_attest(root, port):
        assert port == "9002"
        return {"secret": secret} if diag.listener._exclusive_socket_owner(
            owner, inode) else None

    monkeypatch.setattr(diag.listener, "_procfs_unfiltered", lambda: True)
    monkeypatch.setattr(diag.listener.os, "scandir", scandir)
    monkeypatch.setattr(diag.listener.os, "readlink", readlink)
    monkeypatch.setattr(diag.listener, "attest_api_listener", fake_attest)

    result = diag.observe_once()
    assert result["status"] == expected_status
    assert result["failure_reason"] == reason
    assert result["failure_stage"] == (
        "NONE" if expected_status == "PASS" else "EXCLUSIVE_OWNER")
    scans = [x for x in result["events"] if x["stage"] == "EXCLUSIVE_OWNER"]
    assert len(scans) == 1
    assert scans[0]["total_fds"] == 1
    assert scans[0]["per_thread_fds"] == 1
    raw = json.dumps(result)
    for forbidden in (secret, inode, "SENSITIVE_PATH_NEVER_PRINT",
                      '"pid"', '"port"', '"source_pid"'):
        assert forbidden not in raw


def test_unverified_without_trace_cannot_be_marked_pass(monkeypatch):
    monkeypatch.setattr(diag.listener, "attest_api_listener", lambda *_: None)
    result = diag.observe_once()
    assert result["status"] == "INCOMPLETE"
    assert result["failure_stage"] == "UNOBSERVED"


def test_cli_never_grants_authority_and_bounds_attempts(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(diag, "observe_once", lambda: calls.append(True) or {
        "status": "INCOMPLETE",
        "failure_stage": "EXCLUSIVE_OWNER",
        "failure_reason": "fd_disappeared",
        "elapsed_ms": 2,
        "events": [],
    })
    assert diag.main(["--attempts", "2"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert len(calls) == 2
    assert payload["result"] == "INCOMPLETE"
    assert payload["http_requests"] == 0
    assert payload["credentials_sent"] is False
    assert payload["mutations"] == 0
    with pytest.raises(SystemExit):
        diag.main(["--attempts", "4"])
