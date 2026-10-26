"""OFF-1Q: one authenticated loopback Report Job GET for a SQL-selected item.

This operator-only partial probe ties the latest scheduled batch's selected
completed item to its persisted report_v1 submission, then independently
inspects the same job's live API status. It does NOT create jobs, download Word,
prove Agent/LLM/ES provenance, or attest airgap/network/PID identity.
"""
from __future__ import annotations

import json
import re
from typing import Any

import pyodbc
import requests

from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1l_schedule_claim import _SCHEDULE_ID_RE

PORT_KEY = "SRAF_OFF1Q_REPORT_API_PORT"
TOKEN_KEY = "SRAF_OFF1Q_REPORT_JOB_READ_TOKEN"
_JOB_ID = re.compile(r"rpt_[0-9a-f]{32}\Z")
_SUBMISSION_ID = re.compile(r"rhsub_[0-9a-f]{48}\Z")
MAX_RESPONSE_BYTES = 8192

# Mirror OFF-1P's TOP(1) selected-item ordering. The h join and item/job
# constraints are SAME ROW, not a separate batch-level EXISTS predicate.
_SQL = """
SELECT TOP (2) i.remote_job_id, h.submission_id
FROM [{schema}].[requirement_schedules] AS s
OUTER APPLY (
    SELECT TOP (1) r.batch_run_id
    FROM [{schema}].[requirement_batch_runs] AS r
    WHERE r.schedule_id=s.schedule_id
      AND r.trigger_type=N'scheduled'
      AND r.created_by=N'requirement-schedule-worker'
    ORDER BY r.scheduled_for DESC, r.batch_run_id DESC
) AS r
OUTER APPLY (
    SELECT TOP (1) i.remote_job_id, h.submission_id
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


def _out(status: str, reason: str, *, executed: bool = False,
         verified: bool = False) -> Observation:
    return Observation(
        "REPORT-LIVE-01", "report-job-loopback-get",
        "same_persisted_item_authenticated_remote_status_only",
        status, reason, executed, {"remote_job_completed_observed": verified},
    )


def _sql_reference(connstr: str, schema: str, schedule_id: str
                   ) -> tuple[str, str] | str:
    db = cursor = None
    try:
        db = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                            autocommit=True)
        db.timeout = QUERY_TIMEOUT_SECONDS
        cursor = db.cursor()
        cursor.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cursor.fetchone(), cursor.fetchone()
        if second is not None:
            return "remote_reference_ambiguous"
        if first is None:
            return "remote_reference_absent"
        if len(first) != 2 or any(type(v) is not str for v in first):
            return "remote_reference_invalid"
        if _JOB_ID.fullmatch(first[0]) is None or _SUBMISSION_ID.fullmatch(first[1]) is None:
            return "remote_reference_invalid"
        return first[0], first[1]
    except Exception:
        return "remote_sql_unverified"
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


def _port(value: Any) -> int | None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,5}", value) is None:
        return None
    n = int(value)
    return n if 1 <= n <= 65535 else None


def _token_valid(token: Any) -> bool:
    return (isinstance(token, str) and 1 <= len(token) <= 4096
            and all(33 <= ord(ch) <= 126 for ch in token))


def _remote_status(port: int, token: str, job_id: str,
                   submission_id: str, *, session: Any = None) -> tuple[str, str]:
    """One no-proxy, no-redirect, bounded HTTP GET, never echo response."""
    client = session if session is not None else requests.Session()
    response = None
    try:
        # Requests' default trust_env=True reads HTTP(S)_PROXY and netrc;
        # even a loopback URI must never carry this credential to a proxy.
        client.trust_env = False
        url = f"http://127.0.0.1:{port}/v1/report/jobs/{job_id}"
        response = client.get(
            url, headers={"Authorization": "Bearer " + token,
                          "Accept": "application/json", "Connection": "close"},
            allow_redirects=False, timeout=(2, 3), stream=True,
        )
        if response.status_code != 200:
            return "SKIP", "remote_http_unverified"
        media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            return "SKIP", "remote_response_invalid"
        size_header = response.headers.get("Content-Length")
        if size_header is not None and (
                re.fullmatch(r"[0-9]{1,9}", size_header) is None
                or int(size_header) > MAX_RESPONSE_BYTES):
            return "SKIP", "remote_response_oversized"
        chunks: list[bytes] = []
        total = 0
        for part in response.iter_content(chunk_size=2048):
            if not isinstance(part, bytes):
                return "SKIP", "remote_response_invalid"
            total += len(part)
            if total > MAX_RESPONSE_BYTES:
                return "SKIP", "remote_response_oversized"
            chunks.append(part)
        body = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(body, dict):
            return "SKIP", "remote_response_invalid"
        if body.get("job_id") != job_id:
            return "FAIL", "remote_job_identity_mismatch"
        metadata = body.get("metadata")
        if (not isinstance(metadata, dict)
                or metadata.get("submission_id") != submission_id
                or metadata.get("workflow_id") != "report_v1"):
            return "FAIL", "remote_submission_mismatch"
        state = body.get("status")
        if state == "completed":
            return "PASS", "remote_completed_attested"
        if state in ("failed", "interrupted"):
            return "FAIL", "remote_state_disagrees"
        if state in ("queued", "running"):
            return "SKIP", "remote_still_in_progress"
        return "SKIP", "remote_response_invalid"
    except (requests.RequestException, ValueError, UnicodeError, TypeError,
            OverflowError):
        return "SKIP", "remote_http_unverified"
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        if session is None:
            try:
                client.close()
            except Exception:
                pass


def probe_remote_report_job(
    sql_config: dict[str, str], *, schedule_id: str, api_port: str,
    read_token: str, schema: str = DEFAULT_SCHEMA, session: Any = None,
) -> Observation:
    """Only partial GET evidence. No SQL mutation or job creation."""
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _out("SKIP", "remote_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _out("SKIP", "remote_schedule_id_invalid")
    port = _port(api_port)
    if port is None:
        return _out("SKIP", "remote_port_invalid")
    if not _token_valid(read_token):
        return _out("SKIP", "remote_token_invalid")
    connstr = _connection_string(sql_config)
    if connstr is None:
        return _out("SKIP", "remote_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _out("SKIP", "remote_driver_unavailable")
    except Exception:
        return _out("SKIP", "remote_driver_unavailable")
    selected = _sql_reference(connstr, schema, schedule_id)
    if isinstance(selected, str):
        return _out("SKIP", selected, executed=True)
    try:
        status, reason = _remote_status(port, read_token, *selected,
                                        session=session)
    except Exception:
        return _out("SKIP", "remote_http_unverified", executed=True)
    return _out(status, reason, executed=True,
                verified=status == "PASS" and reason == "remote_completed_attested")
