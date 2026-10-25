"""OFF-1L: read-only, operator-opt-in Schedule actor-labelled ledger growth.

Two independent SQL Server count snapshots 15 seconds apart are scoped to one
canonical schedule ID. Application created_by values are not authenticated
worker identity; a PASS never proves the local Schedule PID claimed a run.
"""
from __future__ import annotations

import re
import time

import pyodbc

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1j_handoff_renewal import SAMPLE_INTERVAL_SECONDS

SCHEDULE_ID_KEY = "SRAF_OFF1L_SCHEDULE_ID"
_SCHEDULE_ID_RE = re.compile(r"sch_[0-9a-f]{32}\Z")
_SQL = """
SELECT COUNT_BIG(*)
FROM [{schema}].[requirement_batch_runs]
WHERE schedule_id=? AND trigger_type=N'scheduled'
  AND created_by=N'requirement-schedule-worker'
"""


def _result(status: str, reason: str, *, executed: bool = False,
            observed: bool = False) -> Observation:
    return Observation("SCHEDULE-01", "schedule-claim-ledger",
                       "schedule_actor_labeled_run_increment_only",
                       status, reason, executed,
                       {"run_increment_observed": observed})


def _read_count(connstr: str, schema: str, schedule_id: str) -> int | str:
    conn = cursor = None
    try:
        conn = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                              autocommit=True)
        conn.timeout = QUERY_TIMEOUT_SECONDS
        cursor = conn.cursor()
        cursor.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cursor.fetchone(), cursor.fetchone()
        if first is None or second is not None or len(first) != 1:
            return "claim_result_invalid"
        value = first[0]
        if type(value) is not int or not 0 <= value <= 9223372036854775807:
            return "claim_result_invalid"
        return value
    except Exception:
        return "claim_sql_unverified"
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


def probe_schedule_claim_ledger(
    cfg: dict[str, str], *, schedule_id: str,
    schema: str = DEFAULT_SCHEMA,
) -> Observation:
    """Observe committed database ledger growth; never mutate or claim."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _result("SKIP", "claim_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _result("SKIP", "claim_schedule_id_invalid")
    connstr = _connection_string(cfg)
    if connstr is None:
        return _result("SKIP", "claim_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _result("SKIP", "claim_driver_unavailable")
    except Exception:
        return _result("SKIP", "claim_driver_unavailable")
    before = _read_count(connstr, schema, schedule_id)
    if isinstance(before, str):
        return _result("SKIP", before, executed=True)
    try:
        time.sleep(SAMPLE_INTERVAL_SECONDS)
    except Exception:
        return _result("SKIP", "claim_wait_interrupted", executed=True)
    after = _read_count(connstr, schema, schedule_id)
    if isinstance(after, str):
        return _result("SKIP", after, executed=True)
    if after <= before:
        return _result("SKIP", "claim_not_advanced", executed=True)
    return _result("PASS", "claim_actor_labeled_run_added",
                   executed=True, observed=True)
