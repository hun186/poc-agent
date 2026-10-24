"""OFF-1I: explicit operator-only SQL Server Handoff lease snapshot.

This proves at most a database-side lease row was active at one observation
point; it cannot prove that the *local* Worker owns or renews that lease.
No runtime SQL registry, data table enumeration, writes or SQL permissions
are implied. The caller must positively gate this behind OFF-1G SQL-READ.
"""
from __future__ import annotations

import re
from typing import Any

import pyodbc

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS,
    _connection_string,
)

SCHEMA_KEY = "SRAF_OFF1I_SQL_SCHEMA"
DEFAULT_SCHEMA = "sra_schedule"
_SCHEMA_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
# One fixed parameterized SQL SELECT. Never fetch owner_id, lease_token,
# control_domain, connection strings or datetime values to the report.
# Use the SQL Server authoritative UTC clock rather than the probe host.
_SQL_TEMPLATE = """
SELECT TOP (2)
  CASE WHEN LEN(owner_id) BETWEEN 1 AND 128
            AND LEN(lease_token)=64
            AND fencing_generation BETWEEN 1 AND 9223372036854775806
       THEN 1 ELSE 0 END AS identity_shape_ok,
  CASE WHEN expires_at > clock.now_utc THEN 1 ELSE 0 END AS unexpired,
  CASE WHEN heartbeat_at <= clock.now_utc
            AND DATEDIFF(SECOND,heartbeat_at,clock.now_utc) BETWEEN 0 AND 120
       THEN 1 ELSE 0 END AS recent_heartbeat
FROM [{schema}].[requirement_handoff_coordinator_leases]
CROSS JOIN (SELECT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00') AS now_utc) AS clock
WHERE control_domain=?
"""
_DOMAIN = "requirement-report-v1"


def _result(status: str, reason: str, *, executed: bool = False,
            active: bool = False) -> Observation:
    return Observation(
        "LEASE-01", "handoff-lease-snapshot",
        "handoff_db_lease_snapshot_only", status, reason, executed,
        {"active_lease_observed": active},
    )


def probe_handoff_lease_snapshot(cfg: dict[str, str],
                                 *, schema: str = DEFAULT_SCHEMA) -> Observation:
    """A single non-mutating DB SELECT; no owner/PID linkage or progress proof."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "lease_schema_invalid")
    connection_string = _connection_string(cfg)
    if connection_string is None:
        return _result("SKIP", "lease_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "lease_driver_unavailable")
    except Exception:
        return _result("SKIP", "lease_driver_unavailable")
    db = cursor = None
    try:
        db = pyodbc.connect(connection_string, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL_TEMPLATE.format(schema=schema), _DOMAIN)
        first = cursor.fetchone()
        second = cursor.fetchone()
        if second is not None:
            return _result("FAIL", "lease_row_ambiguous", executed=True)
        if first is None:
            return _result("SKIP", "lease_row_not_observed", executed=True)
        if len(first) != 3 or any(type(v) is not int or v not in (0, 1)
                                  for v in first):
            return _result("FAIL", "lease_result_invalid", executed=True)
        if tuple(first) != (1, 1, 1):
            return _result("SKIP", "lease_active_state_unverified",
                           executed=True)
        return _result("PASS", "lease_active_snapshot_observed",
                       executed=True, active=True)
    except Exception:
        # Native driver errors often contain credentials, host and SQL text.
        return _result("SKIP", "lease_sql_unverified", executed=db is not None)
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
