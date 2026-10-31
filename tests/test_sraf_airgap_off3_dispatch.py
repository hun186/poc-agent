"""OFF-3 dispatcher regression without launching the real service/probes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "run_sraf_airgap_offline.sh"


@pytest.fixture
def fake_deployment(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("Bash unavailable")
    root = tmp_path / "SRAF offline root with spaces"
    root.mkdir()
    (root / "tools").mkdir()
    script = root / SOURCE.name
    script.write_bytes(SOURCE.read_bytes())
    capture = tmp_path / "capture.txt"
    py = tmp_path / "application python"
    py.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"python\" \"$PWD\" \"$@\" > \"$SRAF_CAPTURE_FILE\"\nexit 17\n",
        encoding="utf-8",
    )
    py.chmod(0o700)
    for name, exitcode in [
        ("run_sraf_airgap_off1_diagnose.sh", 19),
        ("run_sraf_airgap_off2_verify.sh", 23),
    ]:
        stub = root / name
        stub.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' '{name}' \"$PWD\" \"$@\" > \"$SRAF_CAPTURE_FILE\"\nexit {exitcode}\n",
            encoding="utf-8",
        )
        stub.chmod(0o700)
    env = {**os.environ, "SRAF_CAPTURE_FILE": str(capture),
           "SRAF_PYTHON": str(py)}
    env.pop("SRAF_OFF1_OUTPUT_DIR", None)
    return script, root, capture, env


def _exec(script, env, *args):
    return subprocess.run(["bash", str(script), *args], cwd="/", env=env,
                          capture_output=True, text=True)


def test_default_quick_is_only_canonical_anonymous_hub(fake_deployment):
    script, root, capture, env = fake_deployment
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    out = _exec(script, env)
    assert out.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off1_hub.py",
        "--suite", "quick", "--output-dir", str(root / "sraf-acceptance-results"),
    ]


def test_quick_uses_same_explicit_private_output_override(fake_deployment, tmp_path):
    script, root, capture, env = fake_deployment
    target = tmp_path / "private with spaces" / "evidence"
    env["SRAF_OFF1_OUTPUT_DIR"] = str(target)
    out = _exec(script, env, "quick")
    assert out.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off1_hub.py",
        "--suite", "quick", "--output-dir", str(target),
    ]
    assert not target.exists()


@pytest.mark.parametrize("mode,expected_entry,args,code", [
    ("diagnose", "run_sraf_airgap_off1_diagnose.sh", [], 19),
    ("no-network", "run_sraf_airgap_off1_diagnose.sh", ["--no-network"], 19),
    ("release-files", "run_sraf_airgap_off2_verify.sh", [], 23),
])
def test_all_other_modes_delegate_verbatim_to_existing_entrypoints(
        fake_deployment, mode, expected_entry, args, code):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, mode)
    assert result.returncode == code
    assert capture.read_text().splitlines() == [expected_entry, str(root), *args]


@pytest.mark.parametrize("arguments", [
    ("acceptance",), ("upgrade",), ("restore",),
    ("--live-report",), ("quick", "--live-report"), ("quick", "diagnose"),
    ("release-files", "--no-network"), ("--probe-sql-read",), ("",),
])
def test_forbidden_modes_and_extra_arguments_never_execute(
        fake_deployment, arguments):
    script, _, capture, env = fake_deployment
    result = _exec(script, env, *arguments)
    assert result.returncode == 2
    assert not capture.exists()


@pytest.mark.parametrize("value", [
    "", "output", "../unsafe", "/private\rINJECTION", "/private\nINJECTION",
])
def test_quick_rejects_bad_private_output_path_before_python(
        fake_deployment, value):
    script, _, capture, env = fake_deployment
    env["SRAF_OFF1_OUTPUT_DIR"] = value
    result = _exec(script, env, "quick")
    assert result.returncode == 2
    assert "SRAF_OFF1_OUTPUT_DIR" in result.stderr
    assert not capture.exists()


def test_help_does_not_run_any_probe(fake_deployment):
    script, _, capture, env = fake_deployment
    result = _exec(script, env, "--help")
    assert result.returncode == 0
    assert "quick|diagnose|no-network|release-files" in result.stdout
    assert not capture.exists()


def test_quick_missing_python_fails_before_probe(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "quick")
    assert result.returncode == 127
    assert not capture.exists()
