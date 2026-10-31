"""Pure Bash operator entry tests; never contact a service or mutate deployment."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "run_sraf_airgap_off2_verify.sh"
PIN = "a" * 64


@pytest.fixture
def launcher(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("Linux Bash not available")
    root = tmp_path / "SRAF shared install"
    root.mkdir()
    script = root / SOURCE.name
    script.write_bytes(SOURCE.read_bytes())
    python_bin = tmp_path / "app python"
    python_bin.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$PWD\" \"$@\" > \"$SRAF_CAPTURE_FILE\"\nexit 17\n",
        encoding="utf-8",
    )
    python_bin.chmod(0o700)
    capture = tmp_path / "capture.txt"
    env = {**os.environ, "SRAF_PYTHON": str(python_bin),
           "SRAF_CAPTURE_FILE": str(capture)}
    env.pop("SRAF_OFF2_TRUSTED_MANIFEST_SHA256", None)
    return script, root, capture, env


def test_syntax_and_forward_only_trusted_pin(launcher):
    script, root, capture, env = launcher
    env["SRAF_OFF2_TRUSTED_MANIFEST_SHA256"] = PIN
    check = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    out = subprocess.run(["bash", str(script)], cwd="/", env=env,
                         capture_output=True, text=True)
    assert out.returncode == 17
    assert capture.read_text().splitlines() == [
        str(root), "tools/sraf_airgap_off2_manifest_check.py",
        "--expected-manifest-sha256", PIN,
    ]
    assert not (root / "sraf-acceptance-results").exists()


@pytest.mark.parametrize("digest", [
    None, "", "a" * 63, "a" * 65, "A" * 64,
    "a" * 31 + "/" + "a" * 32, "secret\nTOKEN", "../" + "a" * 64,
])
def test_missing_or_invalid_digest_never_invokes_python(launcher, digest):
    script, _, capture, env = launcher
    if digest is not None:
        env["SRAF_OFF2_TRUSTED_MANIFEST_SHA256"] = digest
    out = subprocess.run(["bash", str(script)], cwd="/", env=env,
                         capture_output=True, text=True)
    assert out.returncode == 2
    assert "trusted_manifest_digest_not_supplied" in out.stdout
    assert "secret" not in out.stdout.lower()
    assert not capture.exists()


@pytest.mark.parametrize("args", [["--force"], ["--expected-manifest-sha256", PIN]])
def test_no_operator_supplied_extra_shell_arguments(launcher, args):
    script, _, capture, env = launcher
    env["SRAF_OFF2_TRUSTED_MANIFEST_SHA256"] = PIN
    out = subprocess.run(["bash", str(script), *args], cwd="/",
                         env=env, capture_output=True, text=True)
    assert out.returncode == 2
    assert not capture.exists()


def test_application_python_missing_prevents_all_reading(launcher):
    script, _, capture, env = launcher
    env["SRAF_OFF2_TRUSTED_MANIFEST_SHA256"] = PIN
    env["SRAF_PYTHON"] = "/no/venv/python"
    out = subprocess.run(["bash", str(script)], cwd="/",
                         env=env, capture_output=True, text=True)
    assert out.returncode == 2
    assert "application_python_unavailable" in out.stdout
    assert not capture.exists()
