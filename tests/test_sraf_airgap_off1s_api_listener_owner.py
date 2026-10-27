"""OFF-1S Linux API listener PID and token-bearing HTTP guard regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest

from tools import sraf_airgap_off1s_api_listener_owner as owner
from tools import sraf_airgap_off1q_remote_report_job as q
from tools import sraf_airgap_off1r_same_item_chain as r
from tools import sraf_airgap_off1d_readiness_matrix as matrix

PID = 43210
START = "778899"
PORT = "9002"
INODE = "987654"
JOB = "rpt_" + "b"*32
SUB = "rhsub_" + "c"*48
SID = "sch_" + "a"*32
ITEM = "rit_" + "e"*32
BATCH = "brun_" + "f"*32
TOKEN = "HIDDEN_OP_READ_TOKEN"
PASSWORD = "HIDDEN_SQL_PASSWORD"


def config():
    return {"SRAF_OFF1G_SQL_HOST": "10.1.2.3",
            "SRAF_OFF1G_SQL_PORT": "1433",
            "SRAF_OFF1G_SQL_DATABASE": "sraf",
            "SRAF_OFF1G_SQL_USER": "read",
            "SRAF_OFF1G_SQL_PASSWORD": PASSWORD}


def fake_proc(tmp_path, monkeypatch):
    root = tmp_path / "deployment"
    root.mkdir()
    (root / owner.IDENTITY).write_text(
        f"api_pid={PID}\napi_start_time={START}\nport={PORT}\n")
    (root / owner.IDENTITY).chmod(0o600)
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    (proc / str(PID) / "fd").mkdir(parents=True)
    (proc / str(PID) / "stat").write_text(
        f"{PID} (uvicorn) S " + " ".join(["0"]*18 + [START] + ["0"]*3))
    (proc / str(PID) / "status").write_text(
        "Name:\tuvicorn\nUid:\t" + " ".join([str(os.geteuid())]*4) + "\n")
    (proc / str(PID) / "cmdline").write_bytes(
        f"/usr/bin/python3\0/venv/bin/uvicorn\0api.main:app\0--host\x000.0.0.0\0--port\0{PORT}\0".encode())
    (proc / str(PID) / "cwd").symlink_to(root, target_is_directory=True)
    (proc / str(PID) / "exe").symlink_to(sys.executable)
    (proc / str(PID) / "fd" / "7").symlink_to(f"socket:[{INODE}]")
    (proc / "net" / "tcp").write_text(
        "sl local_address rem_address st tx rx tr tm retrnsmt uid timeout inode\n"
        f"0: 00000000:{int(PORT):04X} 00000000:0000 0A 0 0 0 0 0 {INODE} 0\n")
    (proc / "net" / "tcp6").write_text(
        "sl local_address rem_address st tx rx tr tm retrnsmt uid timeout inode\n")
    monkeypatch.setattr(owner, "PROC", proc)
    return root, proc


def test_launcher_identity_owned_listener_pass_and_private(tmp_path, monkeypatch):
    root, _ = fake_proc(tmp_path, monkeypatch)
    assert owner._record(root, int(PORT)) == (PID, START)
    assert owner._process(root, PID, START, int(PORT))
    assert owner._listener_inode(int(PORT)) == INODE
    assert owner._owns_socket(PID, INODE)
    result = owner.probe_api_listener_owner(root, PORT)
    assert result.status == "PASS"
    assert result.reason == "api_owner_observed"
    assert result.evidence == {"api_listener_owner_observed": True}
    assert owner.verified_listener_binding(root, PORT) == (PID, START, INODE)
    for sensitive in (str(root), str(PID), INODE, START, TOKEN):
        assert sensitive not in json.dumps(result.__dict__)


@pytest.mark.parametrize("case", [
    "bad_mode", "bad_pid", "bad_start", "symlink_file",
    "wrong_uid", "wrong_cwd", "wrong_route", "wrong_port",
    "wrong_socket", "second_listener", "ipv6_conflict", "zombie",
])
def test_fail_closed_without_matching_launcher_and_tcp(
        tmp_path, monkeypatch, case):
    root, proc = fake_proc(tmp_path, monkeypatch)
    record = root / owner.IDENTITY
    pidproc = proc / str(PID)
    if case == "bad_mode":
        record.chmod(0o644)
    elif case == "bad_pid":
        record.write_text(f"api_pid=1\napi_start_time={START}\nport={PORT}\n")
    elif case == "bad_start":
        record.write_text(f"api_pid={PID}\napi_start_time=123\nport={PORT}\n")
    elif case == "symlink_file":
        record.rename(root / "saved")
        record.symlink_to(root / "saved")
    elif case == "wrong_uid":
        (pidproc / "status").write_text(
            f"Uid:\t{os.geteuid()}\t999999\t{os.geteuid()}\t{os.geteuid()}\n")
    elif case == "wrong_cwd":
        (pidproc / "cwd").unlink()
        (pidproc / "cwd").symlink_to(tmp_path, target_is_directory=True)
    elif case == "wrong_route":
        (pidproc / "cmdline").write_bytes(
            f"/usr/bin/python3\0/venv/bin/uvicorn\0evil:app\0--host\x000.0.0.0\0--port\0{PORT}\0".encode())
    elif case == "wrong_port":
        (pidproc / "cmdline").write_bytes(
            b"/usr/bin/python3\0/venv/bin/uvicorn\0api.main:app\0--host\x000.0.0.0\0--port\09999\0")
    elif case == "wrong_socket":
        (pidproc / "fd" / "7").unlink()
        (pidproc / "fd" / "7").symlink_to("socket:[222222]")
    elif case == "second_listener":
        with (proc / "net" / "tcp").open("a") as fp:
            fp.write(f"1: 0100007F:{int(PORT):04X} 00000000:0000 0A 0 0 0 0 0 11111 0\n")
    elif case == "ipv6_conflict":
        with (proc / "net" / "tcp6").open("a") as fp:
            fp.write(f"1: {'0'*32}:{int(PORT):04X} {'0'*32}:0000 0A 0 0 0 0 0 11111 0\n")
    elif case == "zombie":
        (pidproc / "stat").write_text(
            f"{PID} (uvicorn) Z " + " ".join(["0"]*18 + [START] + ["0"]*3))
    assert owner.verified_listener_binding(root, PORT) is None
    o = owner.probe_api_listener_owner(root, PORT)
    assert (o.status, o.reason) == ("SKIP", "api_owner_unverified")


def test_binding_changes_between_double_sample_skip(tmp_path, monkeypatch):
    root, proc = fake_proc(tmp_path, monkeypatch)
    base = owner._record
    calls = [0]
    def swapped(*args):
        calls[0] += 1
        if calls[0] == 2:
            (proc / "net" / "tcp").write_text("header\n")
        return base(*args)
    monkeypatch.setattr(owner, "_record", swapped)
    assert owner.verified_listener_binding(root, PORT) is None


def test_no_network_or_pid_discovery_when_default(monkeypatch):
    monkeypatch.setattr(matrix, "probe_api_listener_owner",
                        lambda *a: pytest.fail("unconsented process probe"))
    row = matrix._api_owner_check(
        probe_network=True, probe_api_owner=False,
        api_port=PORT, project_root=Path("/tmp"))
    assert (row["status"], row["reason"]) == (
        "NOT_TESTED", "api_owner_not_requested")


def test_api_owner_matrix_positive_must_match_exact_evidence(monkeypatch):
    def good(*args):
        return SimpleNamespace(check_id="API-OWNER-01",
            probe="sraf-api-listener-owner",
            aspect="launcher_record_process_and_tcp_socket_partial_only",
            status="PASS", reason="api_owner_observed",
            executed=True, evidence={"api_listener_owner_observed": True})
    monkeypatch.setattr(matrix, "probe_api_listener_owner", good)
    row = matrix._api_owner_check(
        probe_network=True, probe_api_owner=True,
        api_port=PORT, project_root=Path("/tmp"))
    assert (row["status"], row["reason"]) == ("PASS", "api_owner_observed")
    monkeypatch.setattr(matrix, "probe_api_listener_owner",
        lambda *args: SimpleNamespace(**(good().__dict__ |
                  {"evidence":{"api_listener_owner_observed":True,"secret":TOKEN}})))
    spoof = matrix._api_owner_check(
        probe_network=True, probe_api_owner=True,
        api_port=PORT, project_root=Path("/tmp"))
    assert spoof["status"] == "SKIP" and TOKEN not in json.dumps(spoof)


def test_matrix_owner_failure_never_passes_bearer_to_report_probes(monkeypatch):
    monkeypatch.setattr(matrix, "probe_remote_report_job",
                        lambda *a,**k: pytest.fail("unexpected token-bearing GET"))
    base = dict(probe_network=True,probe_sql_read=True,
        probe_worker_identities=True,probe_schedule_claim=True,
        probe_schedule_link=True,probe_handoff_ack=True,
        probe_report_checkpoint=True,probe_docx_bytes=True,
        probe_report_live=True,docx_status="PASS",
        sql_config=config(),schedule_id=SID,lease_schema=None,
        api_port=PORT,read_token=TOKEN,
        probe_api_owner=True,api_owner_status="SKIP")
    row=matrix._report_live_check(**base)
    assert (row["status"],row["reason"])==("SKIP","api_owner_unverified")
    monkeypatch.setattr(matrix, "probe_single_item_chain",
                        lambda *a,**k: pytest.fail("unexpected token-bearing GET"))
    chain = matrix._report_chain_check(
        flags=(True,)*10,live_status="PASS",sql_config=config(),
        schedule_id=SID,lease_schema=None,artifact_root="/tmp/root",
        api_port=PORT,read_token=TOKEN,
        probe_api_owner=True,api_owner_status="SKIP")
    assert (chain["status"],chain["reason"])==("SKIP","api_owner_unverified")


def test_report_job_guard_rechecked_before_and_after_one_get(monkeypatch):
    monkeypatch.setattr(q.pyodbc,"drivers",lambda:[q.DRIVER])
    monkeypatch.setattr(q,"_sql_reference",lambda *a:(JOB,SUB))
    calls=[]
    def remote(port,token,job,submission):
        calls.append(("HTTP",job,submission))
        return "PASS","remote_completed_attested"
    monkeypatch.setattr(q,"_remote_status",remote)
    guards=[]
    def guard():
        guards.append("guard")
        return (PID,START,INODE)
    obs=q.probe_remote_report_job(config(),schedule_id=SID,
        api_port=PORT,read_token=TOKEN,listener_guard=guard)
    assert obs.status=="PASS" and len(guards)==2 and len(calls)==1
    assert TOKEN not in json.dumps(obs.__dict__)
    guards.clear();calls.clear()
    def absent():
        guards.append("guard")
        return None
    obs=q.probe_remote_report_job(config(),schedule_id=SID,
        api_port=PORT,read_token=TOKEN,listener_guard=absent)
    assert (obs.status,obs.reason)==("SKIP","api_owner_unverified")
    assert calls==[]
    snapshots=iter([(PID,START,INODE),(PID,"changed",INODE)])
    obs=q.probe_remote_report_job(config(),schedule_id=SID,
        api_port=PORT,read_token=TOKEN,listener_guard=lambda:next(snapshots))
    assert (obs.status,obs.reason)==("SKIP","api_owner_changed")


def test_same_item_chain_guard_fails_before_token_and_after_swap(tmp_path,monkeypatch):
    root=tmp_path/"root";root.mkdir()
    row=(BATCH,ITEM,ITEM+"/report.docx","a"*64,"b"*64,JOB,SUB)
    monkeypatch.setattr(r.pyodbc,"drivers",lambda:[r.DRIVER])
    monkeypatch.setattr(r,"_read_reference",lambda *a:row)
    monkeypatch.setattr(r,"output_root_fingerprint",lambda *a:"b"*64)
    monkeypatch.setattr(r,"_inspect_local_docx",lambda *a:"docx_local_bytes_match")
    called=[]
    monkeypatch.setattr(r,"_remote_status",
                        lambda *a:(called.append(a) or ("PASS","remote_completed_attested")))
    x=r.probe_single_item_chain(config(),schedule_id=SID,artifact_root=str(root),
        api_port=PORT,read_token=TOKEN,listener_guard=lambda:None)
    assert (x.status,x.reason)==("SKIP","api_owner_unverified")
    assert called==[]
    states=iter([(PID,START,INODE),(PID,START,"changed")])
    x=r.probe_single_item_chain(config(),schedule_id=SID,artifact_root=str(root),
        api_port=PORT,read_token=TOKEN,listener_guard=lambda:next(states))
    assert (x.status,x.reason)==("SKIP","api_owner_changed")
    assert len(called)==1
