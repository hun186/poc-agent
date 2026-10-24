"""Fail-closed Linux process/socket and Ollama no-cloud version proofs."""
from __future__ import annotations

import json
import os

import pytest

from tools import sraf_airgap_off1f_local_attestation as safety


PID = 4242
PORT = 11434
INODE = "812499"


def _setup_proc(tmp_path, monkeypatch, *, address="0100007F", state="0A",
                inode=INODE, env=b"OLLAMA_NO_CLOUD=1\x00PATH=/bin\x00",
                cmd=b"/usr/bin/ollama\x00serve\x00", exe="/usr/bin/ollama"):
    root = tmp_path / "proc"
    proc = root / str(PID)
    (proc / "fd").mkdir(parents=True)
    (root / "net").mkdir()
    (root / "net" / "tcp").write_text(
        "  sl  local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
        f"  0: {address}:{PORT:04X} 00000000:0000 {state} 00000000:00000000 00:00000000 00000000 1000 0 {inode} 1 0\n"
    )
    (proc / "cmdline").write_bytes(cmd)
    (proc / "environ").write_bytes(env)
    (proc / "exe").symlink_to(exe)
    (proc / "fd" / "7").symlink_to(f"socket:[{inode}]")
    monkeypatch.setattr(safety, "PROC", root)
    monkeypatch.setattr(safety.sys, "platform", "linux")
    return root


def test_real_socket_inode_ollama_process_and_no_cloud_required(tmp_path, monkeypatch):
    _setup_proc(tmp_path, monkeypatch)
    assert safety._loopback_listen_inode(PORT) == INODE
    assert safety._owns_socket(PID, INODE)
    assert safety.server_cloud_disabled(PID, PORT)
    assert not safety.server_cloud_disabled(PID + 1, PORT)
    assert not safety.server_cloud_disabled(None, PORT)
    assert not safety.server_cloud_disabled(True, PORT)
    assert not safety.server_cloud_disabled(PID, 0)


@pytest.mark.parametrize("env", [
    b"OLLAMA_NO_CLOUD=0\x00", b"OTHER_VAR=1\x00",
    b"OLLAMA_NO_CLOUD=true\x00",
    b"OLLAMA_NO_CLOUD=1\x00OLLAMA_NO_CLOUD=0\x00",
    b"OLLAMA_NO_CLOUD=1_NOT_REAL\x00",
])
def test_wrong_or_ambiguous_server_env_is_rejected(tmp_path, monkeypatch, env):
    _setup_proc(tmp_path, monkeypatch, env=env)
    assert not safety.server_cloud_disabled(PID, PORT)


@pytest.mark.parametrize("address,state", [
    ("00000000", "0A"),   # wildcard bind -> cannot prove loopback exclusivity
    ("0200007F", "0A"),   # other loopback address
    ("0100007F", "01"),   # established rather than listen
])
def test_wrong_listener_host_or_state_fails_closed(
        tmp_path, monkeypatch, address, state):
    _setup_proc(tmp_path, monkeypatch, address=address, state=state)
    assert not safety.server_cloud_disabled(PID, PORT)


def test_wrong_server_exe_cmd_and_socket_owner(tmp_path, monkeypatch):
    root = _setup_proc(tmp_path, monkeypatch)
    exe = root / str(PID) / "exe"
    exe.unlink()
    exe.symlink_to("/usr/bin/python")
    assert not safety.server_cloud_disabled(PID, PORT)
    exe.unlink()
    exe.symlink_to("/usr/bin/ollama")
    (root / str(PID) / "cmdline").write_bytes(b"ollama\x00run\x00")
    assert not safety.server_cloud_disabled(PID, PORT)
    (root / str(PID) / "cmdline").write_bytes(b"/usr/bin/ollama\x00serve\x00")
    sock = root / str(PID) / "fd" / "7"
    sock.unlink()
    sock.symlink_to("socket:[88888]")
    assert not safety.server_cloud_disabled(PID, PORT)


@pytest.mark.parametrize("limit_field,payload", [
    ("env", b"X" * (safety.MAX_ENV_BYTES + 1)),
    ("cmd", b"x" * (safety.MAX_CMD_BYTES + 1)),
])
def test_oversized_proc_input_fails_closed(
        tmp_path, monkeypatch, limit_field, payload):
    root = _setup_proc(tmp_path, monkeypatch)
    target = "environ" if limit_field == "env" else "cmdline"
    (root / str(PID) / target).write_bytes(payload)
    assert not safety.server_cloud_disabled(PID, PORT)


def test_missing_proc_and_unsupported_system_reject(tmp_path, monkeypatch):
    root = _setup_proc(tmp_path, monkeypatch)
    monkeypatch.setattr(safety.sys, "platform", "darwin")
    assert not safety.server_cloud_disabled(PID, PORT)
    monkeypatch.setattr(safety.sys, "platform", "linux")
    (root / "net" / "tcp").unlink()
    assert not safety.server_cloud_disabled(PID, PORT)


def test_duplicate_listeners_and_malformed_tcp_reject(tmp_path, monkeypatch):
    root = _setup_proc(tmp_path, monkeypatch)
    path = root / "net" / "tcp"
    path.write_text(path.read_text() +
                    f"  1: 0100007F:{PORT:04X} 00000000:0000 0A 00000000:00000000 00:00000000 00000000 1000 0 123000 1\n")
    assert not safety.server_cloud_disabled(PID, PORT)
    path.write_bytes(b"bad-header\n\xffbad\n")
    assert not safety.server_cloud_disabled(PID, PORT)


@pytest.mark.parametrize("version,expected", [
    ("0.16.1", False), ("0.16.2", True), ("0.17.0", True),
    ("0.35.0", True), ("1.0.0", True),
    ("0.12.0", False), ("0.16.2-rc1", False),
    ("0.16.2+other", False), ("canary", False),
    ("99999.1.1", False),
])
def test_version_minimum_that_supports_server_cloud_disable(
        monkeypatch, version, expected):
    calls = []
    def api(port, path):
        calls.append((port, path))
        return 200, json.dumps({"version": version}).encode()
    monkeypatch.setattr(safety, "_http_get", api)
    assert safety.supported_local_only_version(PORT) is expected
    assert calls == [(PORT, "/api/version")]


@pytest.mark.parametrize("http_status,body", [
    (404, b"{}"), (200, b"invalid"), (200, b"{}"),
    (200, b"[]"), (200, b'{"version": true}'),
    (200, b"x" * 513), (None, None),
])
def test_unavailable_or_invalid_version_does_not_allow_inference(
        monkeypatch, http_status, body):
    monkeypatch.setattr(safety, "_http_get",
                        lambda port, path: (http_status, body))
    assert not safety.supported_local_only_version(PORT)


def test_unsafe_fd_scan_capacity_fails_closed(tmp_path, monkeypatch):
    root = _setup_proc(tmp_path, monkeypatch)
    monkeypatch.setattr(safety, "MAX_FDS", 1)
    fd = root / str(PID) / "fd"
    (fd / "7").unlink()
    (fd / "1").symlink_to("socket:[999]")
    (fd / "2").symlink_to(f"socket:[{INODE}]")
    assert not safety.server_cloud_disabled(PID, PORT)


def test_reading_own_env_is_not_accepted_for_server(tmp_path, monkeypatch):
    root = _setup_proc(tmp_path, monkeypatch, env=b"PATH=/bin\x00")
    monkeypatch.setenv("OLLAMA_NO_CLOUD", "1")
    assert not safety.server_cloud_disabled(PID, PORT)
