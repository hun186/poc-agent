#!/usr/bin/env python3
"""OFF-2 pinned wheel-byte audit; PARTIAL ONLY, no installation or dependency resolution."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_manifest_check import _UnsafeEvidence, _fingerprint, _flags

MANIFEST = "SRAF_WHEELHOUSE_MANIFEST.json"
WHEEL_DIR = "wheelhouse"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_WHEELS = 256
MAX_WHEEL_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
SCOPE = "PINNED_WHEEL_BYTES_ONLY_NOT_DEPENDENCY_OR_AIRGAP_ATTESTATION"
_SHA = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.whl")


class _InvalidWheelInventory(Exception):
    """Never include raw filenames or untrusted manifest data in output."""


def _result(status: str, reason: str, checked: int = 0) -> dict[str, object]:
    return {"status": status, "reason": reason, "wheels_checked": checked}


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _InvalidWheelInventory
        value[key] = item
    return value


def _validate(raw: bytes) -> list[dict[str, object]]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeError, ValueError) as exc:
        raise _InvalidWheelInventory from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "repository", "wheels"
    } or type(value.get("schema_version")) is not int
            or value.get("schema_version") != 1 or value.get("repository") != "hun186/poc-agent":
        raise _InvalidWheelInventory
    entries = value["wheels"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_WHEELS:
        raise _InvalidWheelInventory
    seen = set()
    total = 0
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"filename", "sha256", "size"}:
            raise _InvalidWheelInventory
        filename, digest, size = item["filename"], item["sha256"], item["size"]
        if (not isinstance(filename, str) or not _NAME.fullmatch(filename)
                or ".." in filename or not isinstance(digest, str)
                or not _SHA.fullmatch(digest) or type(size) is not int
                or not 0 < size <= MAX_WHEEL_BYTES):
            raise _InvalidWheelInventory
        normalized = filename.casefold()
        if normalized in seen:
            raise _InvalidWheelInventory
        seen.add(normalized)
        total += size
        if total > MAX_TOTAL_BYTES:
            raise _InvalidWheelInventory
    return entries


def observe(root: Path, expected_manifest_sha256: str | None) -> dict[str, object]:
    """Require external out-of-band pin; hash listed bytes and reject extras."""
    if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
        return _result("INCOMPLETE", "trusted_wheel_inventory_digest_not_supplied")
    rootfd = -1
    wheelfd = -1
    checked = 0
    try:
        rootfd = os.open(root, _flags(directory=True))
        digest, _, raw = _fingerprint(rootfd, MANIFEST, MAX_MANIFEST_BYTES, contents=True)
        if digest != expected_manifest_sha256:
            return _result("FAIL", "wheel_inventory_digest_mismatch")
        assert raw is not None
        wheels = _validate(raw)
        wheelfd = os.open(WHEEL_DIR, _flags(directory=True), dir_fd=rootfd)
        listed = {str(item["filename"]) for item in wheels}
        actual = os.listdir(wheelfd)
        if len(actual) != len(listed) or set(actual) != listed:
            return _result("INCOMPLETE", "wheelhouse_content_incomplete")
        for item in wheels:
            wheel_digest, wheel_size, _ = _fingerprint(
                wheelfd, str(item["filename"]), MAX_WHEEL_BYTES)
            checked += 1
            if wheel_digest != item["sha256"] or wheel_size != item["size"]:
                return _result("FAIL", "wheel_file_mismatch", checked)
        return _result("PASS_PARTIAL", "pinned_wheel_bytes_match_only", checked)
    except (_InvalidWheelInventory, _UnsafeEvidence, OSError, ValueError, TypeError,
            UnicodeError, RecursionError, AssertionError):
        return _result("INCOMPLETE", "wheel_inventory_or_files_unverifiable", checked)
    finally:
        if wheelfd >= 0:
            os.close(wheelfd)
        if rootfd >= 0:
            os.close(rootfd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-manifest-sha256", default=None,
                        help="Externally trusted wheel inventory SHA-256, not a local computed digest")
    args = parser.parse_args(argv)
    result = observe(Path.cwd(), args.expected_manifest_sha256)
    print("SRAF_OFF2_WHEELS=" + str(result["status"])
          + " reason=" + str(result["reason"])
          + " wheels_checked=" + str(result["wheels_checked"])
          + " scope=" + SCOPE)
    return {"PASS_PARTIAL": 0, "FAIL": 1, "INCOMPLETE": 2}[str(result["status"])]


if __name__ == "__main__":
    raise SystemExit(main())
