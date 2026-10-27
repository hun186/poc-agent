"""OFF-1S: Linux listener PID/identity checks and authenticated GET protection."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1s_api_listener as listener
from tools import sraf_airgap_off1q_remote_report_job as remote
from tools import sraf_airgap_off1d_readiness_matrix as matrix

PID = 12345
PORT = 9002
TICK = "1234567"
INODE = "777777"
JOB = "rpt_" + "a" * 32
SUB = "rhsub_" + "b" * 48
TOKEN = "SECRET_BEARER_DO_NOT_LOG"
PROOF = listener.ListenerProof(PID, TICK, PORT, INODE)


def test_identity_file_shape_owner_and_nofollow(tmp_path):
    path = tmp_path / listener.IDENTITY_NAME
    path.write_text(f"api_pid={PID}\napi_start_time={TICK}\nport={PORT}\n")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert listener._identity(fd, PORT) == (PID, TICK)
        assert listener._identity(fd, PORT + 1) is None
        path.write_text(f"api_pid={PID}\napi_pid={PID}\nport={PORT}\n")
        assert listener._identity(fd, PORT) is None
        path.unlink()
        path.symlink_to(tmp_path/"other")
        assert listener._identity(fd, PORT) is None
        path.unlink()
        path.write_bytes(b"api_pid=12\napi_start_time=123\nport=9002\nX"*200)
        assert listener._identity(fd, PORT) is None
    finally:
        os.close(fd)


def test_start_time_parser_with_spaces_and_parentheses(monkeypatch):
    start = b"1234567"
    # fields after comm start at field 3; field22 is position 19.
    fields = [b"S"] + [b"1"] * 18 + [start] + [b"0"] * 14
    raw = b"12345 (api worker ) ) " + b" ".join(fields)
    monkeypatch.setattr(listener, "_bounded", lambda p, n: raw)
    assert listener._start_tick(PID) == TICK
    fields[0] = b"Z"
    monkeypatch.setattr(listener, "_bounded",
                        lambda p,n: b"12345 (api) " + b" ".join(fields))
    assert listener._start_tick(PID) is None


def test_expected_process_binds_cwd_euid_start_and_exact_argv(monkeypatch, tmp_path):
    root_stat = os.stat(tmp_path)
    monkeypatch.setattr(listener, "_start_tick", lambda p: TICK)
    original_stat = listener.os.stat
    monkeypatch.setattr(listener.os, "stat",
        lambda path, *a, **k: root_stat if str(path).endswith("/cwd")
        else original_stat(path, *a, **k))
    status = b"Name:\tuvicorn\nUid:\t1000\t" + str(os.geteuid()).encode() + b"\t1000\t1000\n"
    cmd = b"uvicorn\x00api.main:app\x00--host\x000.0.0.0\x00--port\x009002\x00"
    monkeypatch.setattr(listener, "_bounded", lambda p, n:
        status if str(p).endswith("/status") else cmd)
    assert listener._same_process(PID, TICK, root_stat, PORT)
    monkeypatch.setattr(listener, "_bounded", lambda p, n:
        status if str(p).endswith("/status")
        else b"uvicorn\x00other.main:app\x00--host\x000.0.0.0\x00--port\x009002\x00")
    assert not listener._same_process(PID, TICK, root_stat, PORT)


def test_attest_requires_same_live_record_socket_and_process(tmp_path,monkeypatch):
    root=tmp_path/"app";root.mkdir()
    identity=root/listener.IDENTITY_NAME
    identity.write_text(f"api_pid={PID}\napi_start_time={TICK}\nport={PORT}\n")
    monkeypatch.setattr(listener, "_same_process", lambda *a: True)
    monkeypatch.setattr(listener, "_listener_inode", lambda p: INODE)
    monkeypatch.setattr(listener, "_owns_socket",lambda p,i: True)
    monkeypatch.setattr(listener, "_exclusive_socket_owner", lambda p,i: True)
    got=listener.attest_api_listener(root, str(PORT))
    assert got==PROOF
    assert listener.listener_still_expected(root,got)
    monkeypatch.setattr(listener, "_owns_socket",lambda p,i: False)
    assert listener.attest_api_listener(root, str(PORT)) is None
    assert not listener.listener_still_expected(root,got)
    monkeypatch.setattr(listener, "_owns_socket",lambda p,i: True)
    identity.write_text(f"api_pid={PID+1}\napi_start_time={TICK}\nport={PORT}\n")
    assert listener.attest_api_listener(root, str(PORT)) != PROOF


def test_listener_inode_accepts_exact_loopback_or_wildcard_but_refuses_ipv6(monkeypatch):
    tcp=b"  sl local_address rem_address st txrx tr tm retr uid timeout inode\n" \
        b"  0: 00000000:232A 00000000:0000 0A 0 0 0 0 0 777777\n"
    ipv6=b"  sl local_address rem_address st\n"
    monkeypatch.setattr(listener,"_bounded",
        lambda p,n: tcp if str(p).endswith("/net/tcp") else ipv6)
    assert listener._listener_inode(PORT)==INODE
    monkeypatch.setattr(listener,"_bounded",lambda p,n:
        tcp if str(p).endswith("/net/tcp") else
        ipv6+b"  1: 00000000000000000000000000000000:232A 0000 0A\n")
    assert listener._listener_inode(PORT) is None


class FakeSocket:
    def __init__(self, payload):
        self.payload=payload
        self.sent=b""
        self.closed=False
        self.connected=False
    def settimeout(self,value): self.timeout=value
    def connect(self,addr):
        assert addr==("127.0.0.1",PORT)
        self.connected=True
    def sendall(self,data): self.sent+=data
    def recv(self,n):
        out=self.payload[:n]
        self.payload=self.payload[n:]
        return out
    def close(self): self.closed=True


def response():
    body=json.dumps({"job_id":JOB,"status":"completed",
       "metadata":{"submission_id":SUB,"workflow_id":"report_v1"}}).encode()
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            +str(len(body)).encode()+b"\r\n\r\n"+body)


def test_denied_listener_never_transmits_bearer(monkeypatch):
    fake=FakeSocket(response())
    monkeypatch.setattr(remote.socket,"socket",lambda *a: fake)
    assert remote._remote_status(PORT,TOKEN,JOB,SUB,listener_guard=lambda: False)==(
        "SKIP","remote_listener_unverified")
    assert fake.connected and fake.sent==b"" and fake.closed


def test_recheck_after_response_prevents_forged_pass(monkeypatch):
    fake=FakeSocket(response())
    monkeypatch.setattr(remote.socket,"socket",lambda *a: fake)
    calls=[]
    def guard():
        calls.append(True)
        return len(calls)==1
    assert remote._remote_status(PORT,TOKEN,JOB,SUB,listener_guard=guard)==(
        "SKIP","remote_listener_unverified")
    assert len(calls)==2 and TOKEN.encode() in fake.sent and fake.closed


def test_good_guard_before_token_and_after_body(monkeypatch):
    fake=FakeSocket(response())
    monkeypatch.setattr(remote.socket,"socket",lambda *a: fake)
    calls=[]
    def guard():
        calls.append(len(fake.sent))
        return True
    assert remote._remote_status(PORT,TOKEN,JOB,SUB,listener_guard=guard)==(
        "PASS","remote_completed_attested")
    assert calls[0]==0 and len(calls)==2 and fake.closed


def test_matrix_eleventh_optin_and_fail_closed_without_token(monkeypatch):
    monkeypatch.setattr(matrix,"PROJECT_ROOT",Path("/tmp/nonsecret-app"))
    live_calls=[]
    monkeypatch.setattr(matrix, "probe_remote_report_job",lambda *a,**k:
        live_calls.append(k) or pytest.fail("bearer request should be blocked"))
    row,proof=matrix._api_listener_check(flags=(False,)*11,
                                          docx_status="PASS",api_port=str(PORT))
    assert row["status"]=="NOT_TESTED" and proof is None
    row,proof=matrix._api_listener_check(flags=(True,)*11,
                                          docx_status="SKIP",api_port=str(PORT))
    assert row["status"]=="SKIP" and proof is None
    monkeypatch.setattr(matrix,"attest_api_listener",lambda *a: None)
    row,proof=matrix._api_listener_check(flags=(True,)*11,
                                          docx_status="PASS",api_port=str(PORT))
    assert row["status"]=="SKIP" and proof is None
    base=dict(probe_network=True,probe_sql_read=True,
              probe_worker_identities=True,probe_schedule_claim=True,
              probe_schedule_link=True,probe_handoff_ack=True,
              probe_report_checkpoint=True,probe_docx_bytes=True,
              probe_report_live=True,docx_status="PASS",
              sql_config={},schedule_id="sch_"+"a"*32,lease_schema=None,
              api_port=str(PORT),read_token=TOKEN)
    res=matrix._report_live_check(**base,listener_required=True,listener_proof=None)
    assert (res["status"],res["reason"])==("SKIP","remote_listener_unverified")
    assert live_calls==[]
    assert TOKEN not in json.dumps(res)


def test_matrix_propagates_guard_only_when_opted_in(monkeypatch):
    monkeypatch.setattr(matrix,"probe_remote_report_job",
       lambda *a,**k: SimpleNamespace(check_id="REPORT-LIVE-01",
         probe="report-job-loopback-get",
         aspect="same_persisted_item_authenticated_remote_status_only",
         status="PASS",reason="remote_completed_attested",executed=True,
         evidence={"remote_job_completed_observed":True}))
    args=dict(probe_network=True,probe_sql_read=True,
              probe_worker_identities=True,probe_schedule_claim=True,
              probe_schedule_link=True,probe_handoff_ack=True,
              probe_report_checkpoint=True,probe_docx_bytes=True,
              probe_report_live=True,docx_status="PASS",
              sql_config={},schedule_id="sch_"+"a"*32,lease_schema=None,
              api_port=str(PORT),read_token=TOKEN)
    assert matrix._report_live_check(**args)["status"]=="PASS"
    assert matrix._report_live_check(**args,listener_required=True,
                                    listener_proof=PROOF)["status"]=="PASS"


def test_launcher_python_console_script_and_runtime_title(monkeypatch, tmp_path):
    """Exercise real Linux shebang argv shape and sra_api/core/proctitle.py."""
    root_stat = os.stat(tmp_path)
    monkeypatch.setattr(listener, "_start_tick", lambda p: TICK)
    original_stat = listener.os.stat
    monkeypatch.setattr(listener.os, "stat",
        lambda path, *a, **k: root_stat if str(path).endswith("/cwd")
        else original_stat(path, *a, **k))
    status = (b"Name:\tpython3\nUid:\t1000\t"
              + str(os.geteuid()).encode() + b"\t1000\t1000\n")
    payload = {"command": (b"/usr/local/bin/python3.11\x00"
              b"/usr/local/bin/uvicorn\x00api.main:app\x00"
              b"--host\x000.0.0.0\x00--port\x009002\x00")}
    monkeypatch.setattr(listener, "_bounded", lambda path, limit:
        status if str(path).endswith("/status") else payload["command"])
    assert listener._same_process(PID, TICK, root_stat, PORT)

    payload["command"] = (b"/usr/bin/python3\x00/usr/bin/uvicorn\x00"
                          b"other.main:app\x00--host\x000.0.0.0\x00--port\x009002\x00")
    assert not listener._same_process(PID, TICK, root_stat, PORT)
    payload["command"] = (b"/usr/bin/python3\x00-m\x00uvicorn\x00"
                          b"api.main:app\x00--host\x000.0.0.0\x00--port\x009002\x00")
    assert not listener._same_process(PID, TICK, root_stat, PORT)

    hostname = listener.socket.gethostname()
    title = f"SRA-API | port={PORT} | gpt-oss | pid={PID} | {hostname}"
    payload["command"] = title.encode() + b"\x00\x00\x00"
    assert listener._same_process(PID, TICK, root_stat, PORT)
    payload["command"] = (f"SRA-API | port={PORT} | pid={PID} | {hostname}"
                          ).encode() + b"\x00"
    assert listener._same_process(PID, TICK, root_stat, PORT)
    payload["command"] = (f"SRA-API | port={PORT} | pid={PID+1} | {hostname}"
                          ).encode() + b"\x00"
    assert not listener._same_process(PID, TICK, root_stat, PORT)
    payload["command"] = title.encode() + b"\x00other\x00"
    assert not listener._same_process(PID, TICK, root_stat, PORT)


def test_exclusive_socket_owner_rejects_fork_shared_and_unreadable(monkeypatch):
    """A child holding the *same* listening inode cannot receive a bearer."""
    from types import SimpleNamespace

    other_pid = PID + 1
    owners = {
        PID: {"3": f"socket:[{INODE}]"},
        other_pid: {"4": f"socket:[{INODE}]"},
    }
    blocked = set()

    class FakeDir:
        def __init__(self, items):
            self.items = items
        def __enter__(self):
            return iter(self.items)
        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_scandir(path):
        if path == "/proc":
            return FakeDir([SimpleNamespace(name=str(p)) for p in owners])
        pid = int(str(path).split("/")[2])
        if pid in blocked:
            raise PermissionError("unverifiable fd table")
        return FakeDir([SimpleNamespace(name=fd, path=f"/proc/{pid}/fd/{fd}")
                        for fd in owners[pid]])
    def fake_readlink(path):
        pid, fd = int(path.split("/")[2]), path.split("/")[-1]
        return owners[pid][fd]

    monkeypatch.setattr(listener.os, "scandir", fake_scandir)
    monkeypatch.setattr(listener.os, "readlink", fake_readlink)
    assert not listener._exclusive_socket_owner(PID, INODE)
    owners[other_pid]["4"] = "socket:[different]"
    assert listener._exclusive_socket_owner(PID, INODE)
    blocked.add(other_pid)
    assert not listener._exclusive_socket_owner(PID, INODE)
    blocked.clear()
    del owners[PID]["3"]
    assert not listener._exclusive_socket_owner(PID, INODE)


def test_attestation_refuses_shared_socket_before_bearer(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / listener.IDENTITY_NAME).write_text(
        f"api_pid={PID}\napi_start_time={TICK}\nport={PORT}\n")
    monkeypatch.setattr(listener, "_same_process", lambda *a: True)
    monkeypatch.setattr(listener, "_listener_inode", lambda *a: INODE)
    monkeypatch.setattr(listener, "_owns_socket", lambda *a: True)
    monkeypatch.setattr(listener, "_exclusive_socket_owner", lambda *a: False)
    assert listener.attest_api_listener(root, str(PORT)) is None
    monkeypatch.setattr(matrix, "PROJECT_ROOT", root)
    row, proof = matrix._api_listener_check(
        flags=(True,) * 11, docx_status="PASS", api_port=str(PORT))
    assert row["status"] == "SKIP"
    assert row["reason"] == "api_listener_unverified"
    assert proof is None


@pytest.mark.skipif(os.name != "posix" or not Path("/proc/self/stat").exists(),
                    reason="Linux procfs process verification only")
def test_actual_linux_python_shebang_uvicorn_process(tmp_path):
    """Read real /proc/pid/{stat,status,cwd,cmdline}, not fabricated argv bytes."""
    import subprocess
    import sys
    import time

    script = tmp_path / "uvicorn"
    script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
    script.chmod(0o700)
    proc = subprocess.Popen(
        [str(script), "api.main:app", "--host", "0.0.0.0",
         "--port", str(PORT)],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        valid = False
        root_stat = os.stat(tmp_path)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            start_tick = listener._start_tick(proc.pid)
            if (start_tick is not None
                    and listener._same_process(
                        proc.pid, start_tick, root_stat, PORT)):
                valid = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.025)
        assert valid, "launcher-style Python shebang process must be recognized"
        assert not listener._same_process(proc.pid, start_tick, root_stat, PORT + 1)
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=3)
