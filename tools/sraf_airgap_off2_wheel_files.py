#!/usr/bin/env python3
"""OFF-2 pinned wheel-byte audit; PARTIAL ONLY, no installation or dependency resolution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import zlib
import zipfile
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_manifest_check import (_UnsafeEvidence, _fingerprint, _flags, _open_beneath)

MANIFEST = "SRAF_WHEELHOUSE_MANIFEST.json"
WHEEL_DIR = "wheelhouse"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_WHEELS = 256
MAX_WHEEL_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_ZIP_MEMBERS = 8192
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 4 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
_HASH_CHUNK = 64 * 1024
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
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "repository", "wheels"}
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("repository") != "hun186/poc-agent"
    ):
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



class _WheelStructureInvalid(Exception):
    """Wheel archive not provably a structurally usable package (no raw detail)."""


def _package_key(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _header_fields(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise _WheelStructureInvalid from exc
    fields: dict[str, str] = {}
    previous_key: str | None = None
    for line in lines:
        if not line:
            break
        if line[:1].isspace():
            # RFC 822 style folded headers are normal in Wheel metadata,
            # notably License. Ignore unknown folded values, not the header.
            if previous_key is None:
                raise _WheelStructureInvalid
            if previous_key in fields:
                fields[previous_key] += " " + line.strip()
            continue
        key, separator, val = line.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z-]*", key):
            raise _WheelStructureInvalid
        key = key.casefold()
        previous_key = key
        if key in {"name", "version", "metadata-version", "wheel-version"}:
            if key in fields:
                raise _WheelStructureInvalid
            fields[key] = val.strip()
    return fields



def _preflight_zip_directory(fd: int) -> None:
    """Bound central-directory *bytes and records* before ZipFile allocates ZipInfo."""
    size = os.fstat(fd).st_size
    # Standard EOCD has a maximum 65,535-byte comment. Deliberately reject
    # ZIP64 and multi-disk features here (basic validation subset only).
    tail_size = min(size, 22 + 65535)
    tail = os.pread(fd, tail_size, size - tail_size)
    pos = tail.rfind(b"PK\x05\x06")
    while pos >= 0:
        if pos + 22 <= len(tail):
            try:
                (_, disk, directory_disk, on_disk, count, central_size,
                 central_offset, comment_size) = struct.unpack_from(
                    "<4s4H2LH", tail, pos)
            except struct.error as exc:
                raise _WheelStructureInvalid from exc
            if pos + 22 + comment_size == len(tail):
                break
        pos = tail.rfind(b"PK\x05\x06", 0, pos)
    if pos < 0:
        raise _WheelStructureInvalid
    eocd_start = size - tail_size + pos
    if (disk != 0 or directory_disk != 0 or on_disk != count
            or not 1 <= count <= MAX_ZIP_MEMBERS
            or central_size <= 0 or central_size > MAX_ZIP_CENTRAL_DIRECTORY_BYTES
            or central_offset + central_size != eocd_start
            or count == 0xFFFF or central_size == 0xFFFFFFFF
            or central_offset == 0xFFFFFFFF
            or (eocd_start >= 20
                and os.pread(fd, 4, eocd_start - 20) == b"PK\x06\x07")):
        raise _WheelStructureInvalid
    directory = os.pread(fd, central_size, central_offset)
    if len(directory) != central_size:
        raise _WheelStructureInvalid
    offset = 0
    records = 0
    while offset < len(directory):
        if (offset + 46 > len(directory)
                or directory[offset:offset + 4] != b"PK\x01\x02"):
            raise _WheelStructureInvalid
        filename_len, extra_len, comment_len = struct.unpack_from(
            "<HHH", directory, offset + 28)
        offset += 46 + filename_len + extra_len + comment_len
        records += 1
        if offset > len(directory) or records > MAX_ZIP_MEMBERS:
            raise _WheelStructureInvalid
    if offset != len(directory) or records != count:
        raise _WheelStructureInvalid


def _inspect_zip(fd: int, filename: str) -> None:
    # This is intentionally a conservative PEP 427 *structure* subset.
    # It does not parse/resolve Requires-Dist or execute/decompress payloads.
    parts = filename[:-4].split("-")
    if len(parts) not in (5, 6) or not parts[0] or not parts[1]:
        raise _WheelStructureInvalid
    distinfo = f"{parts[0]}-{parts[1]}.dist-info"
    metadata_name = f"{distinfo}/METADATA"
    wheel_name = f"{distinfo}/WHEEL"
    # ZipFile eagerly materializes every central-directory member. Never
    # reach it until the raw central directory is bounded and counted.
    _preflight_zip_directory(fd)
    with os.fdopen(os.dup(fd), "rb") as stream:
        stream.seek(0)
        with zipfile.ZipFile(stream, "r") as wheel:
            entries = wheel.infolist()
            if not 1 <= len(entries) <= MAX_ZIP_MEMBERS:
                raise _WheelStructureInvalid
            names: dict[str, zipfile.ZipInfo] = {}
            uncompressed = 0
            for info in entries:
                name = info.filename
                segments = name.rstrip("/").split("/")
                if (not name or "\\" in name or "\x00" in name
                        or name.startswith("/") or
                        any(x in {"", ".", ".."} for x in segments)
                        or (info.flag_bits & 1)
                        or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                        or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK):
                    raise _WheelStructureInvalid
                key = name.casefold()
                if key in names:
                    raise _WheelStructureInvalid
                names[key] = info
                uncompressed += info.file_size
                if uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise _WheelStructureInvalid
            if metadata_name.casefold() not in names or wheel_name.casefold() not in names:
                raise _WheelStructureInvalid
            for item in (metadata_name, wheel_name):
                info = names[item.casefold()]
                if info.file_size > MAX_METADATA_BYTES:
                    raise _WheelStructureInvalid
            try:
                with wheel.open(names[metadata_name.casefold()]) as stream:
                    metadata = stream.read(MAX_METADATA_BYTES + 1)
                with wheel.open(names[wheel_name.casefold()]) as stream:
                    wheel_metadata = stream.read(MAX_METADATA_BYTES + 1)
            except (OSError, RuntimeError, ValueError, EOFError) as exc:
                raise _WheelStructureInvalid from exc
            if len(metadata) > MAX_METADATA_BYTES or len(wheel_metadata) > MAX_METADATA_BYTES:
                raise _WheelStructureInvalid
            meta_fields = _header_fields(metadata)
            wheel_fields = _header_fields(wheel_metadata)
            if (not meta_fields.get("metadata-version")
                    or not re.fullmatch(r"[0-9]+\.[0-9]+", meta_fields["metadata-version"])
                    or _package_key(meta_fields.get("name", "")) != _package_key(parts[0])
                    or meta_fields.get("version") != parts[1]
                    or not wheel_fields.get("wheel-version", "").startswith("1.")):
                raise _WheelStructureInvalid


def _verify_one_wheel(wheel_dirfd: int, item: dict[str, object]) -> str:
    """Same no-follow FD for hashed file and conservative ZIP metadata read."""
    fd = _open_beneath(wheel_dirfd, str(item["filename"]))
    try:
        before = os.fstat(fd)
        if before.st_size > MAX_WHEEL_BYTES:
            raise _UnsafeEvidence
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, min(_HASH_CHUNK, MAX_WHEEL_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_WHEEL_BYTES:
                raise _UnsafeEvidence
            hasher.update(chunk)
        match = total == item["size"] and hasher.hexdigest() == item["sha256"]
        outcome = "PASS_PARTIAL" if match else "FAIL"
        if match:
            try:
                _inspect_zip(fd, str(item["filename"]))
            except (zipfile.BadZipFile, zipfile.LargeZipFile, _WheelStructureInvalid,
                    zlib.error, EOFError, OSError, ValueError, RuntimeError,
                    NotImplementedError):
                outcome = "INCOMPLETE"
        after = os.fstat(fd)
        identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        if identity(before) != identity(after):
            raise _UnsafeEvidence
        return outcome
    finally:
        os.close(fd)


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
            outcome = _verify_one_wheel(wheelfd, item)
            checked += 1
            if outcome == "FAIL":
                return _result("FAIL", "wheel_file_mismatch", checked)
            if outcome == "INCOMPLETE":
                return _result("INCOMPLETE", "wheel_archive_structure_invalid", checked)
        return _result("PASS_PARTIAL", "pinned_wheel_bytes_and_basic_metadata_only", checked)
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
