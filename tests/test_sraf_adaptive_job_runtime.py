"""Actual Worker dispatch + same-transaction intent registration (offline)."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3

import pytest

from api.services.report_job_service import DEFAULT_REPORT_MODEL, create_job
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


@pytest.mark.parametrize("pilot,mode", [(False, "shadow"), (True, "off"), (True, "shadow")])
def test_actual_worker_routes_deep_job_to_real_word_without_single_round(tmp_path, monkeypatch, pilot, mode):
    from agent import report_agent
    import api.services.report_job_worker as worker_mod
    from docx import Document
    store = _queue(tmp_path)
    job, _ = _submit(store)
    fake = FakeES(_verified_page("A"), _verified_page("B"))
    calls, planner_inputs, semantic_calls = [], [], []
    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_STRATEGY", mode)
    for flag in ("GROUP_FREQUENCY", "RANK", "TIGHTEN", "RELAX", "DEEP_FREQUENCY", "REVIEW_DEEP"):
        monkeypatch.setenv("SRAF_ARC_" + flag, "off")
    def forbid(*args, **kwargs):
        raise AssertionError("ordinary Agent must not execute")
    monkeypatch.setattr(worker_mod, "execute_agent_turn", forbid)
    monkeypatch.setattr(report_agent, "call_llm",
                        forbid)
    monkeypatch.setattr(report_agent, "REPORT_MODEL_ID", "ordinary:synthetic")
    def planner(prompt, *, system_prompt, timeout):
        assert 0 < timeout <= 60
        payload = json.loads(prompt.split("\n", 1)[1])
        planner_inputs.append(payload)
        term = ("各國外交立場" if payload.get("arc_advisory_read_only") is not None
                else "聯合國聲明")
        return json.dumps({"action": "search", "reason_code": "COVERAGE_GAP",
                           "optional_terms": [term], "target_aspects": ["外交回應"]},
                          ensure_ascii=False)
    def semantic(*args, timeout):
        assert 0 < timeout <= 60
        semantic_calls.append(1)
        return True
    runtime = AdaptiveJobRuntime(lambda: fake, planner, semantic,
                                 lambda j, i: j.owner_id == "owner" and i == "news_test",
                                 lambda j, c, branches: j.prompt == c.question and branches == ("CANONICAL_MAIN",),
                                 lambda *a, **k: calls.append(k["model"]) or "依來源1與來源2分析。",
                                 report_model_id="deep-report:synthetic",
                                 _arc_deep_hint_enabled=pilot)
    root = tmp_path / "reports"
    worker = ReportJobWorker(store, root, adaptive_runtime=runtime)
    claim = store.claim_next()
    worker.execute(claim)
    persisted = store.get(job.job_id)
    assert persisted.status == "completed"
    assert calls == ["deep-report:synthetic"]
    assert report_agent.REPORT_MODEL_ID == "ordinary:synthetic"
    assert len(fake.searches) == 2
    assert len(planner_inputs) == 1 and len(semantic_calls) == 8
    advisory = planner_inputs[0].get("arc_advisory_read_only")
    active = pilot and mode == "shadow"
    assert (advisory is not None) is active
    if active:
        assert advisory["round"] == 1
        assert advisory["advice"] == "inspect_low_incremental_gain"
        assert "PRIVATE" not in json.dumps(advisory)
    before, after = (request["body"] for request in fake.searches)
    bfilter = before["query"]["function_score"]["query"]["bool"]["filter"]
    afilter = after["query"]["function_score"]["query"]["bool"]["filter"]
    assert bfilter == afilter
    selected = "各國外交立場" if active else "聯合國聲明"
    other = "聯合國聲明" if active else "各國外交立場"
    assert selected not in json.dumps(before, ensure_ascii=False)
    assert selected in json.dumps(after, ensure_ascii=False)
    assert other not in json.dumps(after, ensure_ascii=False)
    assert selected not in json.dumps(afilter, ensure_ascii=False)
    assert [k for k, _ in fake.calls] == ["open", "search", "close"] * 2
    assert all(args["index"] == "news_test" for k, args in fake.calls if k == "open")
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
                                 lambda *_: False, lambda *_: False, forbidden)
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


def test_adaptive_admission_preserves_original_question_and_legacy_trim(tmp_path):
    store = _queue(tmp_path)
    intent = _intent()
    original = " \t" + intent.constraints.question + "\n "
    padded = replace(intent, constraints=replace(intent.constraints, question=original))
    job, created = _submit(store, intent=padded)
    assert created and job.prompt == original
    assert store.get(job.job_id).prompt == original
    assert AdaptiveJobIntent.from_options(job.options, job.prompt) == padded
    replay, created = _submit(store, intent=padded)
    assert not created and replay.job_id == job.job_id
    with pytest.raises(IdempotencyConflict):
        _submit(store, intent=intent)
    ordinary, _ = create_job(store, prompt=original, filename=None, session_id=None,
                             model=DEFAULT_REPORT_MODEL, options={}, metadata={},
                             idempotency_key="ordinary", owner_kind="user", owner_id="owner")
    assert ordinary.prompt == original.strip()


@pytest.mark.parametrize('model', ['', 'cloud:model', ' model', 123])
def test_runtime_rejects_invalid_explicit_deep_report_model(model):
    def forbidden(*a, **k):
        raise AssertionError('no provider work')
    with pytest.raises(ValueError, match='adaptive_runtime_model_invalid'):
        AdaptiveJobRuntime(forbidden, forbidden, forbidden, forbidden, forbidden,
                           forbidden, report_model_id=model)


@pytest.mark.parametrize("bad", [1, "true", None])
def test_runtime_arc_pilot_requires_literal_boolean(bad):
    def forbidden(*a, **k):
        raise AssertionError("no provider work")
    with pytest.raises(ValueError, match="adaptive_runtime_arc_pilot_invalid"):
        AdaptiveJobRuntime(forbidden, forbidden, forbidden, forbidden, forbidden,
                           forbidden, _arc_deep_hint_enabled=bad)


def test_arc_pilot_is_not_an_http_or_persisted_job_option(tmp_path):
    from api.routers.report_jobs import ReportJobCreate
    from pydantic import ValidationError
    store = _queue(tmp_path)
    job, _ = _submit(store)
    assert "_arc_deep_hint_enabled" not in json.dumps(job.options)
    with pytest.raises(ValidationError):
        ReportJobCreate(prompt=job.prompt, options={"_arc_deep_hint_enabled": True})
