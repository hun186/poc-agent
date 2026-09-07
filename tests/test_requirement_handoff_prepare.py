from datetime import datetime, timedelta, timezone
import pytest
from requirement_scheduler.lease import LeaseProof
from requirement_scheduler.store import ScheduleStore
NOW=datetime.now(timezone.utc)
class Cursor:
    rowcount=0
    def __init__(self): self.results=[]; self.mutations=[]
    def execute(self,sql,*params):
        if sql == "SELECT SYSUTCDATETIME()": self.results=[(NOW,)]
        elif "coordinator_leases" in sql: self.results=[("successor","new",2,NOW+timedelta(seconds=30))]
        else: self.mutations.append(sql); self.results=[]
        return self
    def fetchone(self): return self.results.pop(0) if self.results else None
class Connection:
    def __init__(self): self.cursor_value=Cursor(); self.rolled=False
    def cursor(self): return self.cursor_value
    def rollback(self): self.rolled=True
    def commit(self): raise AssertionError("stale coordinator committed")
    def close(self): pass
class Registry:
    def __init__(self,c): self.c=c
    def open_named_connection(self,_): return self.c

def test_stale_coordinator_cannot_bind_root_insert_submission_or_advance_item():
    c=Connection(); store=ScheduleStore(Registry(c),"db")
    stale=LeaseProof("requirement-report-v1","old","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",1,NOW+timedelta(seconds=30))
    with pytest.raises(RuntimeError,match="lease_lost"): store.prepare_next_handoff(lease=stale,output_root_fingerprint="a"*64)
    assert c.rolled and c.cursor_value.mutations == []
