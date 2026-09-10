from __future__ import annotations

import os
import shutil
import signal
import socket
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
    tmp_path.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = tmp_path / "events"
    _write_executable(
        bin_dir / "uvicorn",
        "printf '\\n%s LISTEN\\n' \"$BASHPID\" >> \"$FAKE_PORT_PID_FILE\"; "
        'echo "api:$*" >> "$TEST_EVENTS"; '
        'trap \'echo api-term >> "$TEST_EVENTS"; exit 0\' TERM INT; '
        'while :; do sleep 0.05; done',
    )
    _write_executable(
        bin_dir / "python",
        'case "$*" in *config.deployment_bootstrap*) '
        'state_dir="${BOOTSTRAP_STATE_DIR:-$SRA_DEPLOYMENT_STATE_DIR}"; mkdir -m 700 -p "$state_dir"; '
        'cat > "$state_dir/requirement_handoff.env" <<EOF\n'
        'SRA_BOOTSTRAP_STATE_VERSION=1\nSRA_BOOTSTRAP_HANDOFF_KEY_ID=test-key\n'
        'REQUIREMENT_HANDOFF_API_BASE_URL=http://127.0.0.1:9002\n'
        'REQUIREMENT_HANDOFF_ALLOW_INSECURE_LOCALHOST=true\n'
        'REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL=requirement-handoff-runtime\n'
        'REQUIREMENT_HANDOFF_OUTPUT_ROOT=/tmp/output\n'
        'REQUIREMENT_HANDOFF_CREDENTIAL_ENV=REQUIREMENT_HANDOFF_CREDENTIAL\n'
        'REQUIREMENT_HANDOFF_CREDENTIAL=sra_sk_test_not-a-real-secret\nEOF\n'
        'chmod 600 "$state_dir/requirement_handoff.env"; '
        'echo "deployment_bootstrap_state_path=$state_dir/requirement_handoff.env"; exit 0;; esac; '
        'echo "python:$*" >> "$TEST_EVENTS"; '
        'case "$*:$FAIL_SCHEDULE" in *schedule-worker:1) sleep .2; exit 7;; esac; '
        'trap \'echo "worker-term:$*" >> "$TEST_EVENTS"; exit 0\' TERM INT; '
        'while :; do sleep 0.05; done',
    )
    _write_executable(
        bin_dir / "lsof",
        'echo "$*" >> "${LSOF_CALLS:-/dev/null}"; '
        'if [ "${FAKE_PORT_PID_FILE:-}" ] && [ -s "$FAKE_PORT_PID_FILE" ]; then '
        'while read -r pid kind || [ -n "${pid:-}" ]; do '
        'if kill -0 "$pid" 2>/dev/null && [ "$(awk \'{print $3}\' "/proc/$pid/stat" 2>/dev/null)" != Z ]; then '
        'case " $* " in *" -sTCP:LISTEN "*) [ "${kind:-LISTEN}" = LISTEN ] || continue;; esac; '
        'case " $* " in *" -t "*) echo "$pid";; *) echo "fake $pid tcp ${kind:-LISTEN}";; esac; '
        'fi; done < "$FAKE_PORT_PID_FILE"; fi',
    )
    env = os.environ.copy()
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        BASE_DIR=str(tmp_path),
        LOCK_FILE=str(tmp_path / "launcher.lock"),
        LAUNCHER_IDENTITY_FILE=str(tmp_path / ".run_sra_api_launcher.identity"),
        TAKEOVER_LOCK_FILE=str(tmp_path / ".run_sra_api_takeover.lock"),
        TEST_EVENTS=str(events),
        SHUTDOWN_TIMEOUT_SECONDS="1",
        PORT_RELEASE_TIMEOUT_SECONDS="1",
        API_IDENTITY_FILE=str(tmp_path / ".run_sra_api.identity"),
        SRA_DEPLOYMENT_STATE_DIR=str(tmp_path / ".sra_runtime"),
        FAKE_PORT_PID_FILE=str(tmp_path / "port.pid"),
        API_READINESS_TIMEOUT_SECONDS="2",
        FAIL_SCHEDULE="0",
        LSOF_CALLS=str(tmp_path / "lsof.calls"),
    )
    return env, events


@pytest.fixture(scope="session")
def titled_process(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a tiny process whose argv[0] is the complete deployed SRA title."""
    root = tmp_path_factory.mktemp("title-helper")
    source = root / "title_helper.c"
    binary = root / "title-helper"
    source.write_text(
        "#include <fcntl.h>\n#include <signal.h>\n#include <stdlib.h>\n#include <unistd.h>\n"
        "static void term(int s){(void)s;char*p=getenv(\"TERM_EVENT\");"
        "if(p){int f=open(p,O_WRONLY|O_CREAT,0600);if(f>=0){write(f,\"x\",1);close(f);}return;}_exit(0);}\n"
        "int main(void){signal(SIGTERM,term);for(;;)pause();}\n",
        encoding="ascii",
    )
    subprocess.run(["cc", str(source), "-o", str(binary)], check=True)
    return binary


def _set_listener_file(env: dict[str, str], *entries: tuple[int, str]) -> Path:
    path = Path(env["BASE_DIR"]) / "port.pid"
    path.write_text("".join(f"{pid} {kind}\n" for pid, kind in entries), encoding="ascii")
    env["FAKE_PORT_PID_FILE"] = str(path)
    return path


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
    output, _ = proc.communicate(timeout=10)
    return proc.returncode, output


def test_launcher_has_valid_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(LAUNCHER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shell_sources_are_lf_only_and_duplicate_launcher_is_absent() -> None:
    assert "*.sh text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for path in ROOT.glob("*.sh"):
        assert b"\r\n" not in path.read_bytes(), path
    assert not (ROOT / "run_sra_api - 複製.sh").exists()


def test_bootstrap_precedes_takeover_and_state_is_not_executed() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert source.index("python -m config.deployment_bootstrap") < source.index("\ninspect_port\n")
    assert "source $HANDOFF_STATE_FILE" not in source
    assert "eval" not in source
    assert source.count("9>&-") >= 7


def test_starts_all_three_roles_and_bootstraps_workers(launcher_env) -> None:
    env, events = launcher_env
    proc = _start(env)
    _wait_for(events, "handoff-worker")
    content = _wait_for(events, "schedule-worker")
    code, _ = _stop(proc)
    assert code == 0
    assert "api.main:app --host 0.0.0.0 --port 9002" in content
    assert content.count("schedule-worker") == 1
    assert content.count("handoff-worker") == 1
    worker_lines = [line for line in content.splitlines() if line.startswith("python:")]
    assert len(worker_lines) == 2
    assert all("from config.bootstrap import bootstrap_env" in line for line in worker_lines)
    assert all("bootstrap_env()" in line for line in worker_lines)


def test_launcher_imports_exact_path_returned_by_bootstrap(launcher_env) -> None:
    env, events = launcher_env
    env["BOOTSTRAP_STATE_DIR"] = str(Path(env["BASE_DIR"]) / "dotenv-selected-state")
    proc = _start(env)
    _wait_for(events, "handoff-worker")
    _stop(proc)
    assert (Path(env["BOOTSTRAP_STATE_DIR"]) / "requirement_handoff.env").is_file()


def test_second_launcher_gracefully_restarts_verified_runtime(launcher_env) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    _wait_for(events, "schedule-worker")
    identity = Path(env["LAUNCHER_IDENTITY_FILE"])
    old = dict(line.split("=", 1) for line in identity.read_text().splitlines())
    role_records = [Path(env["BASE_DIR"]) / ".run_sra_api_schedule.identity",
                    Path(env["BASE_DIR"]) / ".run_sra_api_handoff.identity"]
    for path in role_records:
        _wait_for(path, "process_start_time=")
    old_roles = [dict(line.split("=", 1) for line in path.read_text().splitlines()) for path in role_records]
    second = _start(env)
    _wait_for(events, "api-term")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        content = events.read_text(encoding="utf-8")
        current = dict(line.split("=", 1) for line in identity.read_text().splitlines()) if identity.exists() else {}
        current_roles = [dict(line.split("=", 1) for line in path.read_text().splitlines())
                         if path.exists() else {} for path in role_records]
        if (current.get("pid") != old["pid"]
                and all(item.get("pid") and item["pid"] != previous["pid"]
                        for item, previous in zip(current_roles, old_roles))):
            break
        time.sleep(0.03)
    assert first.wait(timeout=3) == 0
    assert second.poll() is None, second.communicate(timeout=1)[0]
    assert all(Path(f"/proc/{item['pid']}").exists() for item in current_roles)
    assert current["process_start_time"] != old["process_start_time"] or current["pid"] != old["pid"]
    _stop(second)


def test_restart_contender_does_not_truncate_launcher_identity(launcher_env) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    identity = Path(env["LAUNCHER_IDENTITY_FILE"])
    evidence = identity.read_bytes()
    first.send_signal(signal.SIGSTOP)
    contender = _start(env)
    try:
        time.sleep(0.2)
        assert identity.read_bytes() == evidence
        assert contender.poll() is None
    finally:
        first.send_signal(signal.SIGCONT)
        first.wait(timeout=5)
        _wait_for(events, "handoff-worker", timeout=5)
        _stop(contender)


def test_unverified_launcher_lock_holder_is_never_signaled(launcher_env) -> None:
    env, _ = launcher_env
    holder = subprocess.Popen(["flock", env["LOCK_FILE"], "sleep", "30"])
    identity = Path(env["LAUNCHER_IDENTITY_FILE"])
    identity.write_text(
        f"pid={holder.pid}\nprocess_start_time=1\neffective_uid={os.geteuid()}\n"
        f"cwd={env['BASE_DIR']}\nlauncher_path={LAUNCHER}\n", encoding="utf-8",
    )
    identity.chmod(0o600)
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode != 0
        assert holder.poll() is None
        assert "no signal" in (result.stdout + result.stderr).lower()
    finally:
        holder.terminate(); holder.wait(timeout=3)


@pytest.mark.parametrize("field,replacement", [
    ("process_start_time", "1"),
    ("effective_uid", "99999"),
    ("cwd", "/tmp"),
    ("launcher_path", "/tmp/not-the-launcher"),
])
def test_launcher_identity_mismatch_fails_closed(launcher_env, field: str, replacement: str) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    identity = Path(env["LAUNCHER_IDENTITY_FILE"])
    original = identity.read_text()
    values = dict(line.split("=", 1) for line in original.splitlines())
    values[field] = replacement
    identity.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    identity.chmod(0o600)
    result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
    assert result.returncode != 0
    assert first.poll() is None
    assert "no signal" in (result.stdout + result.stderr).lower()
    identity.write_text(original); identity.chmod(0o600)
    _stop(first)


def test_concurrent_restart_contenders_do_not_restart_replacement(launcher_env) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    identity = Path(env["LAUNCHER_IDENTITY_FILE"])
    old_launcher_pid = dict(line.split("=", 1) for line in identity.read_text().splitlines())["pid"]
    contenders = [_start(env), _start(env)]
    first.wait(timeout=5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = dict(line.split("=", 1) for line in identity.read_text().splitlines()) if identity.exists() else {}
        roles_ready = all((Path(env["BASE_DIR"]) / name).exists() for name in (
            ".run_sra_api_schedule.identity", ".run_sra_api_handoff.identity"))
        if current.get("pid") != old_launcher_pid and roles_ready and any(p.poll() is not None for p in contenders):
            break
        time.sleep(0.03)
    running = [p for p in contenders if p.poll() is None]
    assert len(running) == 1, [p.communicate(timeout=1)[0] for p in contenders]
    assert all((Path(env["BASE_DIR"]) / name).exists() for name in (
        ".run_sra_api_schedule.identity", ".run_sra_api_handoff.identity"))
    stopped = next(p for p in contenders if p.poll() is not None)
    assert stopped.returncode in {0, 1}
    _stop(running[0])


def test_verified_launcher_shutdown_timeout_fails_without_replacement(launcher_env) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    first.send_signal(signal.SIGSTOP)
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=4)
        assert result.returncode != 0
        assert events.read_text().count("handoff-worker") == 1
        assert first.poll() is None
        assert "timed out" in (result.stdout + result.stderr).lower()
    finally:
        first.kill(); first.wait(timeout=3)


def test_sigkill_releases_flock_and_replacement_reclaims_orphan_workers(launcher_env) -> None:
    env, events = launcher_env
    first = _start(env)
    _wait_for(events, "handoff-worker")
    schedule_record = Path(env["BASE_DIR"]) / ".run_sra_api_schedule.identity"
    handoff_record = Path(env["BASE_DIR"]) / ".run_sra_api_handoff.identity"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not (schedule_record.exists() and handoff_record.exists()):
        time.sleep(0.02)
    old_schedule = int(dict(line.split("=", 1) for line in schedule_record.read_text().splitlines())["pid"])
    old_handoff = int(dict(line.split("=", 1) for line in handoff_record.read_text().splitlines())["pid"])

    first.kill()
    first.wait(timeout=3)
    assert all(os.kill(pid, 0) is None for pid in (old_schedule, old_handoff))
    lock_probe = subprocess.run(
        ["flock", "-n", env["LOCK_FILE"], "true"], capture_output=True, text=True,
    )
    assert lock_probe.returncode == 0

    replacement = _start(env)
    try:
        def live(pid: int) -> bool:
            stat_path = Path(f"/proc/{pid}/stat")
            return stat_path.exists() and stat_path.read_text().split()[2] != "Z"

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not live(old_schedule) and not live(old_handoff):
                break
            time.sleep(0.05)
        assert not live(old_schedule)
        assert not live(old_handoff)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            content = events.read_text(encoding="utf-8") if events.exists() else ""
            if content.count("handoff-worker") >= 2 and schedule_record.exists() and handoff_record.exists():
                break
            time.sleep(0.03)
        assert content.count("handoff-worker") >= 2
        new_schedule = int(dict(line.split("=", 1) for line in schedule_record.read_text().splitlines())["pid"])
        new_handoff = int(dict(line.split("=", 1) for line in handoff_record.read_text().splitlines())["pid"])
        assert new_schedule != old_schedule and new_handoff != old_handoff
        assert sum(1 for pid in (new_schedule, new_handoff) if Path(f"/proc/{pid}").exists()) == 2
    finally:
        _stop(replacement)


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


@pytest.mark.parametrize("model_part", ["", "gpt-oss | "])
def test_real_rewritten_runtime_title_is_reclaimed(
    launcher_env, titled_process: Path, model_part: str
) -> None:
    env, events = launcher_env
    # exec through a shell that expands $$ before replacing itself, preserving that PID.
    stale = subprocess.Popen(
        ["bash", "-c", f'exec -a "SRA-API | port=9002 | {model_part}pid=$$ | {socket.gethostname()}" "{titled_process}"'],
        cwd=env["BASE_DIR"], text=True,
    )
    _set_listener_file(env, (stale.pid, "LISTEN"))
    proc = _start(env)
    _wait_for(events, "handoff-worker", timeout=5)
    _stop(proc)
    stale.wait(timeout=3)
    audit = (Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log").read_text(encoding="utf-8")
    assert "identity=runtime-title" in audit
    assert "SIGTERM" in audit and "SIGKILL" not in audit


def test_listener_query_excludes_established_client(launcher_env, titled_process: Path) -> None:
    env, events = launcher_env
    stale = subprocess.Popen(
        ["bash", "-c", f'exec -a "SRA-API | port=9002 | pid=$$ | {socket.gethostname()}" "{titled_process}"'],
        cwd=env["BASE_DIR"], text=True,
    )
    client = subprocess.Popen(["sleep", "30"])
    _set_listener_file(env, (stale.pid, "LISTEN"), (client.pid, "ESTABLISHED"))
    try:
        proc = _start(env)
        _wait_for(events, "handoff-worker", timeout=5)
        _stop(proc)
        assert client.poll() is None
        assert "-iTCP:9002 -sTCP:LISTEN" in Path(env["LSOF_CALLS"]).read_text(encoding="utf-8")
    finally:
        if client.poll() is None:
            client.terminate(); client.wait(timeout=3)


@pytest.mark.parametrize("title", [
    "SRA-API", "SRA-API fake", "foo SRA-API | port=9002",
    "SRA-API | port=9002 | arbitrary",
    "SRA-API | port=9003 | pid={pid} | {host}",
    "SRA-API | port=9002 | pid=999999 | {host}",
    "SRA-API | port=9002 | pid={pid} | wrong-host",
])
def test_forged_runtime_titles_are_never_signaled(launcher_env, titled_process: Path, title: str) -> None:
    env, events = launcher_env
    rendered = title.format(pid="$$", host=socket.gethostname())
    stale = subprocess.Popen(
        ["bash", "-c", f'exec -a "{rendered}" "{titled_process}"'],
        cwd=env["BASE_DIR"], text=True,
    )
    _set_listener_file(env, (stale.pid, "LISTEN"))
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode != 0
        assert stale.poll() is None
        assert not events.exists()
    finally:
        stale.terminate(); stale.wait(timeout=3)


def test_launcher_identity_record_written_and_removed(launcher_env) -> None:
    env, events = launcher_env
    record = Path(env["API_IDENTITY_FILE"])
    proc = _start(env)
    _wait_for(record, "api_start_time=")
    _wait_for(events, "handoff-worker")
    _wait_for(events, "schedule-worker")
    values = dict(line.split("=", 1) for line in record.read_text().splitlines())
    assert values["port"] == "9002"
    assert values["api_pid"].isdigit() and values["api_start_time"].isdigit()
    _stop(proc)
    assert not record.exists()


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


def test_unresponsive_rewritten_api_gets_term_then_kill(launcher_env, titled_process: Path) -> None:
    env, events = launcher_env
    env["TERM_EVENT"] = str(Path(env["BASE_DIR"]) / "stale.term")
    stale = subprocess.Popen(
        ["bash", "-c", f'exec -a "SRA-API | port=9002 | pid=$$ | {socket.gethostname()}" "{titled_process}"'],
        cwd=env["BASE_DIR"], env=env,
    )
    _set_listener_file(env, (stale.pid, "LISTEN"))
    proc = _start(env)
    _wait_for(events, "handoff-worker", timeout=5)
    _stop(proc)
    stale.wait(timeout=3)
    audit = (Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log").read_text(encoding="utf-8")
    assert audit.index("Sending SIGTERM") < audit.index("Sending SIGKILL")


def test_exact_runtime_title_with_wrong_cwd_is_not_signaled(launcher_env, titled_process: Path, tmp_path: Path) -> None:
    env, _ = launcher_env
    other = tmp_path / "other"
    other.mkdir()
    stale = subprocess.Popen(
        ["bash", "-c", f'exec -a "SRA-API | port=9002 | pid=$$ | {socket.gethostname()}" "{titled_process}"'], cwd=other,
    )
    _set_listener_file(env, (stale.pid, "LISTEN"))
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode != 0 and stale.poll() is None
    finally:
        stale.terminate(); stale.wait(timeout=3)


def test_wrong_effective_uid_is_not_signaled(launcher_env, titled_process: Path) -> None:
    if os.geteuid() != 0 or not Path("/usr/bin/setpriv").exists():
        pytest.skip("cross-UID process requires root and setpriv")
    env, _ = launcher_env
    local_binary = Path("/tmp") / f"sra-title-helper-{os.getpid()}-{time.time_ns()}"
    shutil.copy2(titled_process, local_binary)
    local_binary.chmod(0o755)
    stale = subprocess.Popen(
        ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "bash", "-c",
         f'exec -a "SRA-API | port=9002 | pid=$$ | {socket.gethostname()}" "{local_binary}"'],
        cwd=env["BASE_DIR"],
    )
    _set_listener_file(env, (stale.pid, "LISTEN"))
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode != 0 and stale.poll() is None
    finally:
        stale.terminate(); stale.wait(timeout=3)
        local_binary.unlink(missing_ok=True)


def test_start_time_change_before_kill_fails_closed(launcher_env, titled_process: Path) -> None:
    env, _ = launcher_env
    marker = Path(env["BASE_DIR"]) / "term.marker"
    env["TERM_EVENT"] = str(marker)
    stale = subprocess.Popen(
        ["bash", "-c", f'exec -a "SRA-API | port=9002 | pid=$$ | {socket.gethostname()}" "{titled_process}"'],
        cwd=env["BASE_DIR"], env=env,
    )
    _set_listener_file(env, (stale.pid, "LISTEN"))
    real_awk = shutil.which("awk")
    assert real_awk is not None
    fake_awk = Path(env["PATH"].split(":", 1)[0]) / "awk"
    _write_executable(
        fake_awk,
        f"if [ \"$1\" = '{{print $22}}' ] && [ \"$2\" = \"/proc/{stale.pid}/stat\" ] && [ -f \"{marker}\" ]; then "
        f'v=$({real_awk} \'{{print $22}}\' "$2"); echo $((v+1)); else exec {real_awk} "$@"; fi',
    )
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=5)
        assert result.returncode != 0 and stale.poll() is None
        audit = (Path(env["BASE_DIR"]) / "SRA-API_kill_audit.log").read_text()
        assert "no SIGKILL" in audit
    finally:
        stale.kill(); stale.wait(timeout=3)


def test_stale_identity_records_are_harmless(launcher_env) -> None:
    env, events = launcher_env
    record = Path(env["API_IDENTITY_FILE"])
    record.write_text("api_pid=999999\napi_start_time=1\nport=9002\n", encoding="ascii")
    proc = _start(env)
    _wait_for(events, "handoff-worker")
    _stop(proc)
    unrelated = subprocess.Popen(["sleep", "30"], cwd=env["BASE_DIR"])
    record.write_text(f"api_pid={unrelated.pid}\napi_start_time=1\nport=9002\n", encoding="ascii")
    _set_listener_file(env, (unrelated.pid, "LISTEN"))
    try:
        result = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=3)
        assert result.returncode != 0 and unrelated.poll() is None
    finally:
        unrelated.terminate(); unrelated.wait(timeout=3)


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
    env["FAIL_SCHEDULE"] = "1"
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
