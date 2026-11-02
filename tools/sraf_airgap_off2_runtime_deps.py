#!/usr/bin/env python3
"""OFF-2: read-only, bounded direct distribution metadata snapshot.

No imports of target packages, pip, network, package execution, or output
of package names, paths or versions. Inspect only selected interpreter
install-scheme roots, no-follow each component and each selected METADATA.
Does not resolve versions/transitive dependencies or attest a Wheelhouse.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import sysconfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_manifest_check import (
    _UnsafeEvidence, _fingerprint, _flags,
)
from tools.sraf_airgap_off2_requirements_audit import (
    REQUIREMENTS, MAX_REQUIREMENTS_BYTES, MAX_REQUIREMENTS_LINES,
    _LITERAL_REQUIREMENT, _EXACT_VERSION,
)

SCHEMA = "sraf_off2_direct_runtime_inventory_v1"
SCOPE = "INSTALLED_DIRECT_METADATA_ONLY_NOT_VERSION_SOLVER_OR_WHEELHOUSE_ATTESTATION"
_MAX_DIRECT = 256
_MAX_DISTS_SCAN = 4096
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_METADATA_HEADER_LINES = 4096
_MAX_NAME_LEN = 128
_MAX_VERSION_LEN = 128
_CANON = re.compile(r"[-_.]+")
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?")
_DIST_DIR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,255}\.dist-info")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}")


class _InvalidInventory(Exception):
    """Fail closed without displaying untrusted metadata or paths."""


def _canonical(value: str) -> str:
    if not isinstance(value, str) or len(value) > _MAX_NAME_LEN or _NAME.fullmatch(value) is None:
        raise _InvalidInventory
    return _CANON.sub("-", value).lower()


def _declared(root: Path) -> dict[str, str | None]:
    fd = -1
    try:
        fd = os.open(root, _flags(directory=True))
        _, _, raw = _fingerprint(fd, REQUIREMENTS, MAX_REQUIREMENTS_BYTES, contents=True)
    finally:
        if fd >= 0:
            os.close(fd)
    if raw is None:
        raise _InvalidInventory
    content = raw.decode("utf-8")
    if ("\x00" in content or "\ufeff" in content or
            "\r" in content.replace("\r\n", "")):
        raise _InvalidInventory
    lines = content.splitlines()
    if len(lines) > MAX_REQUIREMENTS_LINES:
        raise _InvalidInventory
    found: dict[str, str | None] = {}
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        match = _LITERAL_REQUIREMENT.fullmatch(item)
        if match is None:
            raise _InvalidInventory
        name = _canonical(match["name"])
        if len(found) >= _MAX_DIRECT or name in found:
            raise _InvalidInventory
        version = match["version"]
        if len(version) > _MAX_VERSION_LEN:
            raise _InvalidInventory
        found[name] = (version if match["operator"] == "=="
                       and _EXACT_VERSION.fullmatch(version) else None)
    if not found:
        raise _InvalidInventory
    return found


def _locations() -> tuple[str, ...]:
    paths = sysconfig.get_paths()
    out: list[str] = []
    for category in ("purelib", "platlib"):
        path = paths.get(category)
        if (not isinstance(path, str) or not path.startswith("/")
                or "\x00" in path):
            raise _InvalidInventory
        if path not in out:
            out.append(path)
    if not out or len(out) > 2:
        raise _InvalidInventory
    return tuple(out)


def _open_directory_no_follow(path: str) -> int:
    """Walk an absolute install scheme path from / without following links."""
    if not path.startswith("/") or path == "/":
        raise _InvalidInventory
    parts = path.split("/")[1:]
    if not parts or any(not p or p in (".", "..") for p in parts):
        raise _InvalidInventory
    owner = os.open("/", _flags(directory=True))
    try:
        for part in parts:
            next_fd = os.open(part, _flags(directory=True), dir_fd=owner)
            os.close(owner)
            owner = next_fd
        fd = owner
        owner = -1
        return fd
    finally:
        if owner >= 0:
            os.close(owner)


def _read_metadata(directory_fd: int, relative: str) -> tuple[str, str]:
    """Read a selected on-disk METADATA under strict one-file size cap."""
    _, _, raw = _fingerprint(directory_fd, relative, _MAX_METADATA_BYTES, contents=True)
    if raw is None:
        raise _InvalidInventory
    text = raw.decode("utf-8")
    if "\x00" in text or "\r" in text.replace("\r\n", ""):
        raise _InvalidInventory
    header = text.replace("\r\n", "\n").split("\n\n", 1)[0].split("\n")
    if len(header) > _MAX_METADATA_HEADER_LINES:
        raise _InvalidInventory
    found: dict[str, str] = {}
    for item in header:
        if item.startswith((" ", "\t")):
            # Folded fields are not recognized, nor silently attached to Name.
            if "Name" in found or "Version" in found:
                raise _InvalidInventory
            continue
        key, separator, value = item.partition(":")
        if separator != ":":
            raise _InvalidInventory
        if key in ("Metadata-Version", "Name", "Version"):
            if key in found:
                raise _InvalidInventory
            found[key] = value.strip()
    if set(found) != {"Metadata-Version", "Name", "Version"}:
        raise _InvalidInventory
    if re.fullmatch(r"[1-4]\.[0-9]", found["Metadata-Version"]) is None:
        raise _InvalidInventory
    name = _canonical(found["Name"])
    version = found["Version"]
    if len(version) > _MAX_VERSION_LEN or _VERSION.fullmatch(version) is None:
        raise _InvalidInventory
    return name, version


def _metadata_snapshot(targets: set[str], locations: tuple[str, ...]) -> dict[str, str]:
    """Only read bounded metadata of dir-name-matched direct dependencies."""
    seen: dict[str, str] = {}
    scanned = 0
    for location in locations:
        fd = _open_directory_no_follow(location)
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > _MAX_DISTS_SCAN:
                        raise _InvalidInventory
                    base = entry.name
                    if _DIST_DIR.fullmatch(base) is None:
                        continue
                    stem = base[:-len(".dist-info")]
                    if "-" not in stem:
                        continue
                    package, _, filename_version = stem.rpartition("-")
                    try:
                        name = _canonical(package)
                    except _InvalidInventory:
                        continue
                    if name not in targets:
                        continue
                    if not _VERSION.fullmatch(filename_version) or name in seen:
                        raise _InvalidInventory
                    # Refuse even a symlinked .dist-info directory or METADATA.
                    # Other (unrelated) dist-info metadata is NEVER read.
                    actual, version = _read_metadata(fd, base + "/METADATA")
                    if actual != name or version != filename_version:
                        raise _InvalidInventory
                    seen[name] = version
        finally:
            os.close(fd)
    return seen


def _result(status: str, reason: str, declared: int = 0, present: int = 0,
            unlocked: int = 0, exact_matches: int = 0) -> dict[str, object]:
    return {
        "schema": SCHEMA, "scope": SCOPE, "status": status, "reason": reason,
        "requirements_checked": declared, "installed_direct_count": present,
        "missing_direct_count": max(0, declared - present),
        "unlocked_direct_count": unlocked, "exact_text_matches": exact_matches,
        "transitive_closure": "NOT_TESTED", "wheelhouse_compatibility": "NOT_TESTED",
        "package_imports": "NOT_TESTED", "production_release_ready": False,
    }


def observe(root: Path, *, locations: tuple[str, ...] | None = None) -> dict[str, object]:
    try:
        wanted = _declared(root)
    except (OSError, _UnsafeEvidence, UnicodeError, _InvalidInventory,
            TypeError, ValueError, RecursionError):
        return _result("INCOMPLETE", "requirements_input_unverifiable")
    count = len(wanted)
    unlocked = sum(x is None for x in wanted.values())
    try:
        if locations is None:
            locations = _locations()
        installed = _metadata_snapshot(set(wanted), locations)
        present = len(installed)
        matches = sum(v is not None and installed.get(k) == v for k, v in wanted.items())
        if present != count:
            return _result("INCOMPLETE", "direct_distribution_metadata_missing",
                           count, present, unlocked, matches)
        if matches != count - unlocked:
            return _result("INCOMPLETE", "exact_direct_version_text_mismatch",
                           count, present, unlocked, matches)
        return _result("PASS_PARTIAL", "direct_distribution_metadata_observed_only",
                       count, present, unlocked, matches)
    except (OSError, _UnsafeEvidence, UnicodeError, _InvalidInventory,
            TypeError, ValueError, RuntimeError, RecursionError):
        return _result("INCOMPLETE", "installed_distribution_metadata_unverifiable",
                       count, 0, unlocked)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    value = observe(Path.cwd())
    print(json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True))
    return 0 if value["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
