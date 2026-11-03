"""Synthetic, read-only OFF-2 startup interpreter equality checks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import sraf_airgap_off2_runtime_launchers as target


@pytest.fixture
def identities(tmp_path):
    exe = tmp_path / "python3.10"
    exe.write_bytes(b"fake-test-python")
    exe.chmod(0o755)
    cli = tmp_path / "uvicorn"
    cli.write_text(f"#!{exe}\n# synthetic fixture; never executed\n", encoding="ascii")
    cli.chmod(0o755)
    return exe, cli


def inspect(exe, cli, python_path=None):
    return target.observe(
        selected=str(exe),
        python_path=str(exe if python_path is None else python_path),
        uvicorn_path=str(cli),
    )


def test_same_launcher_interpreter_is_only_partial(identities):
    exe, cli = identities
    out = inspect(exe, cli)
    assert out["schema"] == target.SCHEMA
    assert out["status"] == "PASS_PARTIAL"
    assert out["path_python_identity"] == "MATCH"
    assert out["uvicorn_shebang_identity"] == "DIRECT_MATCH"
    assert out["api_worker_runtime_verified"] is False
    assert out["actual_service_uid_verified"] is False
    assert out["running_process_verified"] is False
    assert out["native_odbc_load"] == "NOT_TESTED"
    assert out["package_imports"] == "NOT_TESTED"
    assert out["production_release_ready"] is False
    assert str(exe) not in json.dumps(out)
    assert str(cli) not in json.dumps(out)


def test_python_mismatch_is_incomplete_even_when_uvicorn_matches(identities, tmp_path):
    exe, cli = identities
    other = tmp_path / "other-python"
    other.write_bytes(b"fake")
    out = inspect(exe, cli, other)
    assert out["status"] == "INCOMPLETE"
    assert out["reason"] == "path_python_selected_interpreter_mismatch"
    assert out["path_python_identity"] == "MISMATCH"


def test_two_venvs_sharing_base_python_never_count_as_identical(tmp_path):
    base = tmp_path / "python3-base"
    base.write_bytes(b"fake python shared base")
    base.chmod(0o755)
    a = tmp_path / "venvA" / "bin"
    b = tmp_path / "venvB" / "bin"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "python").symlink_to(base)
    (b / "python").symlink_to(base)
    console = tmp_path / "uvicorn"
    console.write_text(f"#!{a / 'python'}\n")

    # The binaries have the same device/inode, but different venv/bin
    # entrypoints must not be reported as matching environments.
    assert target._same_file(str(a / "python"), str(b / "python")) is False
    out = target.observe(
        selected=str(a / "python"),
        python_path=str(b / "python"),
        uvicorn_path=str(console),
    )
    assert out["status"] == "INCOMPLETE"
    assert out["path_python_identity"] == "MISMATCH"
    assert out["production_release_ready"] is False


def test_uvicorn_other_venv_is_not_accepted_when_path_python_matches(tmp_path):
    base = tmp_path / "python3-base"
    base.write_bytes(b"fake python shared base")
    base.chmod(0o755)
    a = tmp_path / "first-venv" / "bin"
    b = tmp_path / "second-venv" / "bin"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "python").symlink_to(base)
    (b / "python").symlink_to(base)
    cli = tmp_path / "uvicorn"
    cli.write_text(f"#!{b / 'python'}\n")
    out = target.observe(
        selected=str(a / "python"),
        python_path=str(a / "python"),
        uvicorn_path=str(cli),
    )
    assert out["status"] == "INCOMPLETE"
    assert out["uvicorn_shebang_identity"] == "MISMATCH"
    assert out["production_release_ready"] is False


def test_uvicorn_shebang_mismatch_is_incomplete(identities, tmp_path):
    exe, cli = identities
    other = tmp_path / "other-python"
    other.write_bytes(b"fake")
    cli.write_text(f"#!{other}\n")
    out = inspect(exe, cli)
    assert out["status"] == "INCOMPLETE"
    assert out["reason"] == "uvicorn_shebang_selected_interpreter_mismatch"
    assert out["uvicorn_shebang_identity"] == "MISMATCH"


@pytest.mark.parametrize("script", [
    "#!/usr/bin/env -S python -s\n",
    "#!/usr/bin/python3 -s\n",
    "#!/usr/bin/python3 -I\n",
    "#!/bin/sh\n",  # Valid shell shebang must NOT match Python.
    "#!/relative/python\n",
    "#!/usr/bin/env python3 -s\n",
    "#!/usr/bin/env bash\n",
    "not a shebang\n",
    "#!/usr/bin/python3\r\n",
])
def test_unsupported_or_unsafe_shebang_fails_closed(identities, script):
    exe, cli = identities
    cli.write_text(script, encoding="ascii")
    out = inspect(exe, cli)
    assert out["status"] == "INCOMPLETE"
    assert out["uvicorn_shebang_identity"] in ("UNVERIFIABLE", "MISMATCH")
    assert out["production_release_ready"] is False


def test_env_python3_resolves_only_checked_executable(identities, monkeypatch):
    exe, cli = identities
    cli.write_text("#!/usr/bin/env python3\n")
    original_which = target.shutil.which
    monkeypatch.setattr(
        target.shutil, "which",
        lambda name: str(exe) if name == "python3" else original_which(name),
    )
    out = inspect(exe, cli)
    assert out["status"] == "PASS_PARTIAL"
    assert out["uvicorn_shebang_identity"] == "ENV_MATCH"


def test_env_python3_mismatch_fails_closed(identities, monkeypatch, tmp_path):
    exe, cli = identities
    other = tmp_path / "python3"
    other.write_bytes(b"different")
    cli.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setattr(target.shutil, "which", lambda name: str(other))
    out = inspect(exe, cli)
    assert out["status"] == "INCOMPLETE"
    assert out["uvicorn_shebang_identity"] == "MISMATCH"


@pytest.mark.parametrize("kind", ["symlink_script", "symlink_parent", "oversized", "no_shebang"])
def test_dangerous_or_unknown_script_is_never_followed_or_accepted(
        identities, tmp_path, kind):
    exe, cli = identities
    path = cli
    if kind == "symlink_script":
        other = tmp_path / "secret"
        other.write_text(f"#!{exe}\nPRIVATE_SECRET\n")
        cli.unlink()
        cli.symlink_to(other)
    elif kind == "symlink_parent":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        path = alias / cli.name
    elif kind == "oversized":
        cli.write_bytes(f"#!{exe}\n".encode() + b"x" * target.MAX_SCRIPT_BYTES)
    else:
        cli.write_text("uvicorn without shebang\n")
    out = inspect(exe, path)
    assert out["status"] == "INCOMPLETE"
    assert out["uvicorn_shebang_identity"] == "UNVERIFIABLE"
    assert "PRIVATE_SECRET" not in json.dumps(out)


def test_missing_entrypoint_is_incomplete(identities, tmp_path):
    exe, cli = identities
    out = inspect(exe, tmp_path / "missing-uvicorn")
    assert out["status"] == "INCOMPLETE"
    assert out["uvicorn_shebang_identity"] == "UNVERIFIABLE"


def test_active_user_site_is_local_selected_python_only(identities, monkeypatch, tmp_path):
    exe, cli = identities
    home = str(tmp_path / "user-site")
    monkeypatch.setattr(target.site, "ENABLE_USER_SITE", True)
    monkeypatch.setattr(target.site, "getusersitepackages", lambda: home)
    monkeypatch.setattr(target.sys, "path", [home])
    out = inspect(exe, cli)
    assert out["selected_python_user_site_active"] is (
        not target.sys.flags.no_user_site
    )
    assert out["api_worker_runtime_verified"] is False
    monkeypatch.setattr(target.site, "ENABLE_USER_SITE", False)
    assert inspect(exe, cli)["selected_python_user_site_active"] is False


def test_cli_output_has_no_paths_or_unapproved_modes(identities, monkeypatch, capsys):
    exe, cli = identities
    monkeypatch.setattr(target.sys, "executable", str(exe))
    monkeypatch.setattr(target.shutil, "which", lambda name: str(exe) if name == "python" else str(cli))
    assert target.main([]) == 0
    result = capsys.readouterr().out
    assert json.loads(result)["status"] == "PASS_PARTIAL"
    assert str(exe) not in result
    assert str(cli) not in result
    with pytest.raises(SystemExit) as e:
        target.main(["--active-worker-probe"])
    assert e.value.code == 2
