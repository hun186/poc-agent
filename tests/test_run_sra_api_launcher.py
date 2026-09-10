from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_sra_api.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def launcher_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = tmp_path / "events"
    _write_executable(
        bin_dir / "uvicorn",
        'echo "api:$*" >> "$TEST_EVENTS"; '
        'trap \'echo api-term >> "$TEST_EVENTS"; exit 0\' TERM INT; '
        'while :; do sleep 0.05; done',
    )
    _write_executable(
        bin_dir / "python",
        'echo "python:$*" >> "$TEST_EVENTS"; '
        'trap \'echo "worker-term:$*" >> "$TEST_EVENTS"; exit 0\' TERM INT; '
        'while :; do sleep 0.05; done',
    )
    _write_executable(
        bin_dir / "lsof",
        'if [ "${FAKE_PORT_PID_FILE:-}" ] && [ -s "$FAKE_PORT_PID_FILE" ]; then '
        'pid=$(cat "$FAKE_PORT_PID_FILE"); '
        'if kill -0 "$pid" 2>/dev/null && [ "$(awk \'{print $3}\' "/proc/$pid/stat" 2>/dev/null)" != Z ]; then '
        'case " $* " in *" -t "*) echo "$pid";; *) echo "COMMAND PID NAME"; echo "fake $pid tcp";; esac; '
        'fi; fi',
    )
    env = os.environ.copy()
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        BASE_DIR=str(tmp_path),
        LOCK_FILE=str(tmp_path / "launcher.lock"),
        TEST_EVENTS=str(events),
        SHUTDOWN_TIMEOUT_SECONDS="1",
        PORT_RELEASE_TIMEOUT_SECONDS="1",
    )
    return env, events


def _start(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["bash", str(LAUNCHER)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _wait_for(path: Path, needle: str, timeout: float = 3) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = path.read_text(encoding="utf-8") if path.exists() else ""
        if needle in value:
            return value
        time.sleep(0.03)
    raise AssertionError(f"did not observe {needle!r} in {value!r}")


def _stop(proc: subprocess.Popen[str], sig: int = signal.SIGTERM) -> tuple[int, str]:
    proc.send_signal(sig)
    output, _ = proc.communicate(timeout=5)
    return proc.returncode, output


def test_launcher_has_valid_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(LAUNCHER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_starts_all_three_roles_and_bootstraps_workers(launcher_env) -> None:
    env, events = launcher_env
    proc = _start(env)
    content = _wait_for(events, "handoff-worker")
    code, _ = _stop(proc)
    assert code == 0
    assert "api.main:app --host 0.0.0.0 --port 9002" in content
    assert content.count("schedule-worker") == 1
    assert content.count("handoff-worker") == 1
    worker_lines = [line for line in content.splitlines() if line.startswith("python:")]
    assert len(worker_lines) == 2
    assert all("from config.bootstrap import bootstrap_env" in line for line in worker_lines)
    assert all("bootstrap_env()" in line for line in worker_lines)


def test_second_launcher_fails_without_starting_duplicates(launcher_env) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    before = events.read_text(encoding="utf-8")
    second = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
    after = events.read_text(encoding="utf-8")
    _stop(first)
    assert second.returncode != 0
    assert "already running" in (second.stdout + second.stderr).lower()
    assert after == before


def test_unverified_port_owner_is_not_killed_and_fails_closed(launcher_env) -> None:
    env, events = launcher_env
    owner = subprocess.Popen(["sleep", "30"])
    pid_file = Path(env["BASE_DIR"]) / "port.pid"
    pid_file.write_text(str(owner.pid), encoding="ascii")
    env["FAKE_PORT_PID_FILE"] = str(pid_file)
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode != 0
        assert owner.poll() is None
        assert not events.exists()
        audit = (Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log").read_text(encoding="utf-8")
        assert "unverified" in audit.lower()
    finally:
        owner.terminate()
        owner.wait(timeout=3)


def test_identified_stale_api_gets_term_before_any_kill(launcher_env) -> None:
    env, events = launcher_env
    stale = subprocess.Popen(
        [
            "bash",
            "-c",
            "trap 'exit 0' TERM; while :; do sleep .1; done",
            "uvicorn",
            "api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "9002",
        ],
        cwd=env["BASE_DIR"],
    )
    pid_file = Path(env["BASE_DIR"]) / "port.pid"
    pid_file.write_text(str(stale.pid), encoding="ascii")
    env["FAKE_PORT_PID_FILE"] = str(pid_file)
    proc = _start(env)
    _wait_for(events, "handoff-worker")
    _stop(proc)
    stale.wait(timeout=3)
    audit = (Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log").read_text(encoding="utf-8")
    assert "SIGTERM" in audit
    assert "SIGKILL" not in audit


def test_unresponsive_verified_api_gets_term_then_kill(launcher_env) -> None:
    env, events = launcher_env
    stale = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
            "uvicorn",
            "api.main:app",
            "--port",
            "9002",
        ],
        cwd=env["BASE_DIR"],
    )
    pid_file = Path(env["BASE_DIR"]) / "port.pid"
    pid_file.write_text(str(stale.pid), encoding="ascii")
    env["FAKE_PORT_PID_FILE"] = str(pid_file)
    proc = _start(env)
    _wait_for(events, "handoff-worker", timeout=5)
    _stop(proc)
    stale.wait(timeout=3)
    audit = (Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log").read_text(encoding="utf-8")
    assert audit.index("Sending SIGTERM") < audit.index("Sending SIGKILL")


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_signal_cleans_up_every_owned_child(launcher_env, sig: int) -> None:
    env, events = launcher_env
    proc = _start(env)
    _wait_for(events, "handoff-worker")
    code, _ = _stop(proc, sig)
    content = _wait_for(events, "api-term")
    assert code == 0
    assert content.count("worker-term:") == 2


def test_unexpected_child_exit_cleans_up_siblings(launcher_env) -> None:
    env, events = launcher_env
    python = Path(env["PATH"].split(":", 1)[0]) / "python"
    _write_executable(
        python,
        'echo "python:$*" >> "$TEST_EVENTS"; '
        'case "$*" in *schedule-worker*) sleep .2; exit 7;; esac; '
        'trap \'echo "worker-term:$*" >> "$TEST_EVENTS"; exit 0\' TERM INT; '
        'while :; do sleep .05; done',
    )
    proc = _start(env)
    output, _ = proc.communicate(timeout=5)
    content = events.read_text(encoding="utf-8")
    assert proc.returncode != 0
    assert "Schedule Worker" in output and "status 7" in output
    assert "api-term" in content
    assert "worker-term:" in content


def test_runtime_logs_use_ten_megabyte_cap_semantics() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "MAX_SIZE_KB=$((10 * 1024))" in text
    assert "MAX_SIZE=$((MAX_SIZE_KB * 1024))" in text
    assert "10 MB" in text
    assert "10KB" not in text
    assert "SRA-ScheduleWorker_output.txt" in text
    assert "SRA-HandoffWorker_output.txt" in text


def test_kill_audit_is_appended_not_cleared(launcher_env) -> None:
    env, events = launcher_env
    audit = Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log"
    audit.write_text("permanent-history\n", encoding="utf-8")
    proc = _start(env)
    _wait_for(events, "handoff-worker")
    _stop(proc)
    assert audit.read_text(encoding="utf-8").startswith("permanent-history\n")
