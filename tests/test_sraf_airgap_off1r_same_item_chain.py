"""OFF-1R: one pinned SQL item -> local DOCX + authenticated Job -> SQL recheck."""
from __future__ import annotations

import hashlib
import io
import json
import os
from types import SimpleNamespace
import zipfile

import pytest

from tools import sraf_airgap_off1r_same_item_chain as chain
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SCHEDULE = "sch_" + "a" * 32
ITEM = "rit_" + "b" * 32
BATCH = "brun_" + "c" * 32
JOB = "rpt_" + "d" * 32
SUBMISSION = "rhsub_" + "e" * 48
TOKEN = "READ_TOKEN_FOR_TEST_ONLY"
PASSWORD = "SQL_PASS_FOR_TEST_ONLY"


def sql_config():
    return {"SRAF_OFF1G_SQL_HOST":"10.1.2.3", "SRAF_OFF1G_SQL_PORT":"1433",
            "SRAF_OFF1G_SQL_DATABASE":"control", "SRAF_OFF1G_SQL_USER":"reader",
            "SRAF_OFF1G_SQL_PASSWORD":PASSWORD}


def word():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<doc><p>hello</p></doc>")
    return stream.getvalue()


class Cursor:
    def __init__(self, rows, calls):
        self.rows = list(rows)
        self.calls = calls
    def execute(self, sql, *params):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "r.batch_run_id, i.run_item_id" in sql
        assert "i.artifact_sha256, r.phase1a_output_root_fingerprint" in sql
        assert "i.remote_job_id, i.submission_id" in sql
        assert "i.remote_job_id, h.submission_id" in sql  # inner APPLY
        assert "i.remote_job_id IS NOT NULL" in sql
        assert "i.dispatched_at IS NOT NULL" in sql
        assert "h.remote_job_id" not in sql
        assert "h.dispatched_at" not in sql
        assert "h.run_item_id=i.run_item_id" in sql
        assert "h.workflow_id=N'report_v1'" in sql
        assert "ORDER BY i.completed_at DESC, i.run_item_id DESC" in sql
        assert "UPDATE " not in sql and "DELETE " not in sql
        assert "INSERT " not in sql
        assert params == (SCHEDULE,)
        self.calls.append((sql, params))
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None
    def close(self): pass


class DB:
    def __init__(self, rows, calls):
        self.cur = Cursor(rows, calls)
        self.timeout = None
    def cursor(self): return self.cur
    def close(self): pass


def setup(tmp_path, monkeypatch, *, first=None, last=None, data=None):
    root = tmp_path / "root"
    (root / ITEM).mkdir(parents=True)
    payload = word() if data is None else data
    (root / ITEM / "report.docx").write_bytes(payload)
    row = (BATCH, ITEM, ITEM + "/report.docx",
           hashlib.sha256(payload).hexdigest(),
           chain.output_root_fingerprint(root), JOB, SUBMISSION)
    batches = [[row if first is None else first],
               [row if last is None else last]]
    calls = []
    monkeypatch.setattr(chain.pyodbc, "drivers", lambda: [chain.DRIVER])
    def connect(*args,**kwargs):
        assert kwargs["autocommit"] is True
        return DB(batches.pop(0), calls)
    monkeypatch.setattr(chain.pyodbc, "connect", connect)
    remotes = []
    def status(port,token,job,submission):
        remotes.append((port,token,job,submission))
        return ("PASS", "remote_completed_attested")
    monkeypatch.setattr(chain, "_remote_status",status)
    return root,row,calls,remotes


def observe(root, *, port="8123", sid=SCHEDULE, token=TOKEN):
    return chain.probe_single_item_chain(
        sql_config(), schedule_id=sid, artifact_root=str(root),
        api_port=port, read_token=token)


def test_one_exact_row_binds_local_file_and_remote_status(tmp_path,monkeypatch):
    root,row,calls,remote_calls = setup(tmp_path,monkeypatch)
    o=observe(root)
    assert (o.status,o.reason,o.executed,o.evidence)==(
        "PASS","chain_same_item_observed",True,
        {"single_item_chain_observed":True})
    assert len(calls)==2  # before and after HTTP, two bounded SELECTs
    assert remote_calls==[(8123,TOKEN,JOB,SUBMISSION)]
    for secret in (PASSWORD,TOKEN,SCHEDULE,ITEM,BATCH,JOB,SUBMISSION,str(root),
                   row[3]):
        assert secret not in json.dumps(o.__dict__)


def test_same_item_other_run_after_http_never_passes(tmp_path,monkeypatch):
    root,row,calls,remote_calls=setup(tmp_path,monkeypatch)
    changed=(row[0], "rit_"+"f"*32, *row[2:])
    # Initial and later row need different return values.
    response_rows=[[row],[changed]]
    monkeypatch.setattr(chain.pyodbc,"connect",
       lambda *a,**k: DB(response_rows.pop(0),calls))
    r=observe(root)
    assert (r.status,r.reason)==("SKIP","chain_reference_changed")
    assert len(remote_calls)==1 and len(calls)==2


@pytest.mark.parametrize("position", [0,1,2,3,4,5,6])
def test_no_pass_if_any_immutable_reference_field_changes(tmp_path,monkeypatch,position):
    root,row,calls,remote_calls=setup(tmp_path,monkeypatch)
    changed=list(row);changed[position]="x"+changed[position]
    selections=[[row],[tuple(changed)]]
    monkeypatch.setattr(chain.pyodbc, "connect",
                        lambda *a,**k: DB(selections.pop(0),calls))
    r=observe(root)
    assert r.reason=="chain_reference_changed" and r.status=="SKIP"


def test_tampered_actual_docx_is_fail_without_http(tmp_path,monkeypatch):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    (root / ITEM / "report.docx").write_bytes(b"mismatch")
    r=observe(root)
    assert (r.status,r.reason)==("FAIL","chain_docx_digest_mismatch")
    assert remotes == [] and len(calls)==1


def test_corrupt_zip_with_matching_digest_is_fail(tmp_path,monkeypatch):
    root,row,calls,remotes=setup(tmp_path,monkeypatch,data=b"not ZIP")
    r=observe(root)
    assert (r.status,r.reason)==("FAIL","chain_docx_structure_invalid")
    assert remotes == [] and len(calls)==1


@pytest.mark.parametrize("edit,reason", [
    ({1:"other"}, "chain_path_invalid"),
    ({2:"../secrets.docx"}, "chain_path_invalid"),
    ({2:"rit_"+"0"*32+"/report.docx"}, "chain_path_invalid"),
    ({3:"g"*64}, "chain_reference_invalid"),
    ({4:"0"*64}, "chain_root_mismatch"),
    ({5:"rpt_../../passwd"}, "chain_reference_invalid"),
    ({6:"wrong"}, "chain_reference_invalid"),
    ({0:"weird/id"}, "chain_reference_invalid"),
])
def test_invalid_persisted_reference_never_reaches_remote(tmp_path,monkeypatch,edit,reason):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    first=list(row)
    for key,value in edit.items():first[key]=value
    selection=[[tuple(first)]]
    monkeypatch.setattr(chain.pyodbc, "connect",
                        lambda *a,**k: DB(selection.pop(0),calls))
    r=observe(root)
    assert (r.status,r.reason)==("SKIP",reason)
    assert remotes==[] and len(calls)==1


@pytest.mark.parametrize("remote_state,reason,expected",[
    (("FAIL","remote_submission_mismatch"),"chain_remote_submission_mismatch","FAIL"),
    (("FAIL","remote_job_identity_mismatch"),"chain_remote_job_identity_mismatch","FAIL"),
    (("FAIL","remote_state_disagrees"),"chain_remote_state_disagrees","FAIL"),
    (("SKIP","remote_http_deadline"),"chain_api_unverified","SKIP"),
    (("SKIP","remote_http_unverified"),"chain_api_unverified","SKIP"),
])
def test_remote_not_exact_must_not_pass(tmp_path,monkeypatch,
                                       remote_state,reason,expected):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    monkeypatch.setattr(chain, "_remote_status",
                        lambda *a: remote_state)
    r=observe(root)
    assert (r.status,r.reason)==(expected,reason)
    assert len(calls)==1


def test_symlink_swap_during_sql_never_escapes_pinned_root(tmp_path,monkeypatch):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    new_parent=tmp_path/"attacker"
    (new_parent/"root"/ITEM).mkdir(parents=True)
    changed=b"outside bytes"
    (new_parent/"root"/ITEM/"report.docx").write_bytes(changed)
    parent=root.parent
    # root is nested directly below tmp_path: move the root after the pin,
    # and replace it with a symlink to an outside copy for the SQL result.
    original_connect=chain.pyodbc.connect
    def sql_swap(*a,**kw):
        if not calls:
            root.rename(tmp_path/"moved_original")
            root.symlink_to(new_parent/"root",target_is_directory=True)
        return original_connect(*a,**kw)
    monkeypatch.setattr(chain.pyodbc,"connect",sql_swap)
    r=observe(root)
    assert r.status=="PASS"  # pin uses original directory and original digest
    assert len(remotes)==1
    # PASS attests the original pinned data, not the attacker's replacement.
    # Root-string fingerprint may not change, so trusted parent/mount is needed.


def test_symlink_docx_never_followed(tmp_path,monkeypatch):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    file=root/ITEM/"report.docx"
    file.unlink();file.symlink_to(tmp_path/"secret.docx")
    r=observe(root)
    assert r.status=="SKIP" and r.reason=="chain_docx_unverified"
    assert remotes==[]


@pytest.mark.parametrize("sid,port,token,reason",[
    (None,"8123",TOKEN,"chain_schedule_invalid"),
    ("bad","8123",TOKEN,"chain_schedule_invalid"),
    (SCHEDULE,"0",TOKEN,"chain_port_invalid"),
    (SCHEDULE,"1/path",TOKEN,"chain_port_invalid"),
    (SCHEDULE,"8123","bad\r\nHost:evil","chain_token_invalid"),
    (SCHEDULE,"8123","","chain_token_invalid"),
])
def test_invalid_input_never_contacts_sql_or_http(tmp_path,monkeypatch,sid,port,token,reason):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    monkeypatch.setattr(chain.pyodbc,"drivers",lambda: pytest.fail("driver"))
    r=observe(root,sid=sid,port=port,token=token)
    assert (r.status,r.reason)==("SKIP",reason)
    assert remotes==[]


def test_sql_error_or_second_read_failure_is_redacted(tmp_path,monkeypatch):
    root,row,calls,remotes=setup(tmp_path,monkeypatch)
    monkeypatch.setattr(chain.pyodbc,"connect",
                        lambda *a,**k: (_ for _ in ()).throw(RuntimeError(PASSWORD)))
    r=observe(root)
    assert (r.status,r.reason)==("SKIP","chain_reference_sql_unverified")
    assert PASSWORD not in json.dumps(r.__dict__)
    # Now success first, then second SQL throws.
    prepared=[True,False]
    def connect(*a,**k):
        if prepared.pop(0):return DB([row],calls)
        raise RuntimeError(PASSWORD)
    monkeypatch.setattr(chain.pyodbc,"connect",connect)
    r=observe(root)
    assert (r.status,r.reason)==("SKIP","chain_recheck_unverified")
    assert PASSWORD not in json.dumps(r.__dict__)


def test_matrix_tenth_optin_and_previous_live_pass_are_required(monkeypatch):
    seen=[]
    def good(*args,**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            check_id="REPORT-CHAIN-01",probe="report-docx-job-same-item",
            aspect="one_sql_selected_item_local_docx_and_authenticated_job_only",
            status="PASS",reason="chain_same_item_observed",executed=True,
            evidence={"single_item_chain_observed":True})
    monkeypatch.setattr(matrix,"probe_single_item_chain",good)
    args=dict(sql_config=sql_config(),schedule_id=SCHEDULE,lease_schema=None,
        artifact_root="/tmp/operator/root",api_port="8123",read_token=TOKEN)
    for flags,live,expected in [
        ((False,)*10,"PASS","NOT_TESTED"),
        ((True,)*9+(False,),"PASS","NOT_TESTED"),
        ((True,)*10,"SKIP","SKIP"),
        ((True,)*10,"PASS","PASS"),
    ]:
        row=matrix._report_chain_check(flags=flags,live_status=live,**args)
        assert row["status"]==expected
    assert len(seen)==1
    assert row["depends_on"]==["SQL-READ","DOCX-BYTES","REPORT-LIVE"]


def test_matrix_rejects_forged_pass_and_secret_leak(monkeypatch):
    monkeypatch.setattr(matrix,"probe_single_item_chain",lambda *a,**k:
        SimpleNamespace(
            check_id="REPORT-CHAIN-01",probe="report-docx-job-same-item",
            aspect="one_sql_selected_item_local_docx_and_authenticated_job_only",
            status="PASS",reason="chain_same_item_observed",executed=True,
            evidence={"single_item_chain_observed":True,"secret":TOKEN}))
    row=matrix._report_chain_check(
        flags=(True,)*10,live_status="PASS",
        sql_config=sql_config(),schedule_id=SCHEDULE,lease_schema=None,
        artifact_root="/tmp/operator/root",api_port="8123",read_token=TOKEN)
    assert (row["status"],row["reason"])==("SKIP","unexpected_probe_result")
    assert TOKEN not in json.dumps(row)


def test_sql_query_columns_follow_real_migration_schema():
    """Catch invalid table alias/columns that fake ODBC cannot parse."""
    import re
    from requirement_scheduler.migrations import REQUIRED_COLUMNS

    query = chain._SQL
    item_cols = {c.name for c in REQUIRED_COLUMNS["requirement_batch_run_items"]}
    handoff_cols = {c.name for c in REQUIRED_COLUMNS["requirement_handoff_submissions"]}
    batch_cols = {c.name for c in REQUIRED_COLUMNS["requirement_batch_runs"]}
    schedule_cols = {c.name for c in REQUIRED_COLUMNS["requirement_schedules"]}
    # Keep a complete alias to-table map, including OUTER APPLY outputs.
    for alias, table_cols in (("s", schedule_cols), ("r", batch_cols),
                              ("h", handoff_cols), ("i", item_cols)):
        mentioned = re.findall(r"\\b" + alias + r"\\.([a-z_][a-z_0-9]*)\\b", query)
        assert mentioned
        assert set(mentioned) <= table_cols, (alias, set(mentioned)-table_cols)
    assert "i.remote_job_id IS NOT NULL" in query
    assert "i.dispatched_at IS NOT NULL" in query
    assert "h.remote_job_id" not in query
    assert "h.dispatched_at" not in query
