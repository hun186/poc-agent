"""OFF-1Q: one authenticated loopback Report Job GET for a SQL-selected item.

This operator-only partial probe ties the latest scheduled batch's selected
completed item to its persisted report_v1 submission, then independently
inspects the same job's live API status. It does NOT create jobs, download Word,
prove Agent/LLM/ES provenance, or attest airgap/network/PID identity.
"""
from __future__ import annotations

import json
import re
import socket
import time
from typing import Any

import pyodbc
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
SELECT TOP (2) i.remote_job_id, i.submission_id
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


def _recv_with_deadline(sock: socket.socket, deadline: float,
                        length: int) -> bytes:
    """Each socket read is individually bounded by the SAME absolute deadline."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("deadline_exceeded")
    sock.settimeout(left)
    data = sock.recv(length)
    if time.monotonic() > deadline:
        raise TimeoutError("deadline_exceeded")
    return data


def _http_get_one(port: int, token: str, job_id: str) -> bytes:
    """One fixed IPv4 TCP HTTP/1.1 GET with strict size/framing and total deadline.

    Avoid requests/urllib's per-idle read timeout, DNS, netrc, redirects,
    proxies, or streaming semantics. Reject chunked/compressed/unknown-length
    framing; the real FastAPI JSON route supplies Content-Length.
    """
    deadline = time.monotonic() + 3.0
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(max(0.001, deadline - time.monotonic()))
        sock.connect(("127.0.0.1", port))
        if time.monotonic() > deadline:
            raise TimeoutError("deadline_exceeded")
        request = (
            f"GET /v1/report/jobs/{job_id} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Authorization: Bearer {token}\r\n"
            "Accept: application/json\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("deadline_exceeded")
        sock.settimeout(left)
        sock.sendall(request)
        if time.monotonic() > deadline:
            raise TimeoutError("deadline_exceeded")
        frame = bytearray()
        while b"\r\n\r\n" not in frame:
            # 4 KiB maximum HTTP header frame, not just body length.
            if len(frame) > 4096:
                raise ValueError("headers_too_large")
            part = _recv_with_deadline(sock, deadline, 2048)
            if not part:
                raise ValueError("incomplete_headers")
            frame.extend(part)
            if len(frame) > 4096 + MAX_RESPONSE_BYTES + 4:
                raise ValueError("frame_too_large")
        header, body = bytes(frame).split(b"\r\n\r\n", 1)
        if len(header) > 4096:
            raise ValueError("headers_too_large")
        lines = header.split(b"\r\n")
        if not lines or not re.fullmatch(rb"HTTP/1\.[01] [0-9]{3} [^\r\n]{0,100}",
                                         lines[0]):
            raise ValueError("invalid_status_line")
        if lines[0].split(b" ", 2)[1] != b"200":
            raise ValueError("http_status_not_200")
        headers = {}
        for line in lines[1:]:
            if b":" not in line:
                raise ValueError("malformed_header")
            name, value = line.split(b":", 1)
            if re.fullmatch(rb"[A-Za-z0-9-]+", name) is None:
                raise ValueError("header_name_invalid")
            key = name.lower()
            if key in headers:
                raise ValueError("duplicate_header")
            headers[key] = value.strip()
        if b"transfer-encoding" in headers or b"content-encoding" in headers:
            raise ValueError("unsafe_encoding")
        mime = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if mime != b"application/json":
            raise ValueError("wrong_media")
        length_bytes = headers.get(b"content-length", b"")
        if re.fullmatch(rb"[0-9]{1,5}", length_bytes) is None:
            raise ValueError("length_invalid")
        length = int(length_bytes)
        if not 0 < length <= MAX_RESPONSE_BYTES:
            raise ValueError("length_unbounded")
        if len(body) > length:
            raise ValueError("extra_response_bytes")
        result = bytearray(body)
        while len(result) < length:
            part = _recv_with_deadline(sock, deadline, min(2048, length-len(result)))
            if not part:
                raise ValueError("body_truncated")
            result.extend(part)
        if time.monotonic() > deadline:
            raise TimeoutError("deadline_exceeded")
        return bytes(result)
    finally:
        sock.close()


def _remote_status(port: int, token: str, job_id: str,
                   submission_id: str) -> tuple[str, str]:
    """Bounded HTTP GET; no exception, body or identifiers reach the JSON row."""
    try:
        raw = _http_get_one(port, token, job_id)
    except TimeoutError:
        return "SKIP", "remote_http_deadline"
    except (OSError, ValueError, OverflowError, UnicodeError):
        return "SKIP", "remote_http_unverified"
    try:
        body = json.loads(raw.decode("utf-8"))
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
    except (ValueError, UnicodeError, TypeError):
        return "SKIP", "remote_response_invalid"


def probe_remote_report_job(
    sql_config: dict[str, str], *, schedule_id: str, api_port: str,
    read_token: str, schema: str = DEFAULT_SCHEMA,
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
        status, reason = _remote_status(port, read_token, *selected)
    except Exception:
        return _out("SKIP", "remote_http_unverified", executed=True)
    return _out(status, reason, executed=True,
                verified=status == "PASS" and reason == "remote_completed_attested")
