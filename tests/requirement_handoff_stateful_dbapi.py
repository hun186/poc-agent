"""Stateful DB-API acceptance harness for the Phase 1C-B SQL transactions.

This deliberately interprets the small SQL vocabulary emitted by ScheduleStore.  It
keeps a private transaction copy and only exposes it on commit, which lets the
acceptance tests prove state (rather than merely assert SQL text).
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from requirement_scheduler.execution import build_execution_manifest
from requirement_scheduler.handoff import prepared_handoff
from requirement_scheduler.lease import CONTROL_DOMAIN, LeaseProof

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
TOKEN = "a" * 64


def lease(owner="worker", token=TOKEN, generation=1, expires_at=None):
    return LeaseProof(CONTROL_DOMAIN, owner, token, generation,
                      expires_at or NOW + timedelta(minutes=5))


def initial_state(*, checkpoint=(None, None, None), item_state="handoff_pending",
                  remote_state=None, root=None, deadline=None):
    return {
        "now_values": [NOW, NOW],
        "lease": ["worker", TOKEN, 1, NOW + timedelta(minutes=5)],
        "run": {"batch_run_id": "run-1", "schedule_id": "schedule-1",
                "schedule_version_id": "sv-1", "snapshot_id": "snapshot-1",
                "root": root, "state": "handoff_pending", "success_count": 0,
                "failure_count": 0, "completed_at": None},
        "item": {"run_item_id": "item-1", "requirement_id": "requirement-1",
                 "requirement_version_id": "rv-1", "requirement_version_number": 2,
                 "state": item_state, "remote_state": remote_state,
                 "remote_job_id": None, "path": None, "digest": None,
                 "reconciled_at": None, "deadline": deadline or NOW + timedelta(hours=1),
                 "expired_before_handoff": 0, "completed_at": None},
        "other_items": [], "checkpoint": list(checkpoint), "submission": None,
        "audits": [], "locks": [], "commits": [], "rollbacks": [],
    }


class StatefulDatabase:
    def __init__(self, state=None, *, fail_at=None):
        self.state = deepcopy(state or initial_state())
        self.fail_at = fail_at
        self.executions = []
        self.connect_count = 0

    def open_named_connection(self, _name):
        self.connect_count += 1
        return Connection(self)


class Connection:
    def __init__(self, db):
        self.db = db
        self.working = deepcopy(db.state)
        self.closed = False

    def cursor(self): return Cursor(self)

    def commit(self):
        if self.db.fail_at == "commit": raise RuntimeError("injected:commit")
        self.working["commits"].append(deepcopy(self.working))
        self.db.state = self.working

    def rollback(self):
        self.db.state["rollbacks"].append(deepcopy(self.db.state))

    def close(self): self.closed = True


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.results = []
        self.rowcount = -1

    @property
    def s(self): return self.connection.working

    def fetchone(self): return self.results.pop(0) if self.results else None
    def fetchall(self): result, self.results = self.results, []; return result

    def _fail(self, marker):
        if self.connection.db.fail_at == marker: raise RuntimeError("injected:" + marker)

    def execute(self, sql, *p):
        normalized = " ".join(sql.split())
        self.connection.db.executions.append((normalized, p))
        self.results, self.rowcount = [], -1
        if "UPDLOCK" in normalized or "HOLDLOCK" in normalized:
            self.s["locks"].append(normalized)
        if normalized == "SELECT SYSUTCDATETIME()":
            values = self.s["now_values"]
            self.results = [(values.pop(0) if len(values) > 1 else values[0],)]
        elif "FROM [sra_schedule].[requirement_handoff_coordinator_leases]" in normalized:
            self.results = [tuple(self.s["lease"])]
        elif "SELECT TOP 1 i.run_item_id" in normalized:
            i, r = self.s["item"], self.s["run"]
            if i["state"] == "handoff_pending" and r["state"] in {"handoff_pending", "running"}:
                self.results = [(i["run_item_id"], r["batch_run_id"], r["schedule_id"],
                    r["schedule_version_id"], r["snapshot_id"], i["requirement_id"],
                    i["requirement_version_id"], i["requirement_version_number"],
                    "private requirement prompt", "approved-model", i["deadline"], r["root"], r["state"])]
        elif "SET execution_state='expired'" in normalized:
            self._fail("item_update")
            i = self.s["item"]
            self.rowcount = int(i["state"] == "handoff_pending")
            if self.rowcount: i.update(state="expired", expired_before_handoff=1, completed_at=p[0])
        elif "SET phase1a_output_root_fingerprint=?" in normalized:
            self._fail("root_bind")
            r = self.s["run"]; self.rowcount = int(r["root"] is None and r["state"] == p[3])
            if self.rowcount: r["root"] = p[0]
            self._fail("after_root_bind")
        elif "SELECT submission_id,workflow_id,semantic_manifest_json" in normalized and "JOIN" not in normalized:
            sub = self.s["submission"]
            self.results = [tuple(sub[k] for k in ("submission_id","workflow_id","manifest","fingerprint","session"))] if sub else []
        elif "INSERT INTO [sra_schedule].[requirement_handoff_submissions]" in normalized:
            self._fail("submission_insert")
            if self.s["submission"] is not None: raise RuntimeError("duplicate")
            self.s["submission"] = dict(submission_id=p[0], run_item_id=p[1], workflow_id=p[2],
                manifest=p[3], fingerprint=p[4], session=p[5])
            if self.connection.db.fail_at in {"duplicate_exact","duplicate_drift"}:
                if self.connection.db.fail_at == "duplicate_drift": self.s["submission"]["manifest"] += " "
                raise RuntimeError("23000", "2627 duplicate key")
            self.rowcount = 1; self._fail("after_submission_insert")
        elif "SET execution_state='submitting'" in normalized:
            self._fail("item_update")
            i=self.s["item"]; self.rowcount=int(i["state"] == "handoff_pending")
            if self.rowcount: i["state"]="submitting"
            self._fail("after_item_update")
        elif "SET state='running',handoff_started_at" in normalized:
            self.s["run"]["state"]="running"; self.rowcount=1
        elif "SELECT s.submission_id,s.workflow_id" in normalized:
            sub,i,r=self.s["submission"],self.s["item"],self.s["run"]
            if sub:
                self.results=[(sub["submission_id"],sub["workflow_id"],sub["manifest"],sub["fingerprint"],sub["session"],i["state"],i["remote_job_id"],r["batch_run_id"],r["schedule_id"],r["schedule_version_id"],r["root"])]
        elif "SET remote_job_id=?" in normalized:
            self._fail("remote_update")
            i=self.s["item"]; expected=p[4]
            self.rowcount=int(i["state"] == expected and (i["remote_job_id"] is None or i["remote_job_id"] == p[0]))
            if self.rowcount: i.update(remote_job_id=p[0], remote_state="pending", state="pending")
            self._fail("after_remote_update")
        elif "SET handed_off_at=" in normalized:
            self._fail("run_evidence"); self.s["run"]["handed_off_at"]=p[0]; self.rowcount=1
        elif "remote_completed_at=CASE" in normalized:
            self._fail("reconcile_update")
            i=self.s["item"]; self.rowcount=int(i["state"]==p[8])
            if self.rowcount:
                i.update(state=p[0],remote_state=p[1])
                if p[0] == "reconciling": i["remote_completed_at"]=p[5]
        elif "SET reconciled_at=?" in normalized:
            self.s["run"]["reconciled_at"]=p[0]; self.rowcount=1
        elif "SET artifact_relative_path=?" in normalized:
            self._fail("artifact_update")
            i=self.s["item"]
            self.rowcount=int(i["state"]=="reconciling" and i["remote_state"]=="completed")
            if self.rowcount: i.update(path=p[0],digest=p[1],reconciled_at=p[2])
        elif "SELECT i.batch_run_id,i.requirement_id" in normalized:
            i,r=self.s["item"],self.s["run"]
            self.results=[(r["batch_run_id"],i["requirement_id"],i["requirement_version_id"],i["requirement_version_number"],i["state"],i["remote_state"],i["path"],i["digest"],i["reconciled_at"],r["schedule_id"],r["schedule_version_id"],r["root"])]
        elif "SELECT submission_id FROM [sra_schedule].[requirement_handoff_submissions]" in normalized:
            self.results=[(self.s["submission"]["submission_id"],)] if self.s["submission"] else []
        elif "SELECT last_successful_requirement_version_id" in normalized:
            self.results=[tuple(self.s["checkpoint"])]
        elif "SET execution_state='completed'" in normalized:
            self._fail("item_update")
            i=self.s["item"]; self.rowcount=int(bool(i["state"]=="reconciling" and i["remote_state"]=="completed" and i["path"] and i["digest"] and i["reconciled_at"]))
            if self.rowcount: i.update(state="completed",completed_at=p[0])
            self._fail("after_item_update")
        elif "SET last_successful_requirement_version_id=?" in normalized:
            self._fail("checkpoint_update")
            self.s["checkpoint"]=[p[0],p[1],p[2]]; self.rowcount=1
            self._fail("after_checkpoint_update")
        elif "SELECT execution_state,COUNT(*)" in normalized:
            states=[self.s["item"]["state"]]+[x["state"] for x in self.s["other_items"] if x.get("selected",True)]
            self.results=[(state,states.count(state)) for state in sorted(set(states))]
        elif "SET success_count=?" in normalized:
            self._fail("run_update")
            r=self.s["run"]; r.update(success_count=p[0],failure_count=p[1],state=p[2],completed_at=(r["completed_at"] or p[4]) if p[3]==0 else None)
            self.rowcount=1; self._fail("after_run_update")
        elif "SET execution_state=?,error_code=?" in normalized:
            self._fail("item_update")
            i=self.s["item"]; self.rowcount=int(i["state"]==p[6])
            if self.rowcount: i.update(state=p[0],completed_at=p[3])
        elif "INSERT INTO [sra_schedule].[requirement_schedule_audit_outbox]" in normalized:
            self._fail("audit_insert")
            self.s["audits"].append({"event_id":p[0],"action":p[1],"actor":p[2],
                "schedule_id":p[3],"schedule_version_id":p[4],"batch_run_id":p[5],
                "payload":json.loads(p[6])}); self.rowcount=1
        else:
            # Updates irrelevant to the asserted domain snapshot (timestamps, etc.).
            self.rowcount = 1
        return self


def durable_submission(state):
    i, r = state["item"], state["run"]
    manifest = build_execution_manifest({"schedule_id":r["schedule_id"],
        "schedule_version_id":r["schedule_version_id"],"batch_run_id":r["batch_run_id"],
        "run_item_id":i["run_item_id"],"snapshot_id":r["snapshot_id"],
        "requirement_id":i["requirement_id"],"requirement_version_id":i["requirement_version_id"],
        "requirement_version_number":i["requirement_version_number"],
        "resolved_prompt":"private requirement prompt","resolved_model":"approved-model",
        "deadline_at":i["deadline"]})
    p=prepared_handoff(i["run_item_id"],manifest)
    state["submission"]={"submission_id":p.submission_id,"run_item_id":p.run_item_id,
        "workflow_id":"report_v1","manifest":p.semantic_manifest_json,
        "fingerprint":p.semantic_fingerprint,"session":p.legacy_session_id}
    return p
