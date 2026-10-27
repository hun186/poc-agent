"""OFF-1R: one SQL-selected run item bound to local DOCX and Report Job GET.

The earlier OFF-1P and OFF-1Q independently select the latest run item; this
new, separately opted-in partial check reuses ONE in-process SQL reference
across both observations, then re-reads it to reject selection drift. No new
jobs, Word download, SQL mutations, listener/PID or FULL_LIVE attestation.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path
import sys

import pyodbc

from requirement_scheduler.artifacts import output_root_fingerprint
from tools.sraf_airgap_off1_probes import Observation
from tools.sraf_airgap_off1g_sql_read import (
    DRIVER, LOGIN_TIMEOUT_SECONDS, QUERY_TIMEOUT_SECONDS, _connection_string,
)
from tools.sraf_airgap_off1i_handoff_lease import DEFAULT_SCHEMA, _SCHEMA_RE
from tools.sraf_airgap_off1l_schedule_claim import _SCHEDULE_ID_RE
from tools.sraf_airgap_off1p_docx_integrity import (
    _DIGEST_RE, _SAFE_ITEM_RE, _pin_root_directory, _inspect_local_docx,
)
from tools.sraf_airgap_off1q_remote_report_job import (
    _JOB_ID, _SUBMISSION_ID, _port, _token_valid, _remote_status,
)

# One report_v1 submission and *one* selected item, including its published
# bytes/path AND remote identity. All projections at the outer scope refer to
# aliases exposed by OUTER APPLY, never to the inner h alias.
_SQL = """
SELECT TOP (2)
    r.batch_run_id, i.run_item_id, i.artifact_relative_path,
    i.artifact_sha256, r.phase1a_output_root_fingerprint,
    i.remote_job_id, i.submission_id
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
    SELECT TOP (1)
        i.run_item_id, i.artifact_relative_path, i.artifact_sha256,
        i.remote_job_id, h.submission_id
    FROM [{schema}].[requirement_batch_run_items] AS i
    INNER JOIN [{schema}].[requirement_handoff_submissions] AS h
      ON h.run_item_id=i.run_item_id
    WHERE i.batch_run_id=r.batch_run_id
      AND i.selection_status=N'selected'
      AND h.workflow_id=N'report_v1'
      AND i.remote_job_id IS NOT NULL
      AND i.dispatched_at IS NOT NULL
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
        "REPORT-CHAIN-01", "report-docx-job-same-item",
        "one_sql_selected_item_local_docx_and_authenticated_job_only",
        status, reason, executed, {"single_item_chain_observed": verified},
    )


def _read_reference(connstr: str, schema: str, schedule_id: str):
    """One ODBC connection/SELECT, precisely seven strings; no raw error text."""
    conn = cur = None
    try:
        conn = pyodbc.connect(connstr, timeout=LOGIN_TIMEOUT_SECONDS,
                              autocommit=True)
        conn.timeout = QUERY_TIMEOUT_SECONDS
        cur = conn.cursor()
        cur.execute(_SQL.format(schema=schema), schedule_id)
        first, second = cur.fetchone(), cur.fetchone()
        if second is not None:
            return "chain_reference_ambiguous"
        if first is None:
            return "chain_reference_absent"
        if len(first) != 7 or any(type(x) is not str for x in first):
            return "chain_reference_invalid"
        return tuple(first)
    except Exception:
        return "chain_reference_sql_unverified"
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _valid_reference(row, root_fp: str) -> str | None:
    batch, item, relative, digest, persisted_root, job, submission = row
    if (not _SAFE_ITEM_RE.fullmatch(batch)
            or not _SAFE_ITEM_RE.fullmatch(item)
            or _DIGEST_RE.fullmatch(digest) is None
            or _DIGEST_RE.fullmatch(persisted_root) is None
            or _JOB_ID.fullmatch(job) is None
            or _SUBMISSION_ID.fullmatch(submission) is None):
        return "chain_reference_invalid"
    parts = relative.split("/")
    if len(parts) != 2 or parts[0] != item:
        return "chain_path_invalid"
    if not hmac.compare_digest(root_fp, persisted_root):
        return "chain_root_mismatch"
    return None


def probe_single_item_chain(cfg: dict[str, str], *, schedule_id: str,
                            artifact_root: str, api_port: str, read_token: str,
                            schema: str = DEFAULT_SCHEMA) -> Observation:
    """One pinned filesystem root, two SQL observations and one fixed GET."""
    if sys.platform != "linux" or not hasattr(os, "O_NOFOLLOW"):
        return _out("SKIP", "chain_host_unsupported")
    if not isinstance(schema, str) or _SCHEMA_RE.fullmatch(schema) is None:
        return _out("SKIP", "chain_schema_invalid")
    if not isinstance(schedule_id, str) or _SCHEDULE_ID_RE.fullmatch(schedule_id) is None:
        return _out("SKIP", "chain_schedule_invalid")
    if (not isinstance(artifact_root, str)
            or not artifact_root.startswith("/")
            or "\x00" in artifact_root
            or len(artifact_root.encode("utf-8")) > 1024
            or "." in artifact_root.split("/")
            or ".." in artifact_root.split("/")):
        return _out("SKIP", "chain_root_invalid")
    port = _port(api_port)
    if port is None:
        return _out("SKIP", "chain_port_invalid")
    if not _token_valid(read_token):
        return _out("SKIP", "chain_token_invalid")
    connstr = _connection_string(cfg)
    if connstr is None:
        return _out("SKIP", "chain_sql_config_invalid")
    try:
        if DRIVER not in pyodbc.drivers():
            return _out("SKIP", "chain_driver_unavailable")
    except Exception:
        return _out("SKIP", "chain_driver_unavailable")

    root_fd = None
    try:
        root = Path(artifact_root)
        # Pin every ancestor BEFORE either SQL SELECT. Never re-open root by
        # absolute path across database/API calls.
        root_fd = _pin_root_directory(root)
        root_fp = output_root_fingerprint(root)
    except (OSError, ValueError):
        return _out("SKIP", "chain_root_invalid")
    finally:
        # If computing the fingerprint failed after opening a root, release
        # it here without dropping a successful pinned FD.
        if "root_fp" not in locals() and root_fd is not None:
            os.close(root_fd)

    try:
        first = _read_reference(connstr, schema, schedule_id)
        if isinstance(first, str):
            return _out("SKIP", first, executed=True)
        invalid = _valid_reference(first, root_fp)
        if invalid is not None:
            return _out("SKIP", invalid, executed=True)
        _, _, relative, digest, _, job_id, submission_id = first
        local = _inspect_local_docx(root_fd, relative, digest)
        if local in ("docx_digest_mismatch", "docx_structure_invalid"):
            return _out("FAIL", "chain_" + local, executed=True)
        if local != "docx_local_bytes_match":
            return _out("SKIP", "chain_docx_unverified", executed=True)

        # Deliberately compare the API with the *same saved* reference;
        # never call OFF-1Q's separate latest-item SQL selector.
        remote_state, remote_reason = _remote_status(port, read_token,
                                                      job_id, submission_id)
        if remote_state == "FAIL":
            if remote_reason in ("remote_job_identity_mismatch",
                                 "remote_submission_mismatch",
                                 "remote_state_disagrees"):
                return _out("FAIL", "chain_" + remote_reason, executed=True)
            return _out("SKIP", "chain_api_unverified", executed=True)
        if remote_state != "PASS" or remote_reason != "remote_completed_attested":
            return _out("SKIP", "chain_api_unverified", executed=True)

        # A fresh SQL reference must still match all 7 initial strings after
        # the file and HTTP reads. This detects observed selection drift but
        # does NOT establish an atomic serializable SQL/API/filesystem view.
        last = _read_reference(connstr, schema, schedule_id)
        if isinstance(last, str):
            return _out("SKIP", "chain_recheck_unverified", executed=True)
        if last != first:
            return _out("SKIP", "chain_reference_changed", executed=True)
        return _out("PASS", "chain_same_item_observed",
                    executed=True, verified=True)
    except Exception:
        # Never emit exception text or unreviewed third-party reason strings.
        return _out("SKIP", "chain_probe_unverified", executed=True)
    finally:
        os.close(root_fd)
