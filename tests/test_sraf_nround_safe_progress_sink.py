"""Opt-in N-round runtime safe audit -> SQLite checkpoint bridge, fake ES only."""
from __future__ import annotations

import json

import pytest

from agent.adaptive_retrieval.job_checkpoint import NroundCheckpointStore
from agent.adaptive_retrieval.trusted_execution_loop import (
    TrustedNroundExecutionError, run_trusted_nround,
)
from test_sraf_nround_es_pit_adapter import FakeES
from test_sraf_nround_trusted_execution_loop import _setup, _verified_page

J = "rpt_" + "6" * 32


def _run(c, scope, ev, es, *, sink):
    return run_trusted_nround(
        coordinator=c, constraints=scope, evaluator=ev,
        authorized_indexes=("news_test",),
        es_client=es, semantic_assessor=lambda *_: True,
        attest_whole_query_scope=lambda *_: True,
        query_for_snippet="甲軸乙軸丙軸",
        checkpoint_sink=sink,
    )


def test_real_temporary_sqlite_checkpoint_progress_rounds_and_terminal(tmp_path):
    c, scope, ev, budget, planners, _ = _setup()
    store = NroundCheckpointStore(tmp_path / "private-only.sqlite3")
    store.initialize()
    assert store.create(J)
    token = store.claim(J)
    assert token
    emitted = []

    def persist(item):
        emitted.append((item["phase"], item["round"], item["completed_rounds"],
                        item["es_calls_admitted_this_round"]))
        return store.record_progress(J, token, item)

    result = _run(
        c, scope, ev,
        FakeES(_verified_page("A"), _verified_page("B")),
        sink=persist,
    )
    assert len(result.rounds) == 2
    assert planners == [1]
    assert emitted == [
        ("SEARCHING", 1, 0, 0),
        ("SEARCHING", 1, 0, 2),
        ("ASSESSED", 1, 1, 2),
        ("SEARCHING", 2, 1, 0),
        ("SEARCHING", 2, 1, 2),
        ("TERMINAL", 2, 2, 2),
    ]
    public = store.get_public(J)
    assert public["state"] == "RETRIEVAL_STOPPED"
    assert public["completed_rounds"] == 2
    assert public["termination"] == "SUFFICIENT"
    assert public["report_generation_authorized"] is False
    assert public["checkpoint_resume_supported"] is False
    out = json.dumps(public)
    for secret in ("PRIVATE", "news_test", "甲軸", token):
        assert secret not in out


@pytest.mark.parametrize("return_value", [False, 0, 1, None, "true"])
def test_initial_checkpoint_denial_prevents_any_es_or_llm(return_value):
    c, scope, ev, _, planners, _ = _setup()
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError,
                       match="trusted_nround_execution_failed"):
        _run(c, scope, ev, es, sink=lambda _: return_value)
    assert es.calls == []
    assert planners == []
    assert c.history == ()
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_checkpoint_rejected_after_pit_never_enters_semantic_verification():
    c, scope, ev, _, planners, _ = _setup()
    es = FakeES(_verified_page("A"))
    calls = []
    def persist(p):
        calls.append((p["phase"], p["es_calls_admitted_this_round"]))
        return p["es_calls_admitted_this_round"] < 2
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, sink=persist)
    assert calls == [("SEARCHING", 0), ("SEARCHING", 2)]
    assert [kind for kind, _ in es.calls] == ["open", "search", "close"]
    assert c.history == ()
    assert planners == []
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_checkpoint_failure_before_second_pit_preserves_first_round_only():
    c, scope, ev, _, planners, _ = _setup()
    es = FakeES(_verified_page("A"))
    def persist(p):
        return not (p["round"] == 2 and p["phase"] == "SEARCHING")
    with pytest.raises(TrustedNroundExecutionError):
        _run(c, scope, ev, es, sink=persist)
    assert planners == [1]
    assert len(es.searches) == 1
    assert c.safe_progress()["completed_rounds"] == 1
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_checkpoint_exception_redacts_provider_and_path_data():
    c, scope, ev, _, planners, _ = _setup()
    es = FakeES(_verified_page("A"))
    def fail(_):
        raise RuntimeError("PRIVATE_SQLITE_FULL_PATH_AND_TOKEN")
    with pytest.raises(TrustedNroundExecutionError) as err:
        _run(c, scope, ev, es, sink=fail)
    assert "PRIVATE" not in str(err.value)
    assert es.calls == []
    assert planners == []


def test_snapshot_is_detached_from_live_coordinator_internal_state():
    c, scope, ev, _, planners, _ = _setup()
    es = FakeES(_verified_page("A"), _verified_page("B"))
    observed = []
    def mutate_snapshot(snapshot):
        observed.append(snapshot["phase"])
        snapshot["phase"] = "PRIVATE_INJECTED_PHASE"
        snapshot["canonical_evidence_history"] = ()
        return True
    result = _run(c, scope, ev, es, sink=mutate_snapshot)
    assert result.progress["phase"] == "TERMINAL"
    assert result.progress["termination"] == "SUFFICIENT"
    assert result.progress["completed_rounds"] == 2
    assert observed == ["SEARCHING", "SEARCHING", "ASSESSED",
                        "SEARCHING", "SEARCHING", "TERMINAL"]


def test_invalid_sink_fails_before_any_start_or_es():
    c, scope, ev, _, _, _ = _setup()
    es = FakeES(_verified_page("A"))
    with pytest.raises(TrustedNroundExecutionError,
                       match="invalid_trusted_nround_context"):
        _run(c, scope, ev, es, sink=123)
    assert c.safe_progress()["phase"] == "CREATED"
    assert es.calls == []



@pytest.mark.parametrize("failure_mode", ["false", "exception"])
def test_terminal_checkpoint_failure_revokes_prior_sufficient_report_readiness(
    failure_mode,
):
    c, scope, ev, _, planners, _ = _setup()
    es = FakeES(_verified_page("A"), _verified_page("B"))
    events = []

    def persist(snapshot):
        events.append((snapshot["phase"], snapshot["termination"]))
        if (snapshot["phase"] == "TERMINAL"
                and snapshot["termination"] == "SUFFICIENT"):
            # The coordinator has already accepted adequate Evidence and
            # would expose ready=True unless the sink failure revokes it.
            assert c.safe_progress()["ready_for_external_report_generation"] is True
            if failure_mode == "exception":
                raise OSError("PRIVATE_CHECKPOINT_DB_PATH")
            return False
        return True

    with pytest.raises(TrustedNroundExecutionError,
                       match="trusted_nround_execution_failed") as err:
        _run(c, scope, ev, es, sink=persist)
    assert "PRIVATE_" not in str(err.value)
    assert events[-1] == ("TERMINAL", "SUFFICIENT")
    status = c.safe_progress()
    assert status["phase"] == "TERMINAL"
    assert status["termination"] == "CANCELLED"
    assert status["ready_for_external_report_generation"] is False
    assert status["completed_rounds"] == 2
    assert planners == [1]
    assert len(es.searches) == 2
    # Historical canonical source/evidence counts are retained for
    # diagnosis, but are NOT a report/Word handoff authorization.
    assert len(status["canonical_evidence_history"]) == 2
