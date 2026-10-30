"""No external service, model, network call, lock creation or real deployment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tools import sraf_linux_load_topology_readonly as diag


@pytest.fixture
def installed(monkeypatch, tmp_path):
    monkeypatch.setattr(diag, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _proof(pid=1234, start="567890"):
    return SimpleNamespace(pid=pid, start_tick=start, port=9002, inode="98765")


def test_stable_snapshot_never_claims_full_live_or_cross_worker_proof(monkeypatch, installed):
    seen = {"listener": 0}
    def listener(*args):
        seen["listener"] += 1
        return _proof()
    monkeypatch.setattr(diag, "attest_local_sampling_process", listener)
    monkeypatch.setattr(diag, "_same_mount_namespace", lambda pid: True)
    monkeypatch.setattr(diag, "_local_lock_observation",
                        lambda root: diag._row("OBSERVED", "local_lock_candidate_metadata_verified"))
    measurements = iter((
        {"rss_kib": 2048, "threads": 4, "cpu_ticks": 11},
        {"rss_kib": 3072, "threads": 5, "cpu_ticks": 13},
    ))
    monkeypatch.setattr(diag, "_sample", lambda pid, tick: next(measurements))
    monkeypatch.setattr(diag.time, "sleep", lambda sec: None)
    result = diag.observe(installed, "9002", samples=2, interval=2)
    assert seen["listener"] == 2
    assert result["overall"] == "PARTIAL_OBSERVATION"
    assert result["samples"] == [
        {"sample": 1, "rss_mib": 2.0, "threads": 4},
        {"sample": 2, "rss_mib": 3.0, "threads": 5},
    ]
    assert result["checks"]["API-LISTENER"]["reason"] == "launcher_listener_for_local_sampling_only"
    assert result["checks"]["SOCKET-EXCLUSIVITY"] == {
        "status": "NOT_TESTED", "reason": "global_fd_scan_intentionally_not_run"}
    assert result["checks"]["CROSS-WORKER-LOCK-SHARING"]["status"] == "NOT_TESTED"
    assert result["checks"]["OLLAMA-ES-TIMEOUT"]["status"] == "NOT_TESTED"
    assert result["feature_acceptance"] == "NOT_TESTED"
    assert (result["network_requests"], result["model_inferences"],
            result["mutations"], result["processes_spawned"]) == (0, 0, 0, 0)
    for forbidden in ("1234", "9002", "567890", "98765", str(installed), "Bearer"):
        assert forbidden not in json.dumps(result)


def test_unverified_listener_does_not_read_process_or_sleep(monkeypatch, installed):
    monkeypatch.setattr(diag, "attest_local_sampling_process", lambda *_: None)
    monkeypatch.setattr(diag, "_sample",
                        lambda *_: pytest.fail("unattested PID sampled"))
    monkeypatch.setattr(diag.time, "sleep",
                        lambda *_: pytest.fail("should not sleep"))
    result = diag.observe(installed, "9002")
    assert result["overall"] == "INCOMPLETE"
    assert result["samples"] == []
    assert result["checks"]["API-PROCESS-SAMPLES"]["status"] == "SKIP"


def test_listener_replacement_discards_all_numeric_samples(monkeypatch, installed):
    proofs = iter((_proof(), _proof(pid=3333)))
    monkeypatch.setattr(diag, "attest_local_sampling_process", lambda *_: next(proofs))
    monkeypatch.setattr(diag, "_sample",
                        lambda *_: {"rss_kib": 4096, "threads": 5, "cpu_ticks": 10})
    monkeypatch.setattr(diag, "_same_mount_namespace", lambda *_: None)
    monkeypatch.setattr(diag.time, "sleep", lambda _: None)
    result = diag.observe(installed, "9002", interval=0)
    assert result["overall"] == "INCOMPLETE"
    assert result["samples"] == []
    assert result["checks"]["API-LISTENER"]["reason"] == "listener_identity_changed"
    assert result["checks"]["API-PROCESS-SAMPLES"]["status"] == "SKIP"


@pytest.mark.parametrize("port", ["", "0", "65536", "09002", "9002;rm -rf /",
                                  "90x", "²"])
def test_invalid_port_fails_before_listener(monkeypatch, installed, port):
    monkeypatch.setattr(diag, "attest_local_sampling_process",
                        lambda *_: pytest.fail("bad port accepted"))
    monkeypatch.setattr(diag, "_local_lock_observation",
                        lambda *_: pytest.fail("invalid input reached filesystem"))
    assert diag.observe(installed, port)["overall"] == "INCOMPLETE"


@pytest.mark.parametrize("samples,interval", [(1, 1), (6, 1), (2, -1), (2, 21)])
def test_invalid_sampling_arguments_fail_closed(monkeypatch, installed, samples, interval):
    monkeypatch.setattr(diag, "attest_local_sampling_process",
                        lambda *_: pytest.fail("invalid sampling accepted"))
    assert diag.observe(installed, "9002", samples=samples, interval=interval)["overall"] == "INCOMPLETE"


def test_root_is_required_to_match_running_repository(monkeypatch, installed):
    monkeypatch.setattr(diag, "attest_local_sampling_process",
                        lambda *_: pytest.fail("other root accepted"))
    elsewhere = installed.parent / "some-other-repo"
    elsewhere.mkdir(exist_ok=True)
    assert diag.observe(elsewhere, "9002")["overall"] == "INCOMPLETE"
    assert diag.observe(Path("relative"), "9002")["overall"] == "INCOMPLETE"


def test_missing_candidate_lock_does_not_create_it(monkeypatch, tmp_path):
    candidate = tmp_path / "private"
    monkeypatch.setattr(diag, "_local_lock_candidate", lambda *_: candidate)
    result = diag._local_lock_observation(tmp_path)
    assert result == diag._row("SKIP", "local_lock_candidate_missing")
    assert not candidate.exists()


def test_lock_candidate_checked_read_only_and_rejects_symlinks(monkeypatch, tmp_path):
    candidate = tmp_path / "private"
    candidate.mkdir(mode=0o700)
    candidate.chmod(0o700)
    lock = candidate / "preflight.lock"
    lock.write_bytes(b"fake-opaque-epoch-no-need-to-read")
    lock.chmod(0o600)
    monkeypatch.setattr(diag, "_local_lock_candidate", lambda *_: candidate)
    before = lock.read_bytes()
    assert diag._local_lock_observation(tmp_path) == diag._row(
        "OBSERVED", "local_lock_candidate_metadata_verified")
    assert lock.read_bytes() == before
    lock.unlink()
    lock.symlink_to(tmp_path / "another")
    assert diag._local_lock_observation(tmp_path)["status"] == "SKIP"


def test_untrusted_directory_mode_fails_closed(monkeypatch, tmp_path):
    candidate = tmp_path / "private"
    candidate.mkdir()
    candidate.chmod(0o755)
    monkeypatch.setattr(diag, "_local_lock_candidate", lambda *_: candidate)
    assert diag._local_lock_observation(tmp_path) == diag._row(
        "SKIP", "local_lock_candidate_untrusted")


def test_bounded_proc_parser_accepts_only_numeric_stable_identity(monkeypatch):
    pid, start = 1234, "567890"
    fields = [b"S"] + [b"0"] * 19
    fields[11], fields[12], fields[19] = b"100", b"123", start.encode()
    raw_stat = str(pid).encode() + b" (worker) " + b" ".join(fields)
    raw_status = b"Name:\tworker\nVmRSS:\t2048 kB\nThreads:\t4\n"
    monkeypatch.setattr(diag, "_start_tick", lambda *_: start)
    monkeypatch.setattr(diag, "_bounded",
                        lambda path, limit: raw_stat if str(path).endswith("/stat") else raw_status)
    assert diag._sample(pid, start) == {"rss_kib": 2048, "threads": 4, "cpu_ticks": 223}
    monkeypatch.setattr(diag, "_start_tick", lambda *_: "DIFFERENT")
    assert diag._sample(pid, start) is None


def test_malformed_proc_is_not_printed_or_exposed(monkeypatch):
    monkeypatch.setattr(diag, "_start_tick", lambda *_: "99")
    monkeypatch.setattr(diag, "_bounded",
                        lambda *_: b"bad-proc-Bearer-SENSITIVE")
    assert diag._sample(1234, "99") is None


def test_cli_invalid_root_outputs_redacted_json_only(tmp_path, capsys):
    rc = diag.main(["--project-root", str(tmp_path / "missing"), "--api-port", "9002",
                    "--samples", "2", "--interval", "0"])
    raw = capsys.readouterr()
    obj = json.loads(raw.out)
    assert rc == 2
    assert obj["overall"] == "INCOMPLETE"
    assert obj["feature_acceptance"] == "NOT_TESTED"
    assert str(tmp_path) not in raw.out and "9002" not in raw.out
    assert raw.err == ""


def test_local_sampling_attestation_preserves_pid_cwd_uid_and_socket_without_global_scan(
        monkeypatch, tmp_path):
    """The real OFF-1S exclusive scan is NOT an authorized part of OFF-1U."""
    from tools import sraf_airgap_off1s_api_listener as strict
    monkeypatch.setattr(strict, "_exclusive_socket_owner",
                        lambda *_: pytest.fail("global FD scan must not run"))
    calls = {"identity": 0, "process": 0, "inode": 0, "own": 0}

    def identity(*_):
        calls["identity"] += 1
        return (1234, "567890")

    def same_process(*_):
        calls["process"] += 1
        return True

    def inode(*_):
        calls["inode"] += 1
        return "98765"

    def owns(*_):
        calls["own"] += 1
        return True

    monkeypatch.setattr(diag, "_identity", identity)
    monkeypatch.setattr(diag, "_same_process", same_process)
    monkeypatch.setattr(diag, "_listener_inode", inode)
    monkeypatch.setattr(diag, "_owns_socket", owns)
    proof = diag.attest_local_sampling_process(tmp_path, "9002")
    assert proof is not None
    assert (proof.pid, proof.start_tick, proof.port, proof.inode) == (
        1234, "567890", 9002, "98765")
    assert calls == {"identity": 2, "process": 2, "inode": 2, "own": 2}


@pytest.mark.parametrize("failure", [
    "record_missing", "process_bad", "socket_missing", "socket_not_held",
    "identity_drift", "socket_changed",
])
def test_sampling_attestation_rejects_unbound_or_changed_authorities(
        monkeypatch, tmp_path, failure):
    ids = iter([(1234, "567890"), (9999, "99999")]) if failure == "identity_drift" else None
    inodes = iter(["98765", "56789"]) if failure == "socket_changed" else None
    monkeypatch.setattr(diag, "_identity", lambda *_: (
        next(ids) if ids else None if failure == "record_missing" else (1234, "567890")))
    monkeypatch.setattr(diag, "_same_process",
                        lambda *_: failure != "process_bad")
    monkeypatch.setattr(diag, "_listener_inode",
                        lambda *_: next(inodes) if inodes else
                        None if failure == "socket_missing" else "98765")
    monkeypatch.setattr(diag, "_owns_socket",
                        lambda *_: failure != "socket_not_held")
    assert diag.attest_local_sampling_process(tmp_path, "9002") is None


def test_nonexclusive_sampler_never_invokes_token_bearing_off1s_proof(monkeypatch, installed):
    from tools import sraf_airgap_off1s_api_listener as strict
    monkeypatch.setattr(strict, "attest_api_listener",
                        lambda *_: pytest.fail("token gate should not be used"))
    monkeypatch.setattr(strict, "_exclusive_socket_owner",
                        lambda *_: pytest.fail("global FD scan should not be used"))
    monkeypatch.setattr(diag, "attest_local_sampling_process", lambda *_: _proof())
    monkeypatch.setattr(diag, "_sample",
                        lambda *_: {"rss_kib": 4096, "threads": 2, "cpu_ticks": 0})
    monkeypatch.setattr(diag, "_same_mount_namespace", lambda *_: None)
    monkeypatch.setattr(diag.time, "sleep", lambda *_: None)
    result = diag.observe(installed, "9002", samples=2, interval=0)
    assert result["overall"] == "PARTIAL_OBSERVATION"
    assert result["checks"]["SOCKET-EXCLUSIVITY"]["status"] == "NOT_TESTED"
    assert result["checks"]["API-LISTENER"]["reason"] == "launcher_listener_for_local_sampling_only"
