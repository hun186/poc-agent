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

def test_owner_summary_list_is_bounded_parameterized_and_secret_free(tmp_path):
    store = make(tmp_path)
    for index, (kind, owner) in enumerate([
        ("service", "owner-a"),
        ("service", "owner-a"),
        ("service", "owner-b"),
        (None, None),  # migrated/unowned legacy records must never leak
    ]):
        store.create(
            job_id=f"rpt_{index}", prompt=f"TOP_SECRET_PROMPT_{index}",
            filename="report.docx", session_id="private-session", model="m",
            options={"private": "secret"}, metadata={"secret": 1},
            idempotency_key=f"secret-key-{index}", request_hash=f"hash-{index}",
            owner_kind=kind, owner_id=owner,
        )
    rows = store.list_owned_summaries(owner_kind="service", owner_id="owner-a", limit=1, offset=0)
    other_page = store.list_owned_summaries(owner_kind="service", owner_id="owner-a", limit=1, offset=1)
    assert len(rows) == len(other_page) == 1
    assert {rows[0]["job_id"], other_page[0]["job_id"]} == {"rpt_0", "rpt_1"}
    assert store.list_owned_summaries(owner_kind="service", owner_id="owner-b")[0]["job_id"] == "rpt_2"
    assert store.list_owned_summaries(owner_kind="service", owner_id="owner-missing") == []
    assert store.list_owned_summaries(owner_kind="user", owner_id="owner-a") == []
    assert store.list_owned_summaries(owner_kind="service", owner_id="owner-a", offset=2) == []
    assert set(rows[0]) == {
        "job_id", "status", "filename", "created_at", "started_at",
        "finished_at", "phase", "phase_updated_at", "failure_category",
    }
    assert "TOP_SECRET" not in str(rows)
    for kwargs in [
        {"owner_kind": "", "owner_id": "owner-a"},
        {"owner_kind": "service", "owner_id": ""},
        {"owner_kind": "service", "owner_id": "owner-a", "limit": 0},
        {"owner_kind": "service", "owner_id": "owner-a", "limit": 101},
        {"owner_kind": "service", "owner_id": "owner-a", "offset": -1},
        {"owner_kind": "service", "owner_id": "owner-a", "offset": 10001},
    ]:
        with pytest.raises(ValueError, match="invalid_report_job_list"):
            store.list_owned_summaries(**kwargs)
