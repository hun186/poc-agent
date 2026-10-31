"""Shell launcher contract tests without network or any real SRAF process."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run_sraf_airgap_off1_diagnose.sh"


@pytest.fixture
def isolated_launcher(tmp_path):
    if shutil.which("bash") is None:
        pytest.skip("Linux bash unavailable")
    project = tmp_path / "SRAF project with spaces"
    project.mkdir()
    (project / "tools").mkdir()
    launcher = project / SCRIPT.name
    launcher.write_bytes(SCRIPT.read_bytes())
    fake_python = tmp_path / "app python"
    fake_python.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$PWD" "$@" > "$SRAF_CAPTURE_FILE"\nexit 17\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    capture = tmp_path / "captured.txt"
    env = {**os.environ, "SRAF_PYTHON": str(fake_python),
           "SRAF_CAPTURE_FILE": str(capture), "HOME": str(tmp_path)}
    return launcher, project, capture, env


def test_script_syntax_and_fixed_diagnostic_args(isolated_launcher):
    launcher, project, capture, env = isolated_launcher
    syntax = subprocess.run(["bash", "-n", str(launcher)],
                            capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    outcome = subprocess.run(["bash", str(launcher)],
                             cwd="/", env=env, capture_output=True, text=True)
    assert outcome.returncode == 17  # Python process exit code propagates.
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(project), "tools/sraf_airgap_off1_hub.py", "--suite", "diagnose",
        "--output-dir", str(project / "sraf-acceptance-results")
    ]


def test_unset_home_still_writes_under_project_root(isolated_launcher):
    launcher, project, capture, env = isolated_launcher
    env.pop("HOME", None)
    outcome = subprocess.run(["bash", str(launcher)], cwd="/",
                             env=env, capture_output=True, text=True)
    assert outcome.returncode == 17
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(project), "tools/sraf_airgap_off1_hub.py", "--suite", "diagnose",
        "--output-dir", str(project / "sraf-acceptance-results")
    ]


def test_missing_application_python_is_rejected(isolated_launcher):
    launcher, _, capture, env = isolated_launcher
    env["SRAF_PYTHON"] = "/this/python/does/not/exist"
    outcome = subprocess.run(["bash", str(launcher)],
                             env=env, capture_output=True, text=True)
    assert outcome.returncode == 127
    assert "SRAF Python is not available" in outcome.stderr
    assert not capture.exists()


def test_explicit_es_flag_is_forwarded_without_other_changes(isolated_launcher):
    launcher, project, capture, env = isolated_launcher
    result = subprocess.run(
        ["bash", str(launcher), "--probe-es-tls-mapping"],
        cwd="/", env=env, capture_output=True, text=True)
    assert result.returncode == 17
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(project), "tools/sraf_airgap_off1_hub.py", "--suite", "diagnose",
        "--output-dir", str(project / "sraf-acceptance-results"),
        "--probe-es-tls-mapping",
    ]


@pytest.mark.parametrize("arguments", [
    ("--live-report",), ("--probe-es-tls-mapping", "--live-report"),
    ("--no-network",), ("--bad-flag",), ("",),
])
def test_shell_rejects_any_nonallowlisted_option(isolated_launcher, arguments):
    launcher, _, capture, env = isolated_launcher
    result = subprocess.run(["bash", str(launcher), *arguments],
                            cwd="/", env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert not capture.exists()
