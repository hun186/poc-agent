"""SRAF OFF-2 target inventory: stdlib-only, safe, no-network observations."""
from __future__ import annotations

import json
import struct
from pathlib import Path
import sys

import pytest

from tools import sraf_airgap_off2_linux_target as tool


@pytest.fixture
def linux_target(tmp_path, monkeypatch):
    os_file = tmp_path / "os-release"
    os_file.write_text('NAME="Ubuntu Linux"\nID=ubuntu\nVERSION_ID="22.04"\n'
                       'PRETTY_NAME="SECRET HOSTNAME SHOULD NOT LEAK"\n', encoding="utf-8")
    vendor = tmp_path / "opt" / "microsoft" / "msodbcsql18" / "lib64"
    vendor.mkdir(parents=True)
    library = vendor / "libmsodbcsql-18.5.so.1.1"
    # Minimal synthetic ELF64 ET_DYN with PT_LOAD and a bounded PT_DYNAMIC:
    # NEEDED offset points into a mapped on-disk string table. Never run it.
    strings = b"\x00libodbcinst.so.2\x00"
    dyn_offset = 176
    strings_offset = 240
    size = strings_offset + len(strings)
    header = bytearray(size)
    header[:4] = b"\x7fELF"
    header[4:7] = bytes((2, 1, 1))
    header[16:18] = (3).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    struct.pack_into("<Q", header, 32, 64)
    struct.pack_into("<HH", header, 54, 56, 2)
    struct.pack_into("<IIQQQQQQ", header, 64, 1, 4, 0, 0x400000, 0,
                     size, size, 0x1000)
    struct.pack_into("<IIQQQQQQ", header, 120, 2, 4, dyn_offset,
                     0x400000 + dyn_offset, 0, 64, 64, 8)
    for index, (tag, value) in enumerate((
            (5, 0x400000 + strings_offset), (10, len(strings)),
            (1, 1), (0, 0))):
        struct.pack_into("<qQ", header, dyn_offset + index * 16, tag, value)
    header[strings_offset:] = strings
    library.write_bytes(header)
    monkeypatch.setattr(tool, "ODBC_DRIVER_ROOT", vendor)
    ini = tmp_path / "odbcinst.ini"
    ini.write_text("[ODBC Driver 18 for SQL Server]\n"
                   "Description=Secret private host\n"
                   f"Driver={library}\n", encoding="utf-8")
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
    assert observation["reason"] == "linux_python_target_odbc_dynamic_metadata_observed"
    assert observation["os_id"] == "ubuntu"
    assert observation["os_version_id"] == "22.04"
    assert observation["architecture"] == "x86_64"
    assert observation["libc_family"] == "glibc"
    assert observation["libc_version"] == "2.35"
    assert observation["python_version"] == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert observation["python_abi"] == "cpython-311-x86_64-linux-gnu"
    assert observation["odbc18"] == "REGISTERED_CONFIG_ONLY"
    assert observation["odbc_binary_header"] == "ELF64_ARCH_MATCH_HEADER_ONLY"
    assert observation["odbc_dynamic_needed"] == "DT_NEEDED_REFERENCES_PARSED_ONLY"
    assert observation["odbc_dynamic_needed_count"] == 1
    assert observation["odbc_dependency_resolution"] == "NOT_TESTED"
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



@pytest.mark.parametrize("case", [
    "missing", "symlink", "bad_elf", "elf32", "wrong_machine",
    "bad_type", "oversize", "unsupported_path", "unsupported_library_name",
    "parent_symlink",
])
def test_native_odbc_header_is_bounded_nofollow_and_no_secret_leak(
        linux_target, tmp_path, monkeypatch, case):
    paths, ini = linux_target
    vendor = tool.ODBC_DRIVER_ROOT
    library = vendor / "libmsodbcsql-18.5.so.1.1"
    if case == "missing":
        library.unlink()
    elif case == "symlink":
        old = vendor / "original.so"
        library.rename(old)
        library.symlink_to(old)
    elif case == "bad_elf":
        library.write_bytes(b"NOT_ELF" + b"*" * 60)
    elif case == "elf32":
        raw = bytearray(library.read_bytes())
        raw[4] = 1
        library.write_bytes(raw)
    elif case == "wrong_machine":
        raw = bytearray(library.read_bytes())
        raw[18:20] = (183).to_bytes(2, "little")
        library.write_bytes(raw)
    elif case == "bad_type":
        raw = bytearray(library.read_bytes())
        raw[16:18] = (2).to_bytes(2, "little")
        library.write_bytes(raw)
    elif case == "oversize":
        with library.open("r+b") as stream:
            stream.truncate(tool.MAX_ODBC_LIBRARY_BYTES + 1)
    elif case == "unsupported_path":
        ini.write_text("[ODBC Driver 18 for SQL Server]\n"
                       f"Driver={tmp_path / 'private' / 'secret.so'}\n")
    elif case == "unsupported_library_name":
        ini.write_text("[ODBC Driver 18 for SQL Server]\n"
                       f"Driver={vendor / 'malicious.so'}\n")
    elif case == "parent_symlink":
        source = tmp_path / "original_vendor"
        vendor.rename(source)
        vendor.symlink_to(source, target_is_directory=True)
    observation = tool.observe(os_paths=paths, odbc_path=ini)
    assert observation["status"] == "INCOMPLETE"
    assert observation["reason"] == "odbc18_elf_header_unverified"
    assert observation["odbc18"] == "REGISTERED_CONFIG_ONLY"
    assert observation["odbc_binary_header"] != "ELF64_ARCH_MATCH_HEADER_ONLY"
    assert observation["odbc_binary_load"] == "NOT_TESTED"
    output = json.dumps(observation)
    assert str(tmp_path) not in output and "malicious" not in output
    assert "private" not in output and "secret" not in output


def test_cross_architecture_vendor_elf_header_matches_aarch64(linux_target, monkeypatch):
    paths, ini = linux_target
    machine = tool.ODBC_DRIVER_ROOT / "libmsodbcsql-18.5.so.1.1"
    raw = bytearray(machine.read_bytes())
    raw[18:20] = (183).to_bytes(2, "little")
    machine.write_bytes(raw)
    monkeypatch.setattr(tool.platform, "machine", lambda: "aarch64")
    observed = tool.observe(os_paths=paths, odbc_path=ini)
    assert observed["status"] == "PASS_PARTIAL"
    assert observed["architecture"] == "aarch64"
    assert observed["odbc_binary_header"] == "ELF64_ARCH_MATCH_HEADER_ONLY"
    assert observed["odbc_dynamic_needed_count"] == 1



@pytest.mark.parametrize("failure", [
    "no_phdr", "too_many_phdr", "bad_phentsize", "off_end",
    "no_dynamic", "huge_dynamic", "bad_strtab_addr", "strsz_too_big",
    "needed_oob", "needed_unterminated", "needed_unsafe_name",
    "missing_dt_null", "duplicate_needed",
])
def test_odbc_dynamic_metadata_corruption_rejects_without_load(
        linux_target, failure):
    paths, ini = linux_target
    library = tool.ODBC_DRIVER_ROOT / "libmsodbcsql-18.5.so.1.1"
    raw = bytearray(library.read_bytes())
    if failure == "no_phdr":
        struct.pack_into("<H", raw, 56, 0)
    elif failure == "too_many_phdr":
        struct.pack_into("<H", raw, 56, 65535)
    elif failure == "bad_phentsize":
        struct.pack_into("<H", raw, 54, 60)
    elif failure == "off_end":
        struct.pack_into("<Q", raw, 32, 999999)
    elif failure == "no_dynamic":
        struct.pack_into("<I", raw, 120, 0)
    elif failure == "huge_dynamic":
        struct.pack_into("<Q", raw, 120 + 32, 65536 + 16)
    elif failure == "bad_strtab_addr":
        struct.pack_into("<Q", raw, 176 + 8, 0x500000)
    elif failure == "strsz_too_big":
        struct.pack_into("<Q", raw, 192 + 8, 65537)
    elif failure == "needed_oob":
        struct.pack_into("<Q", raw, 208 + 8, 50000)
    elif failure == "needed_unterminated":
        raw[-1] = ord("x")
    elif failure == "needed_unsafe_name":
        raw[241] = ord("/")
    elif failure == "missing_dt_null":
        struct.pack_into("<qQ", raw, 224, 22, 0)
    elif failure == "duplicate_needed":
        struct.pack_into("<qQ", raw, 224, 1, 1)
    library.write_bytes(raw)
    result = tool.observe(os_paths=paths, odbc_path=ini)
    assert result["status"] == "INCOMPLETE"
    assert result["reason"] == "odbc18_dynamic_metadata_unverifiable"
    assert result["odbc_binary_header"] == "ELF64_ARCH_MATCH_HEADER_ONLY"
    assert result["odbc_dynamic_needed"] == "DYNAMIC_METADATA_UNVERIFIABLE"
    assert result["odbc_dynamic_needed_count"] == 0
    assert result["odbc_binary_load"] == "NOT_TESTED"
    assert str(library) not in json.dumps(result)


def test_dynamic_needed_metadata_cannot_be_mistaken_for_library_resolution(linux_target):
    paths, ini = linux_target
    result = tool.observe(os_paths=paths, odbc_path=ini)
    assert result["odbc_dynamic_needed_count"] == 1
    assert result["odbc_dependency_resolution"] == "NOT_TESTED"
    assert "libodbcinst.so.2" not in json.dumps(result)


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
