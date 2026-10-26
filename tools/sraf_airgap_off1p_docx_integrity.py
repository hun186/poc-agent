"""OFF-1P: operator-opted local DOCX byte integrity vs persisted SQL digest.

Read-only: one strict ODBC SQL row selects a single already-completed item's
path, root fingerprint and digest, then Linux fd-relative O_NOFOLLOW reads the
published DOCX. Does not call the remote Report Job or claim full E2E.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile
import zlib

import pyodbc

from requirement_scheduler.artifacts import output_root_fingerprint
from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1l_schedule_claim import _SCHEDULE_ID_RE

ARTIFACT_ROOT_KEY = "SRAF_OFF1P_ARTIFACT_ROOT"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ITEM_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")
MAX_DOCX_BYTES = 16 * 1024 * 1024
MAX_ZIP_MEMBERS = 1000
MAX_ZIP_UNCOMPRESSED = 64 * 1024 * 1024

# The SQL query intentionally returns sensitive artifact references ONLY to
# this in-process probe, never through Observation or operator JSON.
_SQL = """
SELECT TOP (2)
    i.run_item_id, i.artifact_relative_path, i.artifact_sha256,
    r.phase1a_output_root_fingerprint
FROM [{schema}].[requirement_schedules] AS s
OUTER APPLY (
    SELECT TOP (1) r.batch_run_id, r.phase1a_output_root_fingerprint
    FROM [{schema}].[requirement_batch_runs] AS r
    WHERE r.schedule_id=s.schedule_id
      AND r.trigger_type=N'scheduled'
      AND r.created_by=N'requirement-schedule-worker'
    ORDER BY r.scheduled_for DESC, r.batch_run_id DESC
) AS r
OUTER APPLY (
    SELECT TOP (1) i.run_item_id, i.artifact_relative_path, i.artifact_sha256
    FROM [{schema}].[requirement_batch_run_items] AS i
    INNER JOIN [{schema}].[requirement_handoff_submissions] AS h
        ON h.run_item_id=i.run_item_id
    WHERE i.batch_run_id=r.batch_run_id
      AND i.selection_status=N'selected'
      AND h.workflow_id=N'report_v1'
      AND i.remote_job_state=N'completed'
      AND i.execution_state=N'completed'
      AND i.remote_completed_at IS NOT NULL
      AND i.completed_at IS NOT NULL
      AND i.artifact_reconciled_at IS NOT NULL
    ORDER BY i.completed_at DESC, i.run_item_id DESC
) AS i
WHERE s.schedule_id=?
"""


def _result(status: str, reason: str, *, executed: bool = False,
            confirmed: bool = False) -> Observation:
    return Observation("DOCX-BYTES-01", "docx-byte-integrity",
                       "one_persisted_item_local_docx_byte_match_only",
                       status, reason, executed,
                       {"local_docx_byte_match": confirmed})


def _read_reference(connstr: str, schema: str, schedule_id: str):
    db = cursor = None
    try:
        db = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cursor.fetchone(), cursor.fetchone()
        if second is not None:
            return "docx_reference_ambiguous"
        if first is None:
            return "docx_reference_absent"
        if len(first) != 4 or any(type(v) is not str for v in first):
            return "docx_reference_invalid"
        return tuple(first)
    except Exception:
        return "docx_reference_sql_unverified"
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _docx_bytes_are_valid(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as pkg:
            infos = pkg.infolist()
            if not 2 <= len(infos) <= MAX_ZIP_MEMBERS:
                return False
            seen = set()
            total = 0
            for entry in infos:
                name = entry.filename
                parts = PurePosixPath(name).parts
                if (name in seen or not name or name.startswith("/")
                        or "\\" in name or "." in parts or ".." in parts
                        or entry.file_size > MAX_ZIP_UNCOMPRESSED):
                    return False
                if stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK:
                    return False
                total += entry.file_size
                if total > MAX_ZIP_UNCOMPRESSED:
                    return False
                seen.add(name)
            if not {"[Content_Types].xml", "word/document.xml"} <= seen:
                return False
            if pkg.getinfo("word/document.xml").file_size == 0:
                return False
            return pkg.testzip() is None
    except (OSError, ValueError, RuntimeError, zlib.error, EOFError,
            zipfile.BadZipFile, zipfile.LargeZipFile):
        return False


def _pin_root_directory(root: Path) -> int:
    """Pin every ancestor with openat(O_NOFOLLOW) before touching SQL."""
    parts = root.parts
    if (not root.is_absolute() or len(parts) < 2
            or any(part in ("", ".", "..") for part in parts[1:])):
        raise ValueError("root_path_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise ValueError("root_not_directory")
        return fd
    except Exception:
        os.close(fd)
        raise


def _inspect_local_docx(root_fd: int, relative: str, digest: str) -> str:
    parent_fd = file_fd = None
    try:
        parts = PurePosixPath(relative).parts
        if (len(parts) != 2
                or any(part in ("", ".", "..") for part in parts)
                or "\\" in relative or "\x00" in relative
                or len(relative.encode("utf-8")) > 320
                or len(parts[1].encode("utf-8")) > 240
                or not parts[1].lower().endswith(".docx")):
            return "docx_path_invalid"
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent_fd = os.open(parts[0], flags | os.O_DIRECTORY, dir_fd=root_fd)
        file_fd = os.open(parts[1], flags | os.O_NONBLOCK, dir_fd=parent_fd)
        before = os.fstat(file_fd)
        if (not stat.S_ISREG(before.st_mode)
                or not 0 < before.st_size <= MAX_DOCX_BYTES):
            return "docx_file_unverified"
        chunks = []
        remaining = MAX_DOCX_BYTES + 1
        while remaining:
            value = os.read(file_fd, min(65536, remaining))
            if not value:
                break
            chunks.append(value)
            remaining -= len(value)
        after = os.fstat(file_fd)
        data = b"".join(chunks)
        if (not 0 < len(data) <= MAX_DOCX_BYTES
                or len(data) != before.st_size
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            return "docx_file_unverified"
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), digest):
            return "docx_digest_mismatch"
        if not _docx_bytes_are_valid(data):
            return "docx_structure_invalid"
        return "docx_local_bytes_match"
    except (OSError, ValueError, UnicodeError):
        return "docx_file_unverified"
    finally:
        for fd in (file_fd, parent_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def probe_docx_byte_integrity(cfg: dict[str, str], *,
                              schedule_id: str, artifact_root: str,
                              schema: str = DEFAULT_SCHEMA) -> Observation:
    """One SQL selection plus fd-bound local DOCX verification (no writes)."""
    if sys.platform != "linux" or not hasattr(os, "O_NOFOLLOW"):
        return _result("SKIP", "docx_host_unsupported")
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "docx_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _result("SKIP", "docx_schedule_id_invalid")
    if (not isinstance(artifact_root, str)
            or not artifact_root.startswith("/")
            or "\x00" in artifact_root
            or len(artifact_root.encode("utf-8")) > 1024):
        return _result("SKIP", "docx_root_invalid")
    # No root or file opened until selection/SQL input checks are valid.
    connstr = _connection_string(cfg)
    if connstr is None:
        return _result("SKIP", "docx_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "docx_driver_unavailable")
    except Exception:
        return _result("SKIP", "docx_driver_unavailable")
    # Root descriptor is acquired BEFORE network SQL can yield/release the GIL.
    # Its ancestors cannot be followed via symlinks or silently redirected
    # during the SQL round trip. Never reopen the absolute root afterwards.
    root_fd = None
    try:
        root = Path(artifact_root)
        if ("." in artifact_root.split("/") or ".." in artifact_root.split("/")):
            return _result("SKIP", "docx_root_invalid")
        root_fd = _pin_root_directory(root)
        root_fp = output_root_fingerprint(root)
    except (OSError, ValueError):
        if root_fd is not None:
            os.close(root_fd)
        return _result("SKIP", "docx_root_invalid")
    try:
        row = _read_reference(connstr, schema, schedule_id)
        if isinstance(row, str):
            return _result("SKIP", row, executed=True)
        item_id, relative, expected, persisted_root_fp = row
        if (not _SAFE_ITEM_RE.fullmatch(item_id)
                or not _DIGEST_RE.fullmatch(expected)
                or not _DIGEST_RE.fullmatch(persisted_root_fp)):
            return _result("SKIP", "docx_reference_invalid", executed=True)
        parts = relative.split("/")
        if len(parts) != 2 or parts[0] != item_id[:64]:
            return _result("SKIP", "docx_path_invalid", executed=True)
        if not hmac.compare_digest(root_fp, persisted_root_fp):
            return _result("SKIP", "docx_root_mismatch", executed=True)
        result = _inspect_local_docx(root_fd, relative, expected)
        if result == "docx_local_bytes_match":
            return _result("PASS", result, executed=True, confirmed=True)
        if result in ("docx_digest_mismatch", "docx_structure_invalid"):
            return _result("FAIL", result, executed=True)
        return _result("SKIP", result, executed=True)
    finally:
        os.close(root_fd)
