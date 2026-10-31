#!/usr/bin/env python3
"""OFF-2 listed runtime-file integrity check (partial, not release attestation).

Requires an independently obtained digest of the reviewed provenance manifest.
Does not package, sign, trust an unpinned local manifest, discover all required
files, read deployment-local registries, connect to services, or modify files.
All output is a closed enum and counts: no paths, digests, native errors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.runtime_provenance import validate_provenance

MANIFEST = "REQUIREMENT_E2E_PROVENANCE.json"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
SCOPE = "LISTED_FILES_ONLY_NOT_RELEASE_OR_AIRGAP_ATTESTATION"


class _UnsafeEvidence(Exception):
    """Do not serialize underlying operating-system errors."""


def _flags(*, directory: bool = False) -> int:
    value = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    value |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if directory:
        value |= getattr(os, "O_DIRECTORY", 0)
    return value


def _open_beneath(root_fd: int, relative: str) -> int:
    """Open a regular file through no-follow dirfds, never through a symlink."""
    parts = relative.split("/")
    if not parts or any(x in ("", ".", "..") for x in parts):
        raise _UnsafeEvidence
    owner = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, _flags(directory=True), dir_fd=owner)
            os.close(owner)
            owner = child
        fd = os.open(parts[-1], _flags(), dir_fd=owner)
    finally:
        os.close(owner)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise _UnsafeEvidence
    return fd


def _fingerprint(root_fd: int, relative: str, limit: int,
                 *, contents: bool = False) -> tuple[str, int, bytes | None]:
    fd = _open_beneath(root_fd, relative)
    try:
        before = os.fstat(fd)
        if before.st_size > limit:
            raise _UnsafeEvidence
        hasher = hashlib.sha256()
        out: list[bytes] | None = [] if contents else None
        total = 0
        while True:
            piece = os.read(fd, min(CHUNK_BYTES, limit + 1 - total))
            if not piece:
                break
            total += len(piece)
            if total > limit:
                raise _UnsafeEvidence
            hasher.update(piece)
            if out is not None:
                out.append(piece)
        after = os.fstat(fd)
        # Snapshot evidence is not atomic, but cannot silently accept ordinary
        # replacement/append during hashing.
        if (before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size,
                after.st_mtime_ns, after.st_ctime_ns):
            raise _UnsafeEvidence
        return hasher.hexdigest(), total, b"".join(out) if out is not None else None
    finally:
        os.close(fd)


def observe(root: Path, expected_manifest_sha256: str | None) -> dict[str, object]:
    """Check *listed* bytes only, never claim completeness or signing."""
    if (not isinstance(expected_manifest_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None):
        return {"status": "INCOMPLETE", "reason": "trusted_manifest_digest_not_supplied",
                "files_checked": 0}
    fd = -1
    checked = 0
    try:
        fd = os.open(root, _flags(directory=True))
        manifest_sha, _, manifest_bytes = _fingerprint(
            fd, MANIFEST, MAX_MANIFEST_BYTES, contents=True)
        if manifest_sha != expected_manifest_sha256:
            return {"status": "FAIL", "reason": "manifest_digest_mismatch",
                    "files_checked": 0}
        assert manifest_bytes is not None
        provenance = validate_provenance(json.loads(manifest_bytes.decode("utf-8")))
        total = 0
        for item in provenance["runtime_files"]:
            item_sha, n, _ = _fingerprint(fd, item["path"], MAX_FILE_BYTES)
            total += n
            if total > MAX_TOTAL_BYTES:
                raise _UnsafeEvidence
            if item_sha != item["sha256"]:
                return {"status": "FAIL", "reason": "listed_runtime_file_mismatch",
                        "files_checked": checked + 1}
            checked += 1
        return {"status": "PASS_PARTIAL", "reason": "listed_runtime_bytes_match_only",
                "files_checked": checked}
    except (OSError, _UnsafeEvidence, ValueError, UnicodeError, TypeError,
            RecursionError):
        return {"status": "INCOMPLETE", "reason": "manifest_or_file_unverifiable",
                "files_checked": checked}
    finally:
        if fd >= 0:
            os.close(fd)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--expected-manifest-sha256", default=None,
                   help="Trusted SHA-256 of the manifest, obtained out of band")
    args = p.parse_args(argv)
    # Never echo a digest or any path. Only use the current working directory.
    result = observe(Path.cwd(), args.expected_manifest_sha256)
    print("SRAF_OFF2_PROVENANCE=" + str(result["status"])
          + " reason=" + str(result["reason"])
          + " files_checked=" + str(result["files_checked"])
          + " scope=" + SCOPE)
    return {"PASS_PARTIAL": 0, "FAIL": 1, "INCOMPLETE": 2}[str(result["status"])]


if __name__ == "__main__":
    raise SystemExit(main())
