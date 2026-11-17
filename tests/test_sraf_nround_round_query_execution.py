"""Synthetic frozen N-round ES query-plan execution; no real ES/LLM/Word."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json

import pytest

from agent.adaptive_retrieval.es_pit_adapter import FencedESRound
from agent.adaptive_retrieval.round_query_execution import (
    CompletedSingleQueryRound, FrozenSingleQueryPlan,
    RoundQueryPlanError, execute_single_frozen_query,
)
from agent.adaptive_retrieval.planner import BoundNextRoundPlan
from test_sraf_nround_es_pit_adapter import (
    FakeES, _coordinator, _hit, _page,
)


def _plan(c, scope, *, plan=None, **extra):
    return FrozenSingleQueryPlan(
        coordinator=c, constraints=scope,
        authorized_indexes=("news_test",),
        round_number=c.safe_progress()["round"],
        next_round_plan=plan, **extra,
    )


def test_one_full_pit_query_chain_gives_only_technical_completion():
    c, scope, budget = _coordinator()
    es = FakeES(
        _page([_hit(1), _hit(2)], pit_id="PRIVATE_PIT_2"),
        _page([_hit(3)]),
    )
    batch = execute_single_frozen_query(
        plan=_plan(c, scope), client=es, page_size=2, max_pages=3)
    assert type(batch) is CompletedSingleQueryRound
    assert batch.query_plan_complete is True
    assert batch.request_wide_attested is False
    assert batch.round_number == 1
    assert batch.pages_completed == 2
    assert batch.unique_sources == 3
    assert len(batch.hits) == 3
    assert budget.snapshot().remaining_es_calls == 21
    assert [kind for kind, _ in es.calls] == ["open", "search", "search", "close"]
    safe = json.dumps(batch.safe_audit(), ensure_ascii=False)
    for private in ("PRIVATE_PIT", "PRIVATE-ID", "PRIVATE-CONTENT", "news_test"):
        assert private not in safe
    assert batch.safe_audit()["request_wide_attested"] is False
    assert c.safe_progress()["report_job"] == "NOT_INTEGRATED"


def test_claim_blocks_repeat_execution_and_second_plan_same_round():
    c, scope, budget = _coordinator()
    first = _plan(c, scope)
    second = _plan(c, scope)
    es = FakeES(_page([]))
    assert execute_single_frozen_query(plan=first, client=es).query_plan_complete
    charged = budget.snapshot().remaining_es_calls
    with pytest.raises(RoundQueryPlanError, match="query_plan_already_claimed_or_mixed"):
        execute_single_frozen_query(plan=first, client=es)
    with pytest.raises(RoundQueryPlanError, match="query_plan_already_claimed_or_mixed"):
        execute_single_frozen_query(plan=second, client=es)
    assert [kind for kind, _ in es.calls] == ["open", "search", "close"]
    assert budget.snapshot().remaining_es_calls == charged


def test_preexisting_untracked_es_request_blocks_single_branch_proof():
    c, scope, _ = _coordinator()
    assert c.admit_es_call()
    es = FakeES(_page([]))
    with pytest.raises(RoundQueryPlanError, match="query_plan_already_claimed_or_mixed"):
        execute_single_frozen_query(plan=_plan(c, scope), client=es)
    assert es.calls == []


def test_single_frozen_round_two_requires_real_coordinator_approved_plan():
    from test_sraf_shared_evidence_budget import _hit as verified_hit
    c, scope, _ = _coordinator()
    assert c.admit_es_call()
    c.complete_round(
        [verified_hit(1, "PRIVATE_DOC_A", inner=False)],
        query_for_snippet="甲軸乙軸丙軸",
        complete=True, request_wide_attested=True,
        missing_aspects=("外交回應",), coverage_sufficient=False,
    )
    admission = c.plan_next_round()
    assert admission.approved and admission.plan is not None
    fake = replace(admission.plan, optional_terms=("PRIVATE_FORGED_TERM",))
    with pytest.raises(RoundQueryPlanError, match="unapproved_next_round_plan"):
        _plan(c, scope, plan=fake)
    with pytest.raises(RoundQueryPlanError, match="unapproved_next_round_plan"):
        _plan(c, scope)
    es = FakeES(_page([]))
    result = execute_single_frozen_query(
        plan=_plan(c, scope, plan=admission.plan), client=es)
    assert result.query_plan_complete is True
    assert result.request_wide_attested is False
    assert len(es.searches) == 1
    body = json.dumps(es.searches[0]["body"], ensure_ascii=False)
    assert "聯合國聲明" in body
    assert "PRIVATE_FORGED_TERM" not in body


@pytest.mark.parametrize("invalid", ["untrusted_index", "inactive_round", "wrong_branch", "wrong_scope"])
def test_invalid_plans_reject_before_any_es_io(invalid):
    c, scope, _ = _coordinator()
    es = FakeES(_page([]))
    with pytest.raises(RoundQueryPlanError):
        if invalid == "untrusted_index":
            FrozenSingleQueryPlan(c, scope, ("other_private_index",), 1, None)
        elif invalid == "inactive_round":
            FrozenSingleQueryPlan(c, scope, ("news_test",), 2, None)
        elif invalid == "wrong_branch":
            _plan(c, scope, branch_code="FORGED_OMITTED_QUERY")
        else:
            _plan(c, replace(scope, original_core_terms=("OTHER",)))
    assert es.calls == []


@pytest.mark.parametrize("bad", [
    "transport_error", "partial_shards", "close_error", "timeout", "too_many_pages",
])
def test_execution_failure_is_terminal_without_partial_evidence(bad):
    c, scope, _ = _coordinator()
    if bad == "transport_error":
        es = FakeES(fail=RuntimeError("PRIVATE_URL_AUTH"))
    elif bad == "partial_shards":
        es = FakeES(_page([_hit(1)], successful=1))
    elif bad == "close_error":
        es = FakeES(_page([]), closing=RuntimeError("PRIVATE_CLEANUP"))
    elif bad == "timeout":
        es = FakeES(_page([_hit(1)], timed_out=True))
    else:
        es = FakeES(_page([_hit(1)]))
    with pytest.raises(RoundQueryPlanError, match="frozen_query_execution_failed") as err:
        execute_single_frozen_query(
            plan=_plan(c, scope), client=es, page_size=1, max_pages=1)
    assert "PRIVATE" not in str(err.value)
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert not c.safe_progress()["ready_for_external_report_generation"]


@pytest.mark.parametrize("receipt", [
    {"round": 1, "complete_page_chain": False},
    {"round": 999, "complete_page_chain": True},
    {"round": 1, "complete_page_chain": True, "sources_accepted": 999},
])
def test_forged_or_inconsistent_pit_receipt_fails_closed(monkeypatch, receipt):
    from agent.adaptive_retrieval import round_query_execution as module
    c, scope, _ = _coordinator()
    original = {
        "schema": "sraf_nround_es_page_fence_v1",
        "round": 1,
        "complete_page_chain": True,
        "failed": "NONE",
        "request_wide_attested": False,
        "pages_accepted": 1,
        "sources_accepted": 0,
    }
    original.update(receipt)
    monkeypatch.setattr(
        module, "search_fenced_es_round",
        lambda **kwargs: FencedESRound(hits=[], audit=original),
    )
    with pytest.raises(RoundQueryPlanError, match="frozen_query_receipt_unverified"):
        execute_single_frozen_query(plan=_plan(c, scope), client=object())
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_concurrent_same_round_execution_only_one_can_enter_transport():
    c, scope, _ = _coordinator()
    es = FakeES(_page([]))
    p1, p2 = _plan(c, scope), _plan(c, scope)

    def work(p):
        try:
            execute_single_frozen_query(plan=p, client=es)
            return "complete"
        except RoundQueryPlanError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, (p1, p2)))
    assert sorted(results) == ["complete", "denied"]
    assert [kind for kind, _ in es.calls] == ["open", "search", "close"]


def test_untracked_direct_es_adapter_interleaved_at_pit_open_poison_claim():
    """Codex P2 regression: another adapter must not share claimed ES slots."""
    from agent.adaptive_retrieval.es_pit_adapter import (
        LiveRoundESFailure, search_fenced_es_round,
    )
    c, scope, _ = _coordinator()
    attempts = []

    class InterleavedClient(FakeES):
        def open_point_in_time(self, **kwargs):
            # The frozen plan is already claimed when PIT opening starts.
            other = FakeES(_page([]))
            try:
                search_fenced_es_round(
                    coordinator=c, constraints=scope,
                    authorized_indexes=("news_test",), client=other)
            except LiveRoundESFailure:
                attempts.append("direct_denied")
            else:
                attempts.append("BYPASS")
            assert other.calls == []
            return super().open_point_in_time(**kwargs)

    first = InterleavedClient(_page([]))
    with pytest.raises(RoundQueryPlanError, match="frozen_query_execution_failed"):
        execute_single_frozen_query(plan=_plan(c, scope), client=first)
    assert attempts == ["direct_denied"]
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert c.safe_progress()["termination"] == "UNTRACKED_QUERY_ADMISSION"
    assert not c.safe_progress()["ready_for_external_report_generation"]


def test_untracked_direct_admission_interleaved_on_search_invalidates_receipt():
    c, scope, _ = _coordinator()
    external = []

    class InterleavedClient(FakeES):
        def search(self, **kwargs):
            # Frozen plan opened PIT legitimately; unrelated code now
            # attempts another ES request without its opaque token.
            external.append(c.admit_es_call())
            return super().search(**kwargs)

    es = InterleavedClient(_page([]))
    with pytest.raises(RoundQueryPlanError, match="frozen_query_execution_failed"):
        execute_single_frozen_query(plan=_plan(c, scope), client=es)
    assert external == [False]
    assert c.safe_progress()["termination"] == "UNTRACKED_QUERY_ADMISSION"


def test_forged_token_while_claimed_is_fail_closed():
    c, scope, _ = _coordinator()
    p = _plan(c, scope)
    assert c.claim_single_query_execution(
        1, execution_token=p._execution_token)
    assert not c.admit_es_call(execution_token=object())
    assert c.safe_progress()["termination"] == "UNTRACKED_QUERY_ADMISSION"
    assert not c.admit_es_call(execution_token=p._execution_token)


def test_token_cannot_be_used_when_no_frozen_plan_was_claimed():
    c, scope, _ = _coordinator()
    assert not c.admit_es_call(execution_token=object())
    assert c.safe_progress()["termination"] == "UNTRACKED_QUERY_ADMISSION"
