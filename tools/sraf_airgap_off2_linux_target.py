#!/usr/bin/env python3
"""Read-only OFF-2 Linux target Python/OS/ODBC inventory, not deployment acceptance.

Run using the Python interpreter intended for SRAF.  The command performs no
network access, subprocess invocation, code installation, package import from
a deployment registry, file write, native ODBC load or authentication.  It
prints allowlisted non-secret target fields only, for human review of the
future target-specific Wheelhouse build.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import sysconfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_manifest_check import (_UnsafeEvidence, _fingerprint, _flags, _open_beneath)

SCHEMA = "sraf_off2_linux_target_inventory_v2"
SCOPE = "TARGET_IDENTITY_ONLY_NOT_PACKAGE_OR_AIRGAP_ATTESTATION"
OS_RELEASE_FILES = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
ODBC_INST_FILE = Path("/etc/odbcinst.ini")
MAX_RELEASE_BYTES = 16 * 1024
MAX_ODBC_BYTES = 32 * 1024
MAX_ODBC_LIBRARY_BYTES = 128 * 1024 * 1024
ODBC_DRIVER_ROOT = Path("/opt/microsoft/msodbcsql18/lib64")
_ODBC_LIBRARY_NAME = re.compile(r"libmsodbcsql-18\.[0-9]{1,3}\.so\.[0-9]{1,3}\.[0-9]{1,3}")
ALLOWED_OS_IDS = frozenset((
    "ubuntu", "debian", "rhel", "rocky", "almalinux", "centos", "fedora",
    "ol", "sles", "opensuse-leap", "amzn", "alpine",
))
ALLOWED_ARCH = frozenset(("x86_64", "aarch64"))
_VERSION = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){0,2}")
_ABI = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_DRIVER_SECTION = "ODBC Driver 18 for SQL Server"


def _read_bounded(path: Path, limit: int) -> str:
    """Open by an existing directory FD without following the selected file."""
    fd = os.open(path.parent, _flags(directory=True))
    try:
        _, _, raw = _fingerprint(fd, path.name, limit, contents=True)
        if raw is None:
            raise _UnsafeEvidence
        return raw.decode("utf-8")
    finally:
        os.close(fd)


def _read_os_release(paths: tuple[Path, ...]) -> tuple[str, str] | None:
    # Only two fixed distribution-owned locations. If /etc/os-release is a
    # symlink, do not follow it; /usr/lib/os-release is the supported fallback.
    for path in paths:
        try:
            raw = _read_bounded(path, MAX_RELEASE_BYTES)
        except (OSError, UnicodeError, _UnsafeEvidence, ValueError):
            continue
        fields: dict[str, str] = {}
        valid = True
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep != "=" or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                valid = False
                break
            if key not in {"ID", "VERSION_ID"}:
                continue
            if key in fields:
                valid = False
                break
            # Do not execute shell syntax or interpolate any value.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            fields[key] = value
        if not valid:
            continue
        os_id = fields.get("ID", "")
        version = fields.get("VERSION_ID", "")
        if os_id in ALLOWED_OS_IDS and _VERSION.fullmatch(version):
            return os_id, version
    return None


def _odbc_driver_entry(path: Path) -> tuple[str, str | None]:
    """Registration-only configuration parser; never return a path to stdout."""
    if os.environ.get("ODBCSYSINI") or os.environ.get("ODBCINSTINI"):
        return "CONFIG_OVERRIDE_UNVERIFIED", None
    try:
        raw = _read_bounded(path, MAX_ODBC_BYTES)
        cfg = configparser.ConfigParser(interpolation=None, strict=True)
        cfg.read_string(raw)
        driver = (cfg.get(_DRIVER_SECTION, "Driver", fallback="").strip()
                  if cfg.has_section(_DRIVER_SECTION) else "")
        return (("REGISTERED_CONFIG_ONLY", driver) if driver else
                ("NOT_REGISTERED_IN_DEFAULT_CONFIG", None))
    except (OSError, UnicodeError, ValueError, _UnsafeEvidence, configparser.Error):
        return "CONFIG_UNVERIFIABLE", None


def _odbc_elf_header(driver_path: str | None, arch: str,
                     *, driver_root: Path = ODBC_DRIVER_ROOT) -> str:
    """No-follow header-only ELF check, never dlopen/execute or output path.

    Restrict to supported MS ODBC18 vendor path; unusual layouts cannot
    silently earn evidence. Linux source file can still change after reading.
    """
    if arch not in ALLOWED_ARCH or not isinstance(driver_path, str):
        return "UNVERIFIED"
    # Only accept a direct child of the known versioned Microsoft directory.
    # No resolved() paths: resolving would follow symlinks before O_NOFOLLOW.
    name = driver_path.rsplit("/", 1)[-1]
    if (not _ODBC_LIBRARY_NAME.fullmatch(name)
            or driver_path != str(driver_root / name)
            or not driver_root.is_absolute()
            or ".." in driver_root.parts):
        return "DRIVER_PATH_UNSUPPORTED"
    basefd = -1
    fd = -1
    try:
        basefd = os.open("/", _flags(directory=True))
        fd = _open_beneath(basefd, driver_path.removeprefix("/"))
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode)
                or not 64 <= before.st_size <= MAX_ODBC_LIBRARY_BYTES):
            return "ELF_FILE_UNVERIFIABLE"
        header = os.pread(fd, 64, 0)
        after = os.fstat(fd)
        identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        if identity(before) != identity(after) or len(header) != 64:
            return "ELF_FILE_UNVERIFIABLE"
        if (header[:4] != b"\x7fELF" or header[4] != 2
                or header[5] != 1 or header[6] != 1
                or int.from_bytes(header[16:18], "little") != 3):
            return "ELF_HEADER_UNSUPPORTED"
        expected = {"x86_64": 62, "aarch64": 183}[arch]
        if int.from_bytes(header[18:20], "little") != expected:
            return "ELF_ARCH_MISMATCH"
        return "ELF64_ARCH_MATCH_HEADER_ONLY"
    except (OSError, _UnsafeEvidence, ValueError, TypeError):
        return "ELF_FILE_UNVERIFIABLE"
    finally:
        if fd >= 0:
            os.close(fd)
        if basefd >= 0:
            os.close(basefd)



def observe(*, os_paths: tuple[Path, ...] = OS_RELEASE_FILES,
            odbc_path: Path = ODBC_INST_FILE,
            driver_root: Path | None = None) -> dict[str, object]:
    """Fixed, sanitized and explicitly partial local target observations."""
    result: dict[str, object] = {
        "schema": SCHEMA, "status": "INCOMPLETE",
        "reason": "target_identity_unverifiable", "scope": SCOPE,
        "os_id": "UNVERIFIED", "os_version_id": "UNVERIFIED",
        "architecture": "UNVERIFIED", "python_version": "UNVERIFIED",
        "python_abi": "UNVERIFIED", "libc_family": "UNVERIFIED",
        "libc_version": "UNVERIFIED", "odbc18": "CONFIG_UNVERIFIABLE",
        "odbc_binary_header": "UNVERIFIED", "odbc_binary_load": "NOT_TESTED", "wheelhouse_compatibility": "NOT_TESTED",
        "full_live": "NOT_TESTED", "production_release_ready": False,
    }
    if platform.system() != "Linux":
        result["reason"] = "linux_target_required"
        return result

    release = _read_os_release(os_paths)
    if release:
        result["os_id"], result["os_version_id"] = release

    arch = platform.machine().lower()
    if arch in ALLOWED_ARCH:
        result["architecture"] = arch

    if sys.implementation.name == "cpython" and sys.version_info.major == 3:
        result["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}"
        abi = sysconfig.get_config_var("SOABI")
        if isinstance(abi, str) and _ABI.fullmatch(abi):
            result["python_abi"] = abi

    libc_family, libc_version = platform.libc_ver()
    if libc_family in {"glibc", "musl"} and _VERSION.fullmatch(libc_version):
        result["libc_family"] = libc_family
        result["libc_version"] = libc_version

    if driver_root is None:
        driver_root = ODBC_DRIVER_ROOT
    result["odbc18"], driver = _odbc_driver_entry(odbc_path)
    if result["odbc18"] == "REGISTERED_CONFIG_ONLY":
        result["odbc_binary_header"] = _odbc_elf_header(
            driver, result["architecture"], driver_root=driver_root)
    if all(result[k] != "UNVERIFIED" for k in (
            "os_id", "os_version_id", "architecture", "python_version",
            "python_abi", "libc_family", "libc_version")):
        if result["odbc18"] != "REGISTERED_CONFIG_ONLY":
            result["reason"] = "odbc18_registration_unverified"
        elif result["odbc_binary_header"] != "ELF64_ARCH_MATCH_HEADER_ONLY":
            result["reason"] = "odbc18_elf_header_unverified"
        else:
            result["status"] = "PASS_PARTIAL"
            result["reason"] = "linux_python_target_odbc_elf_header_observed"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = observe()
    except (OSError, ValueError, UnicodeError, RuntimeError, TypeError,
            configparser.Error):
        result = {
            "schema": SCHEMA, "status": "INCOMPLETE",
            "reason": "target_identity_unverifiable", "scope": SCOPE,
            "full_live": "NOT_TESTED", "production_release_ready": False,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0 if result["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
