from types import SimpleNamespace
from requirement_scheduler.coordinator import RequirementHandoffCoordinator
from requirement_scheduler.reconciliation import ReconcileResult
class Store:
    def __init__(self): self.events=[]
    def acquire_lease(self,*a): self.events.append("acquire"); return object()
    def renew_lease(self,*a): self.events.append("renew"); return object()
class Reconciler:
    def __init__(self,store,remaining=False): self.store=store; self.remaining=remaining
    def reconcile_batch(self,*a): self.store.events.append("reconcile"); return ReconcileResult(0,self.remaining)
class Service:
    def __init__(self,store): self.store=store
    def prepare_next(self,*a): self.store.events.append("prepare"); return None

def test_reconciliation_precedes_new_prepare_and_renewal_precedes_mutation():
    store=Store(); c=RequirementHandoffCoordinator(store,Reconciler(store),Service(store),SimpleNamespace(lease_duration=45,batch_size=20),owner_id="o")
    c.run_once(); c.run_once()
    assert store.events == ["acquire","reconcile","prepare","renew","reconcile","prepare"]

def test_backlog_blocks_new_prepare():
    store=Store(); c=RequirementHandoffCoordinator(store,Reconciler(store,True),Service(store),SimpleNamespace(lease_duration=45,batch_size=20),owner_id="o")
    c.run_once(); assert store.events == ["acquire","reconcile"]
