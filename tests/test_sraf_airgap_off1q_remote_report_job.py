"""OFF-1Q: real deadline/framing logic with fake fd-level local socket."""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1q_remote_report_job as remote
from tools import sraf_airgap_off1d_readiness_matrix as matrix

SID = "sch_" + "a" * 32
JOB = "rpt_" + "b" * 32
SUB = "rhsub_" + "c" * 48
TOKEN = "KEEP_SECRET_BEARER"


def sqlcfg():
    return {"SRAF_OFF1G_SQL_HOST": "10.2.3.4",
            "SRAF_OFF1G_SQL_PORT": "1433",
            "SRAF_OFF1G_SQL_DATABASE": "control",
            "SRAF_OFF1G_SQL_USER": "readonly",
            "SRAF_OFF1G_SQL_PASSWORD": "HIDDEN_PASSWORD"}


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
    monkeypatch.setattr(remote.pyodbc, "connect", lambda *a, **kw: DB(rows, calls))
    return calls


def payload(job=JOB, sub=SUB, status="completed"):
    return {"job_id": job, "status": status,
            "metadata": {"submission_id": sub, "workflow_id": "report_v1"}}


def frame(body=None, *, status="200 OK", content_type="application/json",
          extra_headers="", declared_length=None):
    data = json.dumps(payload() if body is None else body).encode()
    length = len(data) if declared_length is None else declared_length
    return (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {length}\r\n"
        f"{extra_headers}\r\n"
    ).encode("ascii") + data


class FakeSocket:
    def __init__(self, parts, *, advance=None):
        self.parts = list(parts)
        self.advance = advance
        self.closed = False
        self.sent = b""
        self.address = None
        self.timeouts = []
    def settimeout(self, value):
        self.timeouts.append(value)
    def connect(self, address):
        self.address = address
    def sendall(self, data):
        self.sent += data
    def recv(self, length):
        if self.advance:
            self.advance()
        if not self.parts:
            return b""
        chunk = self.parts.pop(0)
        if len(chunk) > length:
            self.parts.insert(0, chunk[length:])
            chunk = chunk[:length]
        return chunk
    def close(self):
        self.closed = True


def fake_sock(monkeypatch, parts, advance=None):
    holder = []
    def build(family, kind):
        assert (family, kind) == (socket.AF_INET, socket.SOCK_STREAM)
        sock = FakeSocket(parts, advance=advance)
        holder.append(sock)
        return sock
    monkeypatch.setattr(remote.socket, "socket", build)
    return holder


def probe(monkeypatch, reply=None):
    calls = fake_sql(monkeypatch)
    sockets = fake_sock(monkeypatch, [frame() if reply is None else reply])
    result = remote.probe_remote_report_job(
        sqlcfg(), schedule_id=SID, api_port="8000", read_token=TOKEN)
    return result, calls, sockets[0]


def test_real_socket_request_shape_and_redaction(monkeypatch):
    r, calls, sock = probe(monkeypatch)
    assert (r.status, r.reason, r.evidence) == (
        "PASS", "remote_completed_attested",
        {"remote_job_completed_observed": True})
    assert calls[0][1] == (SID,)
    assert sock.address == ("127.0.0.1", 8000)
    assert sock.sent.startswith(b"GET /v1/report/jobs/" + JOB.encode() + b" HTTP/1.1\r\n")
    assert b"Authorization: Bearer " + TOKEN.encode() in sock.sent
    assert b"Connection: close" in sock.sent
    assert sock.closed
    for secret in (TOKEN, JOB, SUB, SID, "HIDDEN_PASSWORD"):
        assert secret not in json.dumps(r.__dict__)


@pytest.mark.parametrize("body,status,reason", [
    (payload(job="rpt_"+"d"*32), "FAIL", "remote_job_identity_mismatch"),
    (payload(sub="rhsub_"+"d"*48), "FAIL", "remote_submission_mismatch"),
    (payload(status="failed"), "FAIL", "remote_state_disagrees"),
    (payload(status="interrupted"), "FAIL", "remote_state_disagrees"),
    (payload(status="running"), "SKIP", "remote_still_in_progress"),
    (payload(status="queued"), "SKIP", "remote_still_in_progress"),
    (payload(status="unknown"), "SKIP", "remote_response_invalid"),
    ({"job_id": JOB, "status": "completed"}, "FAIL", "remote_submission_mismatch"),
])
def test_live_status_must_match_same_submission(monkeypatch, body, status, reason):
    r, _, sock = probe(monkeypatch, frame(body))
    assert (r.status, r.reason) == (status, reason)
    assert sock.closed


@pytest.mark.parametrize("rows,reason", [
    ((), "remote_reference_absent"),
    (((JOB,),), "remote_reference_invalid"),
    ((("bad/path", SUB),), "remote_reference_invalid"),
    (((JOB, "wrong"),), "remote_reference_invalid"),
    (((JOB, SUB), (JOB, SUB)), "remote_reference_ambiguous"),
])
def test_invalid_sql_reference_never_opens_socket(monkeypatch, rows, reason):
    fake_sql(monkeypatch, rows)
    monkeypatch.setattr(remote.socket, "socket",
                        lambda *a: pytest.fail("network opened"))
    r = remote.probe_remote_report_job(sqlcfg(), schedule_id=SID,
                                       api_port="8000", read_token=TOKEN)
    assert (r.status, r.reason) == ("SKIP", reason)


@pytest.mark.parametrize("sid,port,token,reason", [
    (None, "8000", TOKEN, "remote_schedule_id_invalid"),
    ("sch_"+"A"*32, "8000", TOKEN, "remote_schedule_id_invalid"),
    (SID, "0", TOKEN, "remote_port_invalid"),
    (SID, "65536", TOKEN, "remote_port_invalid"),
    (SID, "8000/", TOKEN, "remote_port_invalid"),
    (SID, "8000", "", "remote_token_invalid"),
    (SID, "8000", "bad\r\nHost: evil", "remote_token_invalid"),
])
def test_invalid_inputs_no_sql_or_http(monkeypatch, sid, port, token, reason):
    monkeypatch.setattr(remote.pyodbc, "drivers", lambda: pytest.fail("odbc"))
    r = remote.probe_remote_report_job(sqlcfg(), schedule_id=sid,
                                       api_port=port, read_token=token)
    assert (r.status, r.reason) == ("SKIP", reason)


@pytest.mark.parametrize("response", [
    frame(status="302 Found", extra_headers="Location: http://attacker/\r\n"),
    frame(status="401 Unauthorized"),
    frame(content_type="text/html"),
    frame(extra_headers="Transfer-Encoding: chunked\r\n"),
    frame(extra_headers="Content-Encoding: gzip\r\n"),
    frame(extra_headers="Content-Length: 100\r\n"),
    frame(declared_length=9000),
    frame(declared_length=3),
])
def test_unsafe_headers_and_redirects_cannot_pass(monkeypatch, response):
    r, _, sock = probe(monkeypatch, response)
    assert r.status == "SKIP"
    assert sock.closed


def test_absolute_total_deadline_blocks_trickling_responses(monkeypatch):
    fake_sql(monkeypatch)
    body = frame()
    header_end = body.index(b"\r\n\r\n")+4
    parts = [body[:header_end]] + [body[i:i+1] for i in range(header_end,len(body))]
    now = [100.0]
    monkeypatch.setattr(remote.time, "monotonic", lambda: now[0])
    def advance(): now[0] += 0.75
    sockets = fake_sock(monkeypatch, parts, advance=advance)
    r = remote.probe_remote_report_job(sqlcfg(),schedule_id=SID,
                                       api_port="8000",read_token=TOKEN)
    assert (r.status,r.reason)==("SKIP","remote_http_deadline")
    assert sockets[0].closed
    assert now[0] < 105.0  # never wait through a full trickled JSON body


def test_trickle_headers_deadline(monkeypatch):
    fake_sql(monkeypatch)
    now=[5.0]
    monkeypatch.setattr(remote.time,"monotonic",lambda:now[0])
    sockets=fake_sock(monkeypatch,[b"HTTP/",b"1.1 ",b"200 ",frame()[13:]],
                      advance=lambda: now.__setitem__(0,now[0]+1.1))
    r=remote.probe_remote_report_job(sqlcfg(),schedule_id=SID,
                                     api_port="8000",read_token=TOKEN)
    assert (r.status,r.reason)==("SKIP","remote_http_deadline")
    assert sockets[0].closed


def test_matrix_only_after_real_docx_pass(monkeypatch):
    calls=[]
    def fn(*a, **kw):
        calls.append(kw)
        return SimpleNamespace(check_id="REPORT-LIVE-01",
           probe="report-job-loopback-get",
           aspect="same_persisted_item_authenticated_remote_status_only",
           status="PASS", reason="remote_completed_attested",
           executed=True, evidence={"remote_job_completed_observed":True})
    monkeypatch.setattr(matrix, "probe_remote_report_job", fn)
    base = dict(probe_network=True,probe_sql_read=True,
        probe_worker_identities=True,probe_schedule_claim=True,
        probe_schedule_link=True,probe_handoff_ack=True,
        probe_report_checkpoint=True,probe_docx_bytes=True,
        probe_report_live=True,docx_status="PASS",sql_config=sqlcfg(),
        schedule_id=SID,lease_schema=None,api_port="8000",read_token=TOKEN)
    for delta,expected in [({"probe_report_live":False},"NOT_TESTED"),
                           ({"docx_status":"SKIP"},"SKIP"),
                           ({}, "PASS")]:
        result=matrix._report_live_check(**(base|delta))
        assert result["status"]==expected
    assert len(calls)==1
    assert result["depends_on"]==["SQL-READ","DOCX-BYTES"]


def test_matrix_rejects_forged_positive(monkeypatch):
    monkeypatch.setattr(matrix,"probe_remote_report_job",lambda *a,**k:
       SimpleNamespace(check_id="REPORT-LIVE-01",
       probe="report-job-loopback-get",
       aspect="same_persisted_item_authenticated_remote_status_only",
       status="PASS",reason="remote_completed_attested",executed=False,
       evidence={"remote_job_completed_observed":True,"secret":TOKEN}))
    result=matrix._report_live_check(
        probe_network=True,probe_sql_read=True,
        probe_worker_identities=True,probe_schedule_claim=True,
        probe_schedule_link=True,probe_handoff_ack=True,
        probe_report_checkpoint=True,probe_docx_bytes=True,
        probe_report_live=True,docx_status="PASS",sql_config=sqlcfg(),
        schedule_id=SID,lease_schema=None,api_port="8000",read_token=TOKEN)
    assert result["status"]=="SKIP"
    assert TOKEN not in json.dumps(result)
