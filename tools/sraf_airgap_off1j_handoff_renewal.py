"""OFF-1J: operator-initiated, two-sample Handoff SQL heartbeat observation.

Only a bounded DB-side lease renewal is measured. Neither local PID ownership
nor useful Handoff/Report Job work is attested. Defaults never contact SQL.
"""
from __future__ import annotations

import time

import pyodbc

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import (
    DEFAULT_SCHEMA, _DOMAIN, _SCHEMA_RE,
)

SAMPLE_INTERVAL_SECONDS = 15
# ISO datetimeoffset is converted to SQL bigint rather than fetched as driver-
# dependent datetimeoffset (-155). The numeric values never leave this module.
# The SQL clock checks expiration/recency independently in BOTH samples.
_SQL = """
SELECT TOP (2)
  CASE WHEN LEN(owner_id) BETWEEN 1 AND 128
            AND LEN(lease_token)=64
            AND fencing_generation BETWEEN 1 AND 9223372036854775806
       THEN 1 ELSE 0 END,
  CASE WHEN expires_at > clock.now_utc THEN 1 ELSE 0 END,
  CASE WHEN heartbeat_at <= clock.now_utc
            AND DATEDIFF(SECOND,heartbeat_at,clock.now_utc) BETWEEN 0 AND 120
       THEN 1 ELSE 0 END,
  fencing_generation,
  DATEDIFF_BIG(MILLISECOND,
      CONVERT(datetimeoffset, '1970-01-01T00:00:00+00:00'), heartbeat_at)
FROM [{schema}].[requirement_handoff_coordinator_leases]
CROSS JOIN (SELECT TODATETIMEOFFSET(SYSUTCDATETIME(), '+00:00') AS now_utc) AS clock
WHERE control_domain=?
"""


def _result(status: str, reason: str, *, executed: bool = False,
            renewed: bool = False) -> Observation:
    return Observation(
        "LEASE-02", "handoff-lease-renewal",
        "two_sample_db_heartbeat_advance_only",
        status, reason, executed, {"renewal_observed": renewed},
    )


def _read_once(connection_string: str, schema: str) -> tuple[int, int] | str:
    """Fetch bounded predicate-only evidence; never return owner/token/SQL."""
    conn = cursor = None
    try:
        conn = pyodbc.connect(connection_string, timeout=LOGIN_TIMEOUT_SECONDS,
                              autocommit=True)
        conn.timeout = QUERY_TIMEOUT_SECONDS
        cursor = conn.cursor()
        cursor.execute(_SQL.format(schema=schema), _DOMAIN)
        first = cursor.fetchone()
        second = cursor.fetchone()
        if second is not None:
            return "lease_renewal_rows_ambiguous"
        if first is None:
            return "lease_renewal_row_unavailable"
        if (len(first) != 5
                or any(type(x) is not int for x in first)
                or any(x not in (0, 1) for x in first[:3])
                or not 1 <= first[3] <= 9223372036854775806
                or not 1 <= first[4] <= 10**15):
            return "lease_renewal_result_invalid"
        if tuple(first[:3]) != (1, 1, 1):
            return "lease_renewal_snapshot_inactive"
        return first[3], first[4]
    except Exception:
        # No host, database, username, password, native ODBC diagnostics,
        # owner/token, generation or SQL-derived timestamps go to the report.
        return "lease_renewal_sql_unverified"
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def probe_handoff_lease_renewal(cfg: dict[str, str], *,
                                schema: str = DEFAULT_SCHEMA) -> Observation:
    """Take exactly two independent DB snapshots with a fixed 15s gap."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "lease_renewal_schema_invalid")
    connection_string = _connection_string(cfg)
    if connection_string is None:
        return _result("SKIP", "lease_renewal_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "lease_renewal_driver_unavailable")
    except Exception:
        return _result("SKIP", "lease_renewal_driver_unavailable")

    first = _read_once(connection_string, schema)
    if isinstance(first, str):
        return _result("SKIP", first, executed=True)
    try:
        # This 15-second blocking wait is an operator-authorized EXTRA probe.
        # The first SQL connection is already closed before waiting. Never
        # sleep/retry on default, implicit opt-ins or failed dependencies.
        time.sleep(SAMPLE_INTERVAL_SECONDS)
    except Exception:
        return _result("SKIP", "lease_renewal_wait_interrupted",
                       executed=True)
    second = _read_once(connection_string, schema)
    if isinstance(second, str):
        return _result("SKIP", second, executed=True)
    if first[0] != second[0]:
        return _result("SKIP", "lease_renewal_generation_changed",
                       executed=True)
    if second[1] <= first[1]:
        return _result("SKIP", "lease_renewal_not_advanced", executed=True)
    return _result("PASS", "lease_renewal_advanced",
                   executed=True, renewed=True)
