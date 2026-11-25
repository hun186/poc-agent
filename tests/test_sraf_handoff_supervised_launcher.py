"""Preserve public HTTP launcher and supervisor ownership on explicit opt-in."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from api import run_api

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("flags,https", [(["--http"], False), ([], True), (["--ssl"], True)])
def test_explicit_http_preserves_legacy_public_transport(monkeypatch, flags, https):
    called = []
    monkeypatch.setattr(run_api, "should_use_https", lambda **kw: True)
    monkeypatch.setattr(run_api, "make_adhoc_cert_with_openssl",
                        lambda *a: ("fixture.crt", "fixture.key", "fixture-dir"))
    monkeypatch.setattr(run_api.uvicorn, "run", lambda app, **kwargs: called.append(kwargs))
    monkeypatch.setattr(run_api.app.state, "handoff_public_listener_port", None, raising=False)
    monkeypatch.setattr(sys, "argv", ["run_api", "--public", "--port", "9123", *flags])
    run_api.main()
    assert run_api.app.state.handoff_public_listener_port == 9123
    assert len(called) == 1
    assert called[0]["host"] == "0.0.0.0" and called[0]["port"] == 9123
    assert called[0]["workers"] == 1
    assert ("ssl_certfile" in called[0]) == https


def test_conflicting_transport_flags_denied(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_api", "--ssl", "--http"])
    with pytest.raises(SystemExit) as exc:
        run_api.main()
    assert exc.value.code == 2


def test_invalid_shell_opt_in_fails_before_runtime_changes(tmp_path):
    result = subprocess.run(["bash", str(ROOT / "run_sra_api.sh")],
        env={**os.environ, "BASE_DIR": str(tmp_path), "SRAF_HANDOFF_SUPERVISED_LAUNCH": "typo"},
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "Invalid SRAF_HANDOFF_SUPERVISED_LAUNCH" in result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("flag,expected", [
    ("0", "uvicorn api.main:app --host 0.0.0.0 --port 9123"),
    ("1", "python -m api.run_api --public --http --port 9123"),
])
def test_actual_shell_spawn_branch_keeps_child_pid_and_port(tmp_path, flag, expected):
    # Execute the exact spawn block with command stubs, not the real
    # supervisor, bootstrap, workers, or any production service.
    script = (ROOT / "run_sra_api.sh").read_text(encoding="utf-8")
    start = script.index('if [ "$SRAF_HANDOFF_SUPERVISED_LAUNCH" = 1 ]; then')
    end = script.index('CHILD_PIDS+=("$!");', start)
    block = script[start:end]
    code = '''
set -euo pipefail
exec 9>/dev/null
cap_log() { cat > "$1"; printf done > "$1.done"; }
python() { printf 'python %s\\n' "$*"; }
uvicorn() { printf 'uvicorn %s\\n' "$*"; }
''' + block + '''
child="$!"
[[ "$child" =~ ^[0-9]+$ ]]
wait "$child"
# Bash process substitution is a separate child; wait for logger EOF.
for ((i=0; i<100; i++)); do
  [ -s "$API_LOG.done" ] && break
  sleep 0.01
done
[ -s "$API_LOG.done" ]
'''
    out = tmp_path / "api.log"
    result = subprocess.run(["bash", "-c", code],
        env={**os.environ, "SRAF_HANDOFF_SUPERVISED_LAUNCH": flag,
             "PORT": "9123", "API_LOG": str(out)}, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert out.read_text().strip() == expected
