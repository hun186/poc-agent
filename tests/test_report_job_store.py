from concurrent.futures import ThreadPoolExecutor
import pytest
from api.services.report_job_store import IdempotencyConflict, ReportJobStore

def make(tmp_path):
    store=ReportJobStore(tmp_path/"jobs.db"); store.initialize(); return store
def create(store, key="key", digest="hash"):
    return store.create(job_id="rpt_one",prompt="p",filename="x.docx",session_id="s",model="m",options={},metadata={},idempotency_key=key,request_hash=digest)
def test_schema_create_and_idempotency(tmp_path):
    store=make(tmp_path); first,new=create(store); second,new2=create(store)
    assert first.status=="queued" and new and second.job_id==first.job_id and not new2
    with pytest.raises(IdempotencyConflict): create(store,digest="other")
def test_atomic_claim_has_one_winner(tmp_path):
    store=make(tmp_path); create(store)
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(lambda _: store.claim_next(), range(2)))
    assert sum(item is not None for item in results)==1
def test_recovery_interrupts_running_but_not_queued(tmp_path):
    store=make(tmp_path); create(store); store.claim_next()
    assert store.recover_running()==1 and store.get("rpt_one").status=="interrupted"
