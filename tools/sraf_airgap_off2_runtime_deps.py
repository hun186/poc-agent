#!/usr/bin/env python3
"""OFF-2: passive installed direct Python distribution metadata observation.

This is deliberately not a version solver, module importer, wheel validator,
package manager or transitive dependency closure check. Only the selected
Python install scheme's purelib/platlib directories are inspected with
importlib.metadata. Output contains no package names, versions or paths.
"""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import sys
import sysconfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_manifest_check import _UnsafeEvidence, _fingerprint, _flags
from tools.sraf_airgap_off2_requirements_audit import (
    REQUIREMENTS, MAX_REQUIREMENTS_BYTES, MAX_REQUIREMENTS_LINES, _LITERAL_REQUIREMENT,
    _EXACT_VERSION,
)

SCHEMA = "sraf_off2_direct_runtime_inventory_v1"
SCOPE = "INSTALLED_DIRECT_METADATA_ONLY_NOT_VERSION_SOLVER_OR_WHEELHOUSE_ATTESTATION"
_MAX_DIRECT = 256
_MAX_DISTS_SCAN = 4096
_MAX_NAME_LEN = 128
_MAX_VERSION_LEN = 128
_CANON = re.compile(r"[-_.]+")
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?")


class _InvalidInventory(Exception):
    """Never include raw metadata or paths in output."""


def _canonical(value: str) -> str:
    if not isinstance(value, str) or len(value) > _MAX_NAME_LEN or _NAME.fullmatch(value) is None:
        raise _InvalidInventory
    return _CANON.sub("-", value).lower()


def _declared(root: Path) -> dict[str, str | None]:
    """Reuse existing strict direct requirement literal subset and no-follow FD."""
    fd = -1
    try:
        fd = os.open(root, _flags(directory=True))
        _, _, data = _fingerprint(fd, REQUIREMENTS, MAX_REQUIREMENTS_BYTES, contents=True)
    finally:
        if fd >= 0:
            os.close(fd)
    if data is None:
        raise _InvalidInventory
    source = data.decode("utf-8")
    if ("\x00" in source or "\ufeff" in source or
            "\r" in source.replace("\r\n", "")):
        raise _InvalidInventory
    lines = source.splitlines()
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
        exact = (match["version"] if match["operator"] == "=="
                 and _EXACT_VERSION.fullmatch(match["version"]) else None)
        # Even exact textual equality is not a complete PEP 440/508 resolver.
        if len(match["version"]) > _MAX_VERSION_LEN:
            raise _InvalidInventory
        found[name] = exact
    if not found:
        raise _InvalidInventory
    return found


def _locations() -> tuple[str, ...]:
    """Inspect only the selected interpreter's install-scheme directories."""
    paths = sysconfig.get_paths()
    dirs = []
    for kind in ("purelib", "platlib"):
        path = paths.get(kind)
        if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
            raise _InvalidInventory
        if path not in dirs:
            dirs.append(path)
    if not dirs or len(dirs) > 2:
        raise _InvalidInventory
    return tuple(dirs)


def _metadata_snapshot(targets: set[str],
                       locations: tuple[str, ...]) -> dict[str, str]:
    """Read metadata only, never import target modules or execute entrypoints."""
    versions: dict[str, str] = {}
    count = 0
    for dist in metadata.distributions(path=list(locations)):
        count += 1
        if count > _MAX_DISTS_SCAN:
            raise _InvalidInventory
        try:
            raw_name = dist.metadata.get("Name")
            if not isinstance(raw_name, str):
                continue
            name = _canonical(raw_name)
        except (TypeError, ValueError, _InvalidInventory, UnicodeError):
            # Unknown irrelevant dist metadata cannot prove a target package.
            continue
        if name not in targets:
            continue
        version = dist.version
        if (not isinstance(version, str) or not 1 <= len(version) <= _MAX_VERSION_LEN
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)):
            raise _InvalidInventory
        if name in versions:
            # More than one same-name installation makes runtime selection
            # ambiguous; even matching versions are NOT accepted.
            raise _InvalidInventory
        versions[name] = version
    return versions


def _result(status: str, reason: str, declared: int = 0, present: int = 0,
            unpinned: int = 0, exact_matches: int = 0) -> dict[str, object]:
    return {
        "schema": SCHEMA, "scope": SCOPE, "status": status,
        "reason": reason, "requirements_checked": declared,
        "installed_direct_count": present,
        "missing_direct_count": max(0, declared - present),
        "unlocked_direct_count": unpinned,
        "exact_text_matches": exact_matches,
        "transitive_closure": "NOT_TESTED",
        "wheelhouse_compatibility": "NOT_TESTED",
        "package_imports": "NOT_TESTED",
        "production_release_ready": False,
    }


def observe(root: Path, *, locations: tuple[str, ...] | None = None) -> dict[str, object]:
    """Best-effort metadata presence only; require operator-selected Python."""
    try:
        declared = _declared(root)
    except (OSError, _UnsafeEvidence, UnicodeError, _InvalidInventory,
            TypeError, ValueError, RecursionError, AssertionError):
        return _result("INCOMPLETE", "requirements_input_unverifiable")
    count = len(declared)
    unlocked = sum(value is None for value in declared.values())
    try:
        if locations is None:
            locations = _locations()
        installed = _metadata_snapshot(set(declared), locations)
        matched = sum(
            v is not None and installed.get(k) == v
            for k, v in declared.items()
        )
        present = len(installed)
        if present != count:
            return _result("INCOMPLETE", "direct_distribution_metadata_missing",
                           count, present, unlocked, matched)
        if matched != count - unlocked:
            return _result("INCOMPLETE", "exact_direct_version_text_mismatch",
                           count, present, unlocked, matched)
        return _result("PASS_PARTIAL", "direct_distribution_metadata_observed_only",
                       count, present, unlocked, matched)
    except (OSError, UnicodeError, ValueError, TypeError, RuntimeError,
            RecursionError, _InvalidInventory):
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
