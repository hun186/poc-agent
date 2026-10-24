"""OFF-1K: operator-only local Handoff PID -> SQL lease owner predicate.

Read-only. Deliberately refuses owners obtained from late dotenv/bootstrap,
guesswork about default handoff-<pid>, or user-supplied expected-owner strings.
An exact SQL owner match is a point-in-time correlation, not job progress.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

import pyodbc

from operator_e2e.requirement_e2e_support import verify_worker_identity
from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import (
    DEFAULT_SCHEMA, _DOMAIN, _SCHEMA_RE,
)

IDENTITY_FILE = ".run_sra_api_handoff.identity"
ENV_MAX_BYTES = 65536
_OWNER_KEY = b"REQUIREMENT_HANDOFF_OWNER_ID="
_OWNER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
# Compare exact NVARCHAR UTF-16 bytes rather than relying on case-insensitive
# SQL Server collations, which can also ignore trailing spaces.
_SQL = """
SELECT TOP (2)
  CASE WHEN CONVERT(varbinary(256), owner_id) =
                 CONVERT(varbinary(256), CAST(? AS nvarchar(128)))
       THEN 1 ELSE 0 END,
  CASE WHEN expires_at > clock.now_utc THEN 1 ELSE 0 END,
  CASE WHEN heartbeat_at <= clock.now_utc
            AND DATEDIFF(SECOND,heartbeat_at,clock.now_utc) BETWEEN 0 AND 120
       THEN 1 ELSE 0 END
FROM [{schema}].[requirement_handoff_coordinator_leases]
CROSS JOIN (SELECT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00') AS now_utc) AS clock
WHERE control_domain=?
"""


def _result(status: str, reason: str, *, executed: bool = False,
            associated: bool = False) -> Observation:
    return Observation(
        "LEASE-03", "handoff-local-owner",
        "local_inherited_owner_matches_db_lease_only",
        status, reason, executed, {"local_owner_match_observed": associated},
    )


def _initial_owner_from_proc(pid: int) -> str | None:
    """Bounded procfs birth-environment read; never report other env entries.

    /proc/PID/environ reflects the initial exec environment rather than
    variables added by bootstrap_env() after exec. Missing explicit birth
    owner is NOT authority to assume the usual handoff-PID default, since
    a late dotenv value could override that default.
    """
    if type(pid) is not int or not 2 <= pid <= 4_194_304:
        return None
    fd = os.open(
        f"/proc/{pid}/environ",
        os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW,
    )
    try:
        data = os.read(fd, ENV_MAX_BYTES + 1)
        # Verify EOF, not merely a single short read of a mutable proc file.
        tail = os.read(fd, 1)
    finally:
        os.close(fd)
    if not data or len(data) > ENV_MAX_BYTES or tail or not data.endswith(b"\0"):
        return None
    values = [v[len(_OWNER_KEY):] for v in data[:-1].split(b"\0")
              if v.startswith(_OWNER_KEY)]
    if len(values) != 1:
        return None
    try:
        owner = values[0].decode("ascii")
    except UnicodeError:
        return None
    return owner if _OWNER_PATTERN.fullmatch(owner) else None


def _trusted_local_owner(root: Path) -> tuple[int, str, str] | None:
    if sys.platform != "linux" or not isinstance(root, Path):
        return None
    if not root.is_dir() or root.is_symlink():
        return None
    real_root = root.resolve(strict=True)
    record = real_root / IDENTITY_FILE
    # The canonical verifier uses the same opened inode, checks effective
    # UID, PID reuse start-tick, expected cwd and exact role-specific argv.
    verified = verify_worker_identity(record, "handoff", real_root)
    if (not isinstance(verified, dict)
            or verified.get("role") != "handoff"
            or verified.get("alive") is not True
            or type(verified.get("pid")) is not int
            or not 2 <= verified["pid"] <= 4_194_304):
        return None
    tick = verified.get("process_start_time")
    if not isinstance(tick, str) or not tick.isdecimal() or len(tick) > 24:
        return None
    owner = _initial_owner_from_proc(verified["pid"])
    if owner is None:
        return None
    return verified["pid"], tick, owner


def _same_local_owner(root: Path, prior: tuple[int, str, str]) -> bool:
    latest = _trusted_local_owner(root)
    return latest is not None and latest == prior


def probe_handoff_local_owner(
    cfg: dict[str, str], *, project_root: Path,
    schema: str = DEFAULT_SCHEMA,
) -> Observation:
    """Validate same local process identity around one fixed SQL SELECT."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "owner_schema_invalid")
    connstr = _connection_string(cfg)
    if connstr is None:
        return _result("SKIP", "owner_sql_config_invalid")
    try:
        local = _trusted_local_owner(project_root)
    except Exception:
        return _result("SKIP", "owner_local_identity_unverified")
    if local is None:
        return _result("SKIP", "owner_local_identity_unverified")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "owner_driver_unavailable")
    except Exception:
        return _result("SKIP", "owner_driver_unavailable")
    db = cursor = None
    try:
        db = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL.format(schema=schema), local[2], _DOMAIN)
        first = cursor.fetchone()
        second = cursor.fetchone()
        if second is not None:
            outcome = "owner_rows_ambiguous"
        elif first is None:
            outcome = "owner_row_unavailable"
        elif (len(first) != 3
              or any(type(v) is not int or v not in (0, 1) for v in first)):
            outcome = "owner_result_invalid"
        elif tuple(first) != (1, 1, 1):
            outcome = "owner_binding_unverified"
        else:
            outcome = "owner_local_sql_match_observed"
    except Exception:
        outcome = "owner_sql_unverified"
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
    try:
        if not _same_local_owner(project_root, local):
            return _result("SKIP", "owner_local_identity_changed",
                           executed=True)
    except Exception:
        return _result("SKIP", "owner_local_identity_changed", executed=True)
    if outcome != "owner_local_sql_match_observed":
        return _result("SKIP", outcome, executed=True)
    return _result("PASS", outcome, executed=True, associated=True)
