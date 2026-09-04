from datetime import datetime, timezone

import pytest

from requirement_scheduler.models import TriggerIdentity
from requirement_scheduler.store import ScheduleStore

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


class TxConnection:
    def __init__(self, *, fail_marker=None, snapshot="snap-1", checkpoints=None):
        self.fail_marker=fail_marker; self.snapshot=snapshot; self.checkpoints=checkpoints or {}
        self.pending_runs=[]; self.pending_items=[]; self.pending_checkpoints={}; self.committed_runs=[]; self.committed_items=[]; self.committed_checkpoints={}
        self.current=None; self.description=[]; self.rollbacks=0
    def cursor(self): return self
    def execute(self, sql, *params):
        if self.fail_marker and self.fail_marker in sql: raise RuntimeError("injected transaction failure")
        if "SELECT active_version_id" in sql: self.current=("sv-1",)
        elif "SELECT run_policy,status" in sql: self.current=("changed_only","approved")
        elif "SELECT batch_run_id" in sql: self.current=None
        elif "SELECT active_snapshot_id" in sql: self.current=(self.snapshot,) if self.snapshot else None
        elif "SELECT i.requirement_id" in sql:
            self.current=[("internal-1","rv-2",2,9,None,"EXTERNAL-99")]
        elif "SELECT last_seen_requirement_version_id" in sql:
            self.current=self.checkpoints.get(params[1])
        elif "INSERT INTO [sra_schedule].[requirement_batch_runs]" in sql: self.pending_runs.append(params)
        elif "INSERT INTO [sra_schedule].[requirement_batch_run_items]" in sql: self.pending_items.append(params)
        elif "MERGE [sra_schedule].[requirement_schedule_item_state]" in sql: self.pending_checkpoints[params[1]]=(params[2],params[3])
        return self
    def fetchone(self): return self.current if not isinstance(self.current,list) else (self.current.pop(0) if self.current else None)
    def fetchall(self): return list(self.current or [])
    def commit(self):
        self.committed_runs += self.pending_runs; self.committed_items += self.pending_items; self.committed_checkpoints.update(self.pending_checkpoints)
        self.pending_runs=[]; self.pending_items=[]; self.pending_checkpoints={}
    def rollback(self): self.rollbacks+=1; self.pending_runs=[]; self.pending_items=[]; self.pending_checkpoints={}
    def close(self): pass


class Registry:
    def __init__(self, connections): self.connections=list(connections)
    def open_named_connection(self, _): return self.connections.pop(0)


def test_materialization_binds_snapshot_version_external_identity_and_checkpoint_atomically():
    connection=TxConnection(); store=ScheduleStore(Registry([connection]),"db")
    result=store.materialize_run(schedule_id="s",trigger=TriggerIdentity("scheduled",NOW),now_utc=NOW,actor="worker")
    assert result.run["snapshot_id"]=="snap-1" and result.run["schedule_version_id"]=="sv-1"
    assert result.run["phase1a_batch_id"] == "reqrun-" + result.run["batch_run_id"]
    assert result.items[0]["requirement_id"]=="internal-1" and result.items[0]["requirement_version_id"]=="rv-2"
    assert result.items[0]["requirement_version_number"]==2 and result.items[0]["source_order"]==9
    assert result.items[0]["phase1a_task_id"]=="EXTERNAL-99"
    assert connection.committed_checkpoints=={"internal-1":("rv-2",2)}


def test_changed_only_uses_preupdate_checkpoint_and_no_snapshot_is_blocked():
    unchanged=TxConnection(checkpoints={"internal-1":("rv-2",2,None,None)})
    result=ScheduleStore(Registry([unchanged]),"db").materialize_run(schedule_id="s",trigger=TriggerIdentity("scheduled",NOW),now_utc=NOW,actor="w")
    assert result.run["selected_count"]==0 and result.items[0]["selection_reason"]=="unchanged_since_seen"
    empty=TxConnection(snapshot=None)
    blocked=ScheduleStore(Registry([empty]),"db").materialize_run(schedule_id="s",trigger=TriggerIdentity("scheduled",NOW),now_utc=NOW,actor="w")
    assert blocked.run["state"]=="blocked_no_snapshot" and blocked.run["phase1a_batch_id"] == "reqrun-" + blocked.run["batch_run_id"]


@pytest.mark.parametrize("marker", ["requirement_batch_runs]", "requirement_batch_run_items]", "MERGE [sra_schedule]"])
def test_materialization_failure_rolls_back_all_evidence(marker):
    connection=TxConnection(fail_marker=marker)
    with pytest.raises(RuntimeError, match="persistence_error"):
        ScheduleStore(Registry([connection]),"db").materialize_run(schedule_id="s",trigger=TriggerIdentity("scheduled",NOW),now_utc=NOW,actor="w")
    assert connection.rollbacks==1 and connection.committed_runs==[] and connection.committed_items==[] and connection.committed_checkpoints=={}

class RaceConnection:
    def __init__(self, reread=False, unrelated=False): self.reread=reread; self.unrelated=unrelated; self.current=None; self.rollbacks=0
    def cursor(self): return self
    def execute(self, sql, *params):
        if self.reread:
            self.current=("br-first",) if "SELECT batch_run_id" in sql else (datetime(2026,9,6,tzinfo=timezone.utc),)
        elif "SELECT TOP 1" in sql:
            recurrence='{"recurrence":{"kind":"daily","local_time":"00:00:00"}}'
            self.current=("s","sv-1",NOW,"UTC",recurrence,"all_active")
        elif "SELECT batch_run_id" in sql: self.current=None
        elif "SELECT active_snapshot_id" in sql: self.current=None
        elif "INSERT INTO" in sql:
            if self.unrelated: raise RuntimeError("40001 deadlock victim")
            raise RuntimeError("23000 2601 UX_schedule_run_scheduled duplicate key")
        return self
    def fetchone(self): return self.current
    def fetchall(self): return []
    def commit(self): pass
    def rollback(self): self.rollbacks+=1
    def close(self): pass


def test_due_duplicate_race_rereads_first_canonical_run_and_next_time():
    loser=RaceConnection(); reader=RaceConnection(reread=True)
    result=ScheduleStore(Registry([loser,reader]),"db").claim_due(now_utc=NOW,actor="worker")
    assert loser.rollbacks==1 and result["batch_run_id"]=="br-first"
    assert result["next_run_at"]==datetime(2026,9,6,tzinfo=timezone.utc)


def test_due_claim_does_not_swallow_unrelated_database_failure():
    loser=RaceConnection(unrelated=True)
    with pytest.raises(RuntimeError,match="persistence_error"):
        ScheduleStore(Registry([loser]),"db").claim_due(now_utc=NOW,actor="worker")
