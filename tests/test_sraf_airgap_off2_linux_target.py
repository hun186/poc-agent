"""SRAF OFF-2 target inventory: stdlib-only, safe, no-network observations."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from tools import sraf_airgap_off2_linux_target as tool


@pytest.fixture
def linux_target(tmp_path, monkeypatch):
    os_file = tmp_path / "os-release"
    os_file.write_text('NAME="Ubuntu Linux"\nID=ubuntu\nVERSION_ID="22.04"\n'
                       'PRETTY_NAME="SECRET HOSTNAME SHOULD NOT LEAK"\n', encoding="utf-8")
    ini = tmp_path / "odbcinst.ini"
    ini.write_text("[ODBC Driver 18 for SQL Server]\n"
                   "Description=Secret private host\n"
                   "Driver=/private/secret/libmsodbcsql-18.so\n", encoding="utf-8")
    monkeypatch.setattr(tool.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tool.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(tool.platform, "libc_ver", lambda: ("glibc", "2.35"))
    monkeypatch.setattr(tool.sysconfig, "get_config_var",
                        lambda key: "cpython-311-x86_64-linux-gnu" if key == "SOABI" else None)
    monkeypatch.delenv("ODBCSYSINI", raising=False)
    monkeypatch.delenv("ODBCINSTINI", raising=False)
    return (os_file,), ini


def test_linux_python_abi_and_odbc_registration_only_partial(linux_target):
    paths, ini = linux_target
    observation = tool.observe(os_paths=paths, odbc_path=ini)
    assert observation["status"] == "PASS_PARTIAL"
    assert observation["reason"] == "linux_python_target_and_odbc_config_observed"
    assert observation["os_id"] == "ubuntu"
    assert observation["os_version_id"] == "22.04"
    assert observation["architecture"] == "x86_64"
    assert observation["libc_family"] == "glibc"
    assert observation["libc_version"] == "2.35"
    assert observation["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert observation["python_abi"] == "cpython-311-x86_64-linux-gnu"
    assert observation["odbc18"] == "REGISTERED_CONFIG_ONLY"
    assert observation["odbc_binary_load"] == "NOT_TESTED"
    assert observation["wheelhouse_compatibility"] == "NOT_TESTED"
    assert observation["full_live"] == "NOT_TESTED"
    assert observation["production_release_ready"] is False
    rendered = json.dumps(observation)
    assert "SECRET" not in rendered and "/private" not in rendered
    assert str(ini) not in rendered


def test_no_distribution_or_alternate_linux_is_incomplete(linux_target, monkeypatch):
    paths, ini = linux_target
    monkeypatch.setattr(tool.platform, "system", lambda: "Darwin")
    result = tool.observe(os_paths=paths, odbc_path=ini)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "linux_target_required"
    assert result["odbc18"] == "CONFIG_UNVERIFIABLE"
    monkeypatch.setattr(tool.platform, "system", lambda: "Linux")
    paths[0].write_text("ID=unknown_secret\nVERSION_ID=2026.8\n", encoding="utf-8")
    result = tool.observe(os_paths=paths, odbc_path=ini)
    assert result["status"] == "INCOMPLETE"
    assert result["os_id"] == "UNVERIFIED"
    assert "unknown_secret" not in json.dumps(result)


@pytest.mark.parametrize("case", ["symlink", "oversize", "bad_utf8", "duplicate", "missing"])
def test_os_release_untrusted_or_unreadable_never_passes(linux_target, tmp_path, case):
    paths, ini = linux_target
    source = paths[0]
    if case == "symlink":
        source.unlink()
        secret = tmp_path / "secret.txt"
        secret.write_text("ID=ubuntu\nVERSION_ID=22.04\n")
        source.symlink_to(secret)
    elif case == "oversize":
        source.write_bytes(b"x" * (tool.MAX_RELEASE_BYTES + 1))
    elif case == "bad_utf8":
        source.write_bytes(b"\xff")
    elif case == "duplicate":
        source.write_text("ID=ubuntu\nID=debian\nVERSION_ID=22.04\n")
    else:
        source.unlink()
    observed = tool.observe(os_paths=paths, odbc_path=ini)
    assert observed["status"] == "INCOMPLETE"
    assert observed["os_id"] == "UNVERIFIED"


@pytest.mark.parametrize("case", ["missing", "symlink", "empty", "duplicate", "oversize",
                                   "config_override"])
def test_odbc_config_always_fails_closed_when_unverifiable(
        linux_target, tmp_path, monkeypatch, case):
    paths, ini = linux_target
    if case == "missing":
        ini.unlink()
    elif case == "symlink":
        secret = tmp_path / "secret.ini"
        ini.rename(secret)
        ini.symlink_to(secret)
    elif case == "empty":
        ini.write_text("[other driver]\nDriver=/tmp/other.so\n")
    elif case == "duplicate":
        ini.write_text("[ODBC Driver 18 for SQL Server]\nDriver=/one\n"
                       "[ODBC Driver 18 for SQL Server]\nDriver=/two\n")
    elif case == "oversize":
        ini.write_bytes(b"a" * (tool.MAX_ODBC_BYTES + 1))
    else:
        monkeypatch.setenv("ODBCSYSINI", "/secret/odbc")
    result = tool.observe(os_paths=paths, odbc_path=ini)
    assert result["status"] == "INCOMPLETE"
    assert result["odbc18"] != "REGISTERED_CONFIG_ONLY"


def test_unknown_abi_arch_and_libc_remain_unverified(linux_target, monkeypatch):
    paths, ini = linux_target
    monkeypatch.setattr(tool.platform, "machine", lambda: "secret private arch")
    monkeypatch.setattr(tool.platform, "libc_ver", lambda: ("secret", "99.88"))
    monkeypatch.setattr(tool.sysconfig, "get_config_var", lambda _: "/secret/abi")
    result = tool.observe(os_paths=paths, odbc_path=ini)
    assert result["status"] == "INCOMPLETE"
    assert result["architecture"] == "UNVERIFIED"
    assert result["python_abi"] == "UNVERIFIED"
    assert result["libc_family"] == "UNVERIFIED"
    assert "secret" not in json.dumps(result).lower()


def test_cli_rejects_extra_arguments(monkeypatch):
    with pytest.raises(SystemExit) as error:
        tool.main(["--live-report"])
    assert error.value.code == 2


def test_cli_incomplete_json_does_not_expose_host_values(monkeypatch, capsys):
    monkeypatch.setattr(tool, "observe", lambda: {
        "schema": tool.SCHEMA, "status": "INCOMPLETE",
        "reason": "linux_target_required", "scope": tool.SCOPE,
        "full_live": "NOT_TESTED", "production_release_ready": False,
    })
    assert tool.main([]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "INCOMPLETE"
    assert data["production_release_ready"] is False
