"""OFF-3 dispatcher regression without launching the real service/probes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/diagnostics/run_sraf_airgap_offline.sh"


@pytest.fixture
def fake_deployment(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("Bash unavailable")
    root = tmp_path / "SRAF offline root with spaces"
    root.mkdir()
    (root / "tools").mkdir()
    (root / "scripts" / "diagnostics").mkdir(parents=True)
    script = root / "scripts" / "diagnostics" / SOURCE.name
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
        stub = root / "scripts" / "diagnostics" / name
        stub.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' '{name}' \"$PWD\" \"$@\" > \"$SRAF_CAPTURE_FILE\"\nexit {exitcode}\n",
            encoding="utf-8",
        )
        stub.chmod(0o700)
    env = {**os.environ, "SRAF_CAPTURE_FILE": str(capture),
           "SRAF_PYTHON": str(py)}
    env.pop("SRAF_OFF1_OUTPUT_DIR", None)
    env.pop("SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256", None)
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


def test_wheel_files_with_external_pin_dispatches_only_local_verifier(fake_deployment):
    script, root, capture, env = fake_deployment
    pin = "a" * 64
    env["SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256"] = pin
    result = _exec(script, env, "wheel-files")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_wheel_files.py",
        "--expected-manifest-sha256", pin,
    ]
    assert pin not in result.stdout + result.stderr


@pytest.mark.parametrize("pin", ["", "A" * 64, "0" * 63, "not-a-digest"])
def test_wheel_files_missing_or_untrusted_pin_blocks_before_python(
        fake_deployment, pin):
    script, _, capture, env = fake_deployment
    env["SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256"] = pin
    result = _exec(script, env, "wheel-files")
    assert result.returncode == 2
    assert "INCOMPLETE" in result.stdout
    assert not capture.exists()


def test_wheel_files_missing_interpreter_blocks_before_python(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256"] = "a" * 64
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "wheel-files")
    assert result.returncode == 2
    assert not capture.exists()


def test_runtime_deps_selects_local_python_metadata_reader(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "runtime-deps")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_runtime_deps.py",
    ]


def test_runtime_deps_missing_python_is_incomplete(fake_deployment):
    script, root, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "runtime-deps")
    assert result.returncode == 2
    assert "application_python_unavailable" in result.stdout
    assert not capture.exists()


def test_runtime_deps_user_site_is_explicit_only_selected_python(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "runtime-deps-user-site")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_user_site.py",
    ]


def test_runtime_deps_user_site_missing_python_is_incomplete(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "runtime-deps-user-site")
    assert result.returncode == 2
    assert "application_python_unavailable" in result.stdout
    assert not capture.exists()


def test_runtime_launchers_routes_to_selected_python_without_live_probe(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "runtime-launchers")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_runtime_launchers.py",
    ]


def test_runtime_launchers_missing_python_is_incomplete(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "runtime-launchers")
    assert result.returncode == 2
    assert "application_python_unavailable" in result.stdout
    assert not capture.exists()


def test_deploy_check_selects_exact_application_python_without_evidence_dir(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "deploy-check")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_local_deploy_quickcheck.py",
    ]
    assert not (root / "sraf-acceptance-results").exists()


def test_deploy_check_missing_python_is_safe_and_does_not_run(fake_deployment):
    script, root, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "deploy-check")
    assert result.returncode == 2
    assert "application_python_unavailable" in result.stdout
    assert not capture.exists()
    assert not (root / "sraf-acceptance-results").exists()


def test_target_platform_runs_only_application_python_without_network(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "target-platform")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_linux_target.py",
    ]


def test_target_platform_missing_python_is_incomplete_before_exec(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "target-platform")
    assert result.returncode == 2
    assert "application_python_unavailable" in result.stdout
    assert not capture.exists()


def test_release_policy_is_only_local_readonly_advisory_python(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "release-policy")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_policy_coverage.py",
    ]


def test_release_deps_is_only_bounded_local_audit(fake_deployment):
    script, root, capture, env = fake_deployment
    result = _exec(script, env, "release-deps")
    assert result.returncode == 17
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_airgap_off2_requirements_audit.py",
    ]


def test_release_deps_missing_python_fails_before_any_exec(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "release-deps")
    assert result.returncode == 127
    assert not capture.exists()


def test_release_policy_missing_interpreter_fails_before_exec(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "release-policy")
    assert result.returncode == 127
    assert not capture.exists()



@pytest.mark.parametrize("arguments", [
    ("acceptance",), ("upgrade",), ("restore",),
    ("--live-report",), ("quick", "--live-report"), ("quick", "diagnose"),
    ("release-files", "--no-network"), ("release-policy", "--live-report"),
    ("release-policy", "--probe-sql-read"),
    ("release-deps", "--live-report"), ("release-deps", "--probe-sql-read"), ("target-platform", "--live-report"),
    ("target-platform", "--probe-sql-read"),
    ("runtime-deps", "--live-report"), ("runtime-deps", "--probe-sql-read"),
    ("deploy-check", "--live-report"), ("deploy-check", "--probe-sql-read"),
    ("runtime-launchers", "--probe-sql-read"), ("runtime-launchers", "--live-report"),
    ("runtime-deps-user-site", "--live-report"), ("runtime-deps-user-site", "--probe-sql-read"), ("wheel-files", "--no-network"),
    ("--probe-sql-read",), ("",),
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
    assert "quick|diagnose|no-network|release-files|release-policy|release-deps|wheel-files|target-platform|runtime-deps|runtime-deps-user-site|runtime-launchers|deploy-check" in result.stdout
    assert not capture.exists()


def test_quick_missing_python_fails_before_probe(fake_deployment):
    script, _, capture, env = fake_deployment
    env["SRAF_PYTHON"] = "/not-present/python"
    result = _exec(script, env, "quick")
    assert result.returncode == 127
    assert not capture.exists()

def test_wheel_files_operator_command_is_one_line_with_pin():
    documentation = (
        ROOT / "docs/operations/sraf_airgap_off2_wheel_files.md"
    ).read_text(encoding="utf-8")
    assert (
        "SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256="
        "<trusted-64-char-lowercase-sha256> "
        "bash scripts/diagnostics/run_sraf_airgap_offline.sh wheel-files"
    ) in documentation




# Accessible, zero-memory operator shortcut: this is a thin OFF-3 alias, not
# another probe, report writer, privileged menu or service launcher.
ONE_CLICK = ROOT / "0_一鍵快檢_SRAF.sh"


def _copy_one_click(fake_deployment):
    script, root, capture, env = fake_deployment
    shortcut = root / ONE_CLICK.name
    shutil.copy2(ONE_CLICK, shortcut)
    return shortcut, root, capture, env


def test_one_click_file_is_executable_and_release_selected():
    import json
    import stat

    assert ONE_CLICK.is_file()
    assert ONE_CLICK.stat().st_mode & stat.S_IXUSR
    policy = json.loads(
        (ROOT / "tools/deployment_manifest_policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert ONE_CLICK.name in policy["managed_files"]


def test_one_click_with_zero_args_is_only_passive_deploy_check(fake_deployment):
    shortcut, root, capture, env = _copy_one_click(fake_deployment)
    assert subprocess.run(["bash", "-n", str(shortcut)]).returncode == 0
    # An executable checkout file can be launched without remembering 'bash'.
    result = subprocess.run([str(shortcut)], cwd="/", env=env,
                            capture_output=True, text=True)
    assert result.returncode == 17
    assert "一鍵快檢" in result.stdout
    assert "FULL_LIVE" in result.stdout
    assert capture.read_text().splitlines() == [
        "python", str(root), "tools/sraf_local_deploy_quickcheck.py",
    ]
    assert not (root / "sraf-acceptance-results").exists()


def test_one_click_help_and_invalid_options_never_start_probe(fake_deployment):
    shortcut, root, capture, env = _copy_one_click(fake_deployment)
    help_result = subprocess.run(["bash", str(shortcut), "--help"], cwd="/",
                                 env=env, capture_output=True, text=True)
    assert help_result.returncode == 0
    assert "deploy-check" not in help_result.stdout
    assert "SRAF_DEPLOY_CHECK_JSON=" in help_result.stdout
    assert not capture.exists()
    for option in ("quick", "diagnose", "acceptance", "--probe-es-tls-mapping", ""):
        result = subprocess.run(["bash", str(shortcut), option], cwd="/",
                                env=env, capture_output=True, text=True)
        assert result.returncode == 2
        assert "unsupported_option" in result.stderr
        assert not capture.exists()
    assert not (root / "sraf-acceptance-results").exists()


def test_one_click_preserves_final_json_and_underlying_exit_code(fake_deployment):
    shortcut, root, capture, env = _copy_one_click(fake_deployment)
    py = Path(env["SRAF_PYTHON"])
    # Real coordinator owns the last JSON line. The shortcut must never append
    # a banner/extra warning after it, including on nonzero exit.
    py.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' 'SRAF_DEPLOY_CHECK_JSON={\"status\":\"INCOMPLETE\"}'\n"
        "exit 2\n",
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(shortcut)], cwd="/", env=env,
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert result.stdout.splitlines()[-1] == (
        'SRAF_DEPLOY_CHECK_JSON={"status":"INCOMPLETE"}'
    )
    assert not (root / "sraf-acceptance-results").exists()


def test_advanced_shell_entries_live_only_under_diagnostics_and_are_pinned():
    import json

    root = ROOT
    advanced = (
        "run_sraf_airgap_offline.sh",
        "run_sraf_airgap_off1_diagnose.sh",
        "run_sraf_airgap_off2_verify.sh",
    )
    policy = json.loads(
        (root / "tools/deployment_manifest_policy.json").read_text(
            encoding="utf-8"
        )
    )
    for name in advanced:
        assert not (root / name).exists()
        nested = "scripts/diagnostics/" + name
        assert (root / nested).is_file()
        assert nested in policy["managed_files"]
        assert name not in policy["managed_files"]
    assert (root / "0_一鍵快檢_SRAF.sh").is_file()
    assert (root / "run_sra_api.sh").is_file()


def test_advanced_launchers_are_shell_syntax_valid_after_move():
    for name in (
        "run_sraf_airgap_offline.sh",
        "run_sraf_airgap_off1_diagnose.sh",
        "run_sraf_airgap_off2_verify.sh",
    ):
        script = ROOT / "scripts" / "diagnostics" / name
        assert subprocess.run(["bash", "-n", str(script)],
                              capture_output=True, text=True).returncode == 0
