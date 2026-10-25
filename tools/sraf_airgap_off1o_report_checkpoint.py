"""OFF-1O: read-only persisted Report Job reconciliation checkpoint evidence.

One explicitly authorized SQL SELECT checks the latest actor-labelled scheduled
run for at least one *same-item* Report Job completion and artifact reconciliation
checkpoint. Persisted SQL markers are NOT remote HTTP verification or DOCX byte
inspection; the query never exposes job IDs, paths, hashes, timestamps or secrets.
"""
from __future__ import annotations

import pyodbc

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1l_schedule_claim import _SCHEDULE_ID_RE

# The same i row must hold every state checkpoint and link to an actual
# report_v1 submission. Do not conflate separate items within one batch.
_SQL = """
SELECT TOP (2)
 CASE WHEN r.batch_run_id IS NOT NULL AND r.handed_off_at IS NOT NULL
           AND r.reconciled_at IS NOT NULL THEN 1 ELSE 0 END,
 CASE WHEN EXISTS (
     SELECT 1
     FROM [{schema}].[requirement_batch_run_items] AS i
     INNER JOIN [{schema}].[requirement_handoff_submissions] AS h
         ON h.run_item_id=i.run_item_id
     WHERE i.batch_run_id=r.batch_run_id
       AND i.selection_status=N'selected'
       AND h.workflow_id=N'report_v1'
       AND i.remote_job_id IS NOT NULL
       AND i.dispatched_at IS NOT NULL
       AND i.remote_job_state=N'completed'
       AND i.remote_completed_at IS NOT NULL
       AND i.execution_state=N'completed'
       AND i.completed_at IS NOT NULL
       AND i.artifact_reconciled_at IS NOT NULL
       AND i.artifact_relative_path IS NOT NULL
       AND LEN(i.artifact_relative_path) > 0
       AND i.artifact_sha256 IS NOT NULL
       AND DATALENGTH(i.artifact_sha256)=64
       AND i.artifact_sha256 COLLATE Latin1_General_100_BIN2
           NOT LIKE N'%[^0-9a-f]%'
 ) THEN 1 ELSE 0 END
FROM [{schema}].[requirement_schedules] AS s
OUTER APPLY (
    SELECT TOP (1) batch_run_id, handed_off_at, reconciled_at
    FROM [{schema}].[requirement_batch_runs] AS r
    WHERE r.schedule_id=s.schedule_id
      AND r.trigger_type=N'scheduled'
      AND r.created_by=N'requirement-schedule-worker'
    ORDER BY r.scheduled_for DESC, r.batch_run_id DESC
) AS r
WHERE s.schedule_id=?
"""


def _result(status: str, reason: str, *, executed: bool = False,
            checkpoint: bool = False) -> Observation:
    return Observation(
        "REPORT-CHECKPOINT-01", "report-sql-checkpoint",
        "latest_schedule_run_one_item_persisted_completion_only",
        status, reason, executed, {"report_checkpoint_persisted": checkpoint},
    )


def probe_report_sql_checkpoint(
    cfg: dict[str, str], *, schedule_id: str,
    schema: str = DEFAULT_SCHEMA,
) -> Observation:
    """Return redacted partial evidence of a persisted completion only."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "report_checkpoint_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _result("SKIP", "report_checkpoint_schedule_id_invalid")
    connstr = _connection_string(cfg)
    if connstr is None:
        return _result("SKIP", "report_checkpoint_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "report_checkpoint_driver_unavailable")
    except Exception:
        return _result("SKIP", "report_checkpoint_driver_unavailable")
    db = cursor = None
    try:
        db = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cursor.fetchone(), cursor.fetchone()
        if second is not None:
            return _result("SKIP", "report_checkpoint_rows_ambiguous", executed=True)
        if first is None:
            return _result("SKIP", "report_checkpoint_schedule_absent", executed=True)
        if (len(first) != 2
                or any(type(v) is not int or v not in (0, 1) for v in first)):
            return _result("SKIP", "report_checkpoint_result_invalid", executed=True)
        if tuple(first) != (1, 1):
            return _result("SKIP", "report_checkpoint_not_observed", executed=True)
        return _result("PASS", "report_checkpoint_persisted",
                       executed=True, checkpoint=True)
    except Exception:
        return _result("SKIP", "report_checkpoint_sql_unverified",
                       executed=db is not None)
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
