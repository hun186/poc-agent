"""OFF-1N: read-only SQL evidence of persisted Handoff submission acknowledgement.

One extra, explicitly gated SQL query checks the latest actor-labelled
scheduled batch run for persisted submission and remote-job reference. This is
NOT remote API verification, actual Report Job progress, PID attribution or
valid DOCX evidence; no schedule/job writes, secrets or data payload reads.
"""
from __future__ import annotations

import pyodbc

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1l_schedule_claim import _SCHEDULE_ID_RE

# Only server-computed predicates leave SQL; no run, job, submission or
# requirement identifiers, semantic_manifest_json, hashes or path values.
_SQL = """
SELECT TOP (2)
    CASE WHEN r.batch_run_id IS NOT NULL
               AND r.selected_count > 0
               AND r.handoff_started_at IS NOT NULL
               AND r.handed_off_at IS NOT NULL
         THEN 1 ELSE 0 END,
    CASE WHEN EXISTS (
        SELECT 1
        FROM [{schema}].[requirement_batch_run_items] AS i
        INNER JOIN [{schema}].[requirement_handoff_submissions] AS h
                ON h.run_item_id=i.run_item_id
        WHERE i.batch_run_id=r.batch_run_id
          AND i.selection_status=N'selected'
          AND i.remote_job_id IS NOT NULL
          AND i.dispatched_at IS NOT NULL
          AND h.workflow_id=N'report_v1'
    ) THEN 1 ELSE 0 END
FROM [{schema}].[requirement_schedules] AS s
OUTER APPLY (
    SELECT TOP (1) batch_run_id, selected_count,
                   handoff_started_at, handed_off_at
    FROM [{schema}].[requirement_batch_runs] AS r
    WHERE r.schedule_id=s.schedule_id
      AND r.trigger_type=N'scheduled'
      AND r.created_by=N'requirement-schedule-worker'
    ORDER BY r.scheduled_for DESC, r.batch_run_id DESC
) AS r
WHERE s.schedule_id=?
"""


def _result(status: str, reason: str, *, executed: bool = False,
            acknowledged: bool = False) -> Observation:
    return Observation("HANDOFF-ACK-01", "handoff-sql-ack",
                       "latest_schedule_run_persisted_handoff_ack_only",
                       status, reason, executed,
                       {"handoff_ack_persisted": acknowledged})


def probe_handoff_sql_ack(cfg: dict[str, str], *, schedule_id: str,
                          schema: str = DEFAULT_SCHEMA) -> Observation:
    """Check persisted SQL acknowledgement; no remote Job status lookup."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "ack_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _result("SKIP", "ack_schedule_id_invalid")
    connection = _connection_string(cfg)
    if connection is None:
        return _result("SKIP", "ack_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "ack_driver_unavailable")
    except Exception:
        return _result("SKIP", "ack_driver_unavailable")
    db = cursor = None
    try:
        db = pyodbc.connect(connection, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cursor.fetchone(), cursor.fetchone()
        if second is not None:
            return _result("SKIP", "ack_rows_ambiguous", executed=True)
        if first is None:
            return _result("SKIP", "ack_schedule_not_observed", executed=True)
        if (len(first) != 2
                or any(type(value) is not int or value not in (0, 1)
                       for value in first)):
            return _result("SKIP", "ack_result_invalid", executed=True)
        if tuple(first) != (1, 1):
            return _result("SKIP", "ack_predicates_unverified", executed=True)
        return _result("PASS", "ack_persisted_submission_observed",
                       executed=True, acknowledged=True)
    except Exception:
        return _result("SKIP", "ack_sql_unverified", executed=db is not None)
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
