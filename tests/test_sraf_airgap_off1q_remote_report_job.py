"""OFF-1Q Report Job: SQL binding and authenticated loopback GET."""
from __future__ import annotations
import json
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1q_remote_report_job as remote
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "a" * 32
JOB = "rpt_" + "b" * 32
SUB = "rhsub_" + "c" * 48
TOKEN = "KEEP_SECRET_BEARER"


def sqlcfg():
    return {"SRAF_OFF1G_SQL_HOST":"10.2.3.4",
            "SRAF_OFF1G_SQL_PORT":"1433",
            "SRAF_OFF1G_SQL_DATABASE":"control",
            "SRAF_OFF1G_SQL_USER":"readonly",
            "SRAF_OFF1G_SQL_PASSWORD":"HIDDEN_PASSWORD"}


class Cursor:
    def __init__(self, rows, calls):
        self.rows, self.calls = list(rows), calls
    def execute(self, sql, *args):
        assert sql.lstrip().startswith("SELECT TOP (2)")
        assert "requirement_batch_run_items" in sql
        assert "requirement_handoff_submissions" in sql
        assert "h.run_item_id=i.run_item_id" in sql
        assert "i.remote_job_state=N'completed'" in sql
        assert "i.execution_state=N'completed'" in sql
        assert "ORDER BY i.completed_at DESC, i.run_item_id DESC" in sql
        assert "UPDATE " not in sql and "INSERT " not in sql
        self.calls.append((sql, args))
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None
    def close(self): pass


class DB:
    def __init__(self, rows, calls):
        self.cur, self.timeout = Cursor(rows, calls), None
    def cursor(self): return self.cur
    def close(self): pass


def fake_sql(monkeypatch, rows=((JOB, SUB),)):
    calls = []
    monkeypatch.setattr(remote.pyodbc, "drivers", lambda: [remote.DRIVER])
    monkeypatch.setattr(remote.pyodbc, "connect",
                        lambda *a, **kw: DB(rows, calls))
    return calls


def payload(*, job=JOB, sub=SUB, status="completed"):
    return {"job_id":job, "status":status,
            "metadata":{"submission_id":sub, "workflow_id":"report_v1"}}


class Response:
    def __init__(self, body=None, status=200, headers=None):
        self.body = json.dumps(payload() if body is None else body).encode()
        self.status_code = status
        self.headers = {"Content-Type":"application/json"} if headers is None else headers
        self.closed = False
    def iter_content(self, chunk_size):
        for i in range(0,len(self.body),chunk_size):
            yield self.body[i:i+chunk_size]
    def close(self): self.closed = True


class Client:
    def __init__(self, response=None):
        self.response = response if response is not None else Response()
        self.calls = []
        self.trust_env = True
    def get(self, url, **kwargs):
        self.calls.append((url,kwargs,self.trust_env))
        return self.response


def check(monkeypatch, response=None):
    sql_calls=fake_sql(monkeypatch)
    client=Client(response)
    r=remote.probe_remote_report_job(sqlcfg(),schedule_id=SID,api_port="8000",
                                      read_token=TOKEN,session=client)
    return r,client,sql_calls


def test_real_get_contract_and_redacted_result(monkeypatch):
    r,client,sql_calls=check(monkeypatch)
    assert (r.status,r.reason,r.evidence)==(
        "PASS","remote_completed_attested",{"remote_job_completed_observed":True})
    assert sql_calls[0][1] == (SID,)
    assert len(client.calls)==1
    url,kwargs,trust=client.calls[0]
    assert url=="http://127.0.0.1:8000/v1/report/jobs/"+JOB
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == (2,3)
    assert kwargs["headers"]["Authorization"]=="Bearer "+TOKEN
    assert trust is False and client.response.closed
    for sensitive in (SID, JOB, SUB, TOKEN, "HIDDEN_PASSWORD", "127.0.0.1"):
        assert sensitive not in json.dumps(r.__dict__)


@pytest.mark.parametrize("body,status,why", [
    (payload(job="rpt_"+"d"*32), "FAIL","remote_job_identity_mismatch"),
    (payload(sub="rhsub_"+"d"*48),"FAIL","remote_submission_mismatch"),
    (payload(status="failed"),"FAIL","remote_state_disagrees"),
    (payload(status="interrupted"),"FAIL","remote_state_disagrees"),
    (payload(status="queued"),"SKIP","remote_still_in_progress"),
    (payload(status="running"),"SKIP","remote_still_in_progress"),
    (payload(status="unknown"),"SKIP","remote_response_invalid"),
    ({"job_id":JOB,"status":"completed"},"FAIL","remote_submission_mismatch"),
    ({"job_id":JOB,"status":"completed","metadata":{"submission_id":SUB,
         "workflow_id":"wrong"}},"FAIL","remote_submission_mismatch"),
])
def test_remote_status_identity_and_state(monkeypatch,body,status,why):
    r,client,_=check(monkeypatch,Response(body))
    assert (r.status,r.reason)==(status,why) and client.response.closed


@pytest.mark.parametrize("rows,why", [
    ((),"remote_reference_absent"),
    (((JOB,),),"remote_reference_invalid"),
    ((("bad/id",SUB),),"remote_reference_invalid"),
    (((JOB,"x"*55),),"remote_reference_invalid"),
    (((JOB,SUB),(JOB,SUB)),"remote_reference_ambiguous"),
])
def test_sql_fail_closed_never_http(monkeypatch,rows,why):
    fake_sql(monkeypatch,rows)
    client=Client()
    r=remote.probe_remote_report_job(sqlcfg(),schedule_id=SID,api_port="8000",
                                      read_token=TOKEN,session=client)
    assert (r.status,r.reason)==("SKIP",why)
    assert client.calls==[]


@pytest.mark.parametrize("sid,port,token,why", [
    (None,"8000",TOKEN,"remote_schedule_id_invalid"),
    ("sch_"+"A"*32,"8000",TOKEN,"remote_schedule_id_invalid"),
    (SID,"0",TOKEN,"remote_port_invalid"),
    (SID,"443/",TOKEN,"remote_port_invalid"),
    (SID,"65536",TOKEN,"remote_port_invalid"),
    (SID,"8000","bad\nHeader","remote_token_invalid"),
    (SID,"8000","","remote_token_invalid"),
])
def test_bad_inputs_do_not_touch_sql_or_network(monkeypatch,sid,port,token,why):
    monkeypatch.setattr(remote.pyodbc,"drivers",lambda:pytest.fail("driver"))
    r=remote.probe_remote_report_job(sqlcfg(),schedule_id=sid,api_port=port,read_token=token)
    assert (r.status,r.reason)==("SKIP",why)


def test_redirect_auth_and_size_unverified(monkeypatch):
    for rsp,reason in [
        (Response(status=302),"remote_http_unverified"),
        (Response(status=401),"remote_http_unverified"),
        (Response(status=403),"remote_http_unverified"),
        (Response(headers={"Content-Type":"text/html"}),"remote_response_invalid"),
        (Response(headers={"Content-Type":"application/json",
                           "Content-Length":"9999999"}),"remote_response_oversized"),
    ]:
        r,client,_=check(monkeypatch,rsp)
        assert (r.status,r.reason)==("SKIP",reason)
        assert client.response.closed


def test_oversized_stream_cannot_be_accepted(monkeypatch):
    body=payload()
    body["other"]="z"*(remote.MAX_RESPONSE_BYTES+5)
    r,client,_=check(monkeypatch,Response(body))
    assert (r.status,r.reason)==("SKIP","remote_response_oversized")
    assert client.response.closed


def test_exception_untrusted_secret_not_echoed(monkeypatch):
    fake_sql(monkeypatch)
    class Broken(Client):
        def get(self,*a,**k):
            raise remote.requests.Timeout("token "+TOKEN)
    r=remote.probe_remote_report_job(sqlcfg(),schedule_id=SID,api_port="8000",
                                     read_token=TOKEN,session=Broken())
    assert (r.status,r.reason)==("SKIP","remote_http_unverified")
    assert TOKEN not in json.dumps(r.__dict__)


@pytest.mark.parametrize("on,prior,expected", [
    ((False,)*9,"PASS","NOT_TESTED"),
    ((True,)*8+(False,),"PASS","NOT_TESTED"),
    ((True,)*9,"SKIP","SKIP"),
    ((True,)*9,"PASS","PASS"),
])
def test_matrix_requires_nine_optins_and_actual_docx_pass(monkeypatch,on,prior,expected):
    calls=[]
    def provider(*a,**k):
        calls.append(k)
        return SimpleNamespace(check_id="REPORT-LIVE-01",
          probe="report-job-loopback-get",
          aspect="same_persisted_item_authenticated_remote_status_only",
          status="PASS",reason="remote_completed_attested",
          executed=True,evidence={"remote_job_completed_observed":True})
    monkeypatch.setattr(matrix,"probe_remote_report_job",provider)
    row=matrix._report_live_check(
        probe_network=on[0],probe_sql_read=on[1],
        probe_worker_identities=on[2],probe_schedule_claim=on[3],
        probe_schedule_link=on[4],probe_handoff_ack=on[5],
        probe_report_checkpoint=on[6],probe_docx_bytes=on[7],
        probe_report_live=on[8],docx_status=prior,sql_config=sqlcfg(),
        schedule_id=SID,lease_schema=None,api_port="8000",read_token=TOKEN)
    assert row["status"]==expected
    assert bool(calls)==(expected=="PASS")
    assert row["depends_on"]==["SQL-READ","DOCX-BYTES"]


def test_matrix_does_not_accept_forged_success(monkeypatch):
    monkeypatch.setattr(matrix,"probe_remote_report_job",lambda *a,**k:
      SimpleNamespace(check_id="REPORT-LIVE-01",probe="report-job-loopback-get",
       aspect="same_persisted_item_authenticated_remote_status_only",
       executed=False,status="PASS",reason="remote_completed_attested",
       evidence={"remote_job_completed_observed":True,"secret":TOKEN}))
    row=matrix._report_live_check(
        probe_network=True,probe_sql_read=True,probe_worker_identities=True,
        probe_schedule_claim=True,probe_schedule_link=True,
        probe_handoff_ack=True,probe_report_checkpoint=True,
        probe_docx_bytes=True,probe_report_live=True,docx_status="PASS",
        sql_config=sqlcfg(),schedule_id=SID,lease_schema=None,
        api_port="8000",read_token=TOKEN)
    assert (row["status"],row["reason"])==("SKIP","unexpected_probe_result")
    assert TOKEN not in json.dumps(row)
