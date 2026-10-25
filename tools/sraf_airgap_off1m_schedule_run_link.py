"""OFF-1M operator-only Schedule→latest actor-labelled run SQL linkage.

One non-mutating, parameterized, bounded SELECT after OFF-1L has independently
observed new scheduled-run ledger rows. Predicates are computed at SQL Server.
Neither the actor label nor this database read authenticates a local worker PID,
nor does an ordinary READ COMMITTED SELECT attest atomic multi-table state.
"""
from __future__ import annotations

import pyodbc

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1l_schedule_claim import _SCHEDULE_ID_RE

_SQL = """
SELECT TOP (2)
  CASE WHEN s.enabled=1 AND v.status=N'approved'
       THEN 1 ELSE 0 END,
  CASE WHEN r.batch_run_id IS NOT NULL
            AND r.schedule_version_id=s.active_version_id
            AND r.scheduled_for IS NOT NULL
       THEN 1 ELSE 0 END,
  CASE WHEN r.scheduled_for IS NOT NULL
            AND s.next_run_at IS NOT NULL
            AND s.next_run_at > r.scheduled_for
       THEN 1 ELSE 0 END
FROM [{schema}].[requirement_schedules] AS s
INNER JOIN [{schema}].[requirement_schedule_versions] AS v
        ON v.schedule_version_id=s.active_version_id
OUTER APPLY (
    SELECT TOP (1) batch_run_id, schedule_version_id, scheduled_for
    FROM [{schema}].[requirement_batch_runs] AS r
    WHERE r.schedule_id=s.schedule_id
      AND r.trigger_type=N'scheduled'
      AND r.created_by=N'requirement-schedule-worker'
    ORDER BY r.scheduled_for DESC, r.batch_run_id DESC
) AS r
WHERE s.schedule_id=?
"""


def _result(status: str, reason: str, *, executed: bool = False,
            linked: bool = False) -> Observation:
    return Observation("SCHEDULE-02", "schedule-run-link",
                       "latest_actor_labeled_run_schedule_link_only",
                       status, reason, executed,
                       {"link_predicates_observed": linked})


def probe_schedule_run_link(
    cfg: dict[str, str], *, schedule_id: str,
    schema: str = DEFAULT_SCHEMA,
) -> Observation:
    """Three SQL-computed flags; no row identifiers, run data or writes."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "link_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _result("SKIP", "link_schedule_id_invalid")
    connstr = _connection_string(cfg)
    if connstr is None:
        return _result("SKIP", "link_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "link_driver_unavailable")
    except Exception:
        return _result("SKIP", "link_driver_unavailable")
    db = cursor = None
    try:
        db = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cursor.fetchone(), cursor.fetchone()
        if second is not None:
            return _result("SKIP", "link_rows_ambiguous", executed=True)
        if first is None:
            return _result("SKIP", "link_schedule_not_observed", executed=True)
        if (len(first) != 3
                or any(type(x) is not int or x not in (0, 1) for x in first)):
            return _result("SKIP", "link_result_invalid", executed=True)
        if tuple(first) != (1, 1, 1):
            return _result("SKIP", "link_predicates_unverified",
                           executed=True)
        return _result("PASS", "link_current_schedule_run_observed",
                       executed=True, linked=True)
    except Exception:
        # No SQLSTATE, database object, credentials or worker data in output.
        return _result("SKIP", "link_sql_unverified", executed=db is not None)
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
