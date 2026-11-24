"""Actual Worker dispatch + same-transaction intent registration (offline)."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3

import pytest

from api.services.report_job_store import ADAPTIVE_JOB_OPTION, ReportJobStore, IdempotencyConflict
from api.services.report_job_worker import ReportJobWorker
from api.services.sraf_adaptive_job_runtime import AdaptiveJobIntent, AdaptiveJobRuntime, create_adaptive_job
from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from test_sraf_nround_trusted_execution_loop import _setup, _verified_page
from test_sraf_nround_es_pit_adapter import FakeES


def _intent():
    _, constraints, *_ = _setup()
    return AdaptiveJobIntent(constraints, (("甲軸",), ("乙軸",), ("丙軸",)),
                             ("甲軸", "乙軸", "丙軸"), ("外交回應",))


def _queue(tmp_path):
    store = ReportJobStore(tmp_path / "jobs.db")
    store.initialize()
    return store


def _submit(store, key="deep-one", intent=None):
    return create_adaptive_job(store, intent=intent or _intent(), owner_id="owner",
                               idempotency_key=key, max_active_jobs=2)


def test_atomic_admission_replay_and_rollback(tmp_path):
    store = _queue(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: _submit(store), range(2)))
    assert sum(int(created) for _, created in values) == 1
    job = values[0][0]
    assert all(row.job_id == job.job_id for row, _ in values)
    ck = NroundCheckpointStore(store.db_path)
    assert ck.get_public(job.job_id)["state"] == "QUEUED"
    with sqlite3.connect(store.db_path) as con:
        con.execute("CREATE TRIGGER refuse_adaptive BEFORE INSERT ON sraf_nround_checkpoints "
                    "BEGIN SELECT RAISE(ABORT, 'PRIVATE_ROLLBACK'); END")
    with pytest.raises(sqlite3.IntegrityError):
        _submit(store, "deep-two")
    with sqlite3.connect(store.db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM report_jobs").fetchone()[0] == 1
    other = replace(_intent(), target_aspects=("其他面向",))
    with pytest.raises(IdempotencyConflict):
        _submit(store, intent=other)


def test_actual_worker_routes_deep_job_to_real_word_without_single_round(tmp_path, monkeypatch):
    from agent import report_agent
    import api.services.report_job_worker as worker_mod
    from docx import Document
    store = _queue(tmp_path)
    job, _ = _submit(store)
    fake = FakeES(_verified_page("A"), _verified_page("B"))
    calls = []
    def forbid(*args, **kwargs):
        raise AssertionError("ordinary Agent must not execute")
    monkeypatch.setattr(worker_mod, "execute_agent_turn", forbid)
    monkeypatch.setattr(report_agent, "call_llm",
                        lambda *a, **k: calls.append(1) or "依來源1與來源2分析。")
    def planner(*a, **k):
        return json.dumps({"action": "search", "reason_code": "COVERAGE_GAP",
                           "optional_terms": ["聯合國聲明"], "target_aspects": ["外交回應"]},
                          ensure_ascii=False)
    runtime = AdaptiveJobRuntime(lambda: fake, planner, lambda *_: True,
                                 lambda j, i: j.owner_id == "owner" and i == "news_test",
                                 lambda j, c, branches: j.prompt == c.question and branches == ("CANONICAL_MAIN",))
    root = tmp_path / "reports"
    worker = ReportJobWorker(store, root, adaptive_runtime=runtime)
    claim = store.claim_next()
    worker.execute(claim)
    persisted = store.get(job.job_id)
    assert persisted.status == "completed"
    assert calls == [1]
    assert len(fake.searches) == 2
    assert "多輪分析範圍" in "\n".join(p.text for p in Document(root / persisted.docx_basename).paragraphs)


@pytest.mark.parametrize("mode", ["missing_runtime", "denied_policy", "missing_checkpoint", "tampered_intent"])
def test_deep_worker_fails_closed_without_ordinary_fallback(tmp_path, monkeypatch, mode):
    import api.services.report_job_worker as worker_mod
    store = _queue(tmp_path)
    job, _ = _submit(store)
    def forbidden(*args, **kwargs):
        raise AssertionError("must not invoke provider")
    monkeypatch.setattr(worker_mod, "execute_agent_turn", forbidden)
    runtime = AdaptiveJobRuntime(forbidden, forbidden, forbidden,
                                 lambda *_: False, lambda *_: False)
    if mode == "missing_runtime":
        runtime = None
    elif mode in ("missing_checkpoint", "tampered_intent"):
        with sqlite3.connect(store.db_path) as con:
            if mode == "missing_checkpoint":
                con.execute("DELETE FROM sraf_nround_checkpoints WHERE job_id=?", (job.job_id,))
            else:
                con.execute("UPDATE report_jobs SET options_json=? WHERE job_id=?",
                            (json.dumps({ADAPTIVE_JOB_OPTION: {"bad": True}}), job.job_id))
    root = tmp_path / "reports"
    ReportJobWorker(store, root, adaptive_runtime=runtime).execute(store.claim_next())
    assert store.get(job.job_id).status == "failed"
    assert not list(root.glob("*.docx"))


def test_status_projection_hides_private_intent(tmp_path):
    from api.routers.report_jobs import _view, ReportJobCreate
    from pydantic import ValidationError
    job, _ = _submit(_queue(tmp_path))
    result = _view(job)
    assert result["execution_mode"] == "adaptive_multiround" and result["options"] == {}
    assert "news_test" not in json.dumps(result)
    with pytest.raises(ValidationError):
        ReportJobCreate(prompt=job.prompt, options=job.options)
