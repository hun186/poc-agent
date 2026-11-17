"""Offline fake-ES PIT transport tests: no actual ES, SQL, LLM or Report Job."""
from __future__ import annotations

from dataclasses import replace
import copy
import json

import pytest

from agent.adaptive_retrieval.contracts import DateWindow, QueryConstraints
from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
from agent.adaptive_retrieval.es_pit_adapter import (
    FencedESRound, LiveRoundESFailure, search_fenced_es_round,
)
from agent.adaptive_retrieval.planner import AdaptiveRetrievalPlanner
from agent.adaptive_retrieval.request_budget import RequestAdmissionBudget


def _coordinator(*, es_calls=24, deadline=0.0):
    scope = QueryConstraints(
        question="研究甲軸、乙軸、丙軸於 2023 年的國際政策影響",
        event_date=DateWindow("2023-08-24", "2023-08-24",
                              "day", "explicit_user", "2023-08-24"),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
        required_entities=(),
        original_core_terms=("甲軸", "乙軸", "丙軸"),
    )
    budget = RequestAdmissionBudget(
        max_es_calls=es_calls, clock=lambda: deadline)
    planner = AdaptiveRetrievalPlanner(
        lambda *args, **kwargs: json.dumps({
            "action": "search", "reason_code": "COVERAGE_GAP",
            "optional_terms": ["聯合國聲明"],
            "target_aspects": ["外交回應"],
        }, ensure_ascii=False))
    c = AdaptiveRequestCoordinator(
        constraints=scope,
        term_groups=(("甲軸",), ("乙軸",), ("丙軸",)),
        effective_terms=("甲軸", "乙軸", "丙軸"),
        budget=budget, planner=planner,
    )
    assert c.start()
    return c, scope, budget


def _hit(id, *, index="news_test", sort=None):
    return {
        "_index": index, "_id": "PRIVATE-ID-" + str(id),
        "_source": {"title": "PRIVATE-CONTENT-" + str(id)},
        "sort": sort if sort is not None else [20 - id, 100 - id, id],
    }


def _page(hits, *, successful=2, failed=0, timed_out=False, pit_id=None):
    response = {
        "timed_out": timed_out,
        "_shards": {
            "total": 2,
            "successful": successful,
            "failed": failed,
            "skipped": 0,
        },
        "hits": {"hits": copy.deepcopy(hits)},
    }
    if pit_id is not None:
        response["pit_id"] = pit_id
    return response


class FakeES:
    def __init__(self, *pages, fail=None, opening=None, closing=None):
        self.pages = list(pages)
        self.fail = fail
        self.opening = opening
        self.closing = closing
        self.calls = []
        self.searches = []
        self.transport_options = []

    def options(self, **kwargs):
        self.transport_options.append(kwargs)
        return self

    def open_point_in_time(self, **kwargs):
        self.calls.append(("open", kwargs))
        if self.opening is not None:
            raise self.opening
        return {"id": "PRIVATE-PIT-1"}

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        self.searches.append(kwargs)
        if self.fail is not None:
            raise self.fail
        return self.pages.pop(0)

    def close_point_in_time(self, **kwargs):
        self.calls.append(("close", kwargs))
        if self.closing is not None:
            raise self.closing
        return {"succeeded": True}


def _run(c, scope, es, **kwargs):
    return search_fenced_es_round(
        coordinator=c,
        constraints=scope,
        client=es,
        authorized_indexes=("news_test",),
        **kwargs,
    )


def test_complete_pit_chain_has_identity_stable_sort_and_no_report_permission():
    c, scope, budget = _coordinator()
    es = FakeES(
        _page([_hit(1), _hit(2)], pit_id="PRIVATE-PIT-2"),
        _page([_hit(3)]),
    )
    result = _run(c, scope, es, page_size=2, max_pages=3)
    assert isinstance(result, FencedESRound)
    assert len(result.hits) == 3
    assert result.request_wide_attested is False
    assert result.audit["complete_page_chain"] is True
    assert result.audit["request_wide_attested"] is False
    assert [x[0] for x in es.calls] == ["open", "search", "search", "close"]
    opened = es.calls[0][1]
    assert opened["index"] == "news_test"
    assert opened["ignore_unavailable"] is False
    assert opened["allow_partial_search_results"] is False
    assert all(o["max_retries"] == 0 and o["retry_on_timeout"] is False
               and o["retry_on_status"] == () for o in es.transport_options)
    assert all(1 <= o["request_timeout"] <= 30
               for o in es.transport_options)
    assert "request_timeout" not in opened
    assert "index" not in es.searches[0]
    assert es.searches[0]["allow_partial_search_results"] is False
    assert "request_timeout" not in es.searches[0]
    first, second = (request["body"] for request in es.searches)
    assert first["pit"]["id"] == "PRIVATE-PIT-1"
    assert second["pit"]["id"] == "PRIVATE-PIT-2"
    assert "search_after" not in first
    assert second["search_after"] == _hit(2)["sort"]
    assert first["sort"][-1] == {"_shard_doc": {"order": "asc"}}
    assert first["query"] == second["query"]
    # Reuse the canonical nested Event + Event_Timeline date candidate query.
    serialized = json.dumps(first, ensure_ascii=False)
    assert "multidim_event_json.Event.time_iso" in serialized
    assert "multidim_event_json.Event_Timeline.time_iso" in serialized
    assert budget.snapshot().remaining_es_calls == 21  # PIT open + 2 pages
    assert c.safe_progress()["report_job"] == "NOT_INTEGRATED"
    assert c.safe_progress()["ready_for_external_report_generation"] is False
    audit = json.dumps(result.audit)
    assert "PRIVATE-ID" not in audit and "PRIVATE-PIT" not in audit


@pytest.mark.parametrize("problem", [
    "missing_pit", "open_exception", "transport_exception",
    "partial_shards", "timed_out", "bad_index", "full_page_limit",
    "failed_cleanup", "negative_cleanup",
])
def test_all_transport_and_page_failures_refuse_partial_evidence(problem):
    c, scope, budget = _coordinator()
    if problem == "missing_pit":
        es = FakeES()
        def no_id(**kwargs):
            es.calls.append(("open", kwargs))
            return {"id": None}
        es.open_point_in_time = no_id
    elif problem == "open_exception":
        es = FakeES(opening=TimeoutError("PRIVATE-URL-TOKEN"))
    elif problem == "transport_exception":
        es = FakeES(fail=ConnectionError("PRIVATE-SERVER-CREDENTIAL"))
    elif problem == "partial_shards":
        es = FakeES(_page([_hit(1)], successful=1))
    elif problem == "timed_out":
        es = FakeES(_page([_hit(1)], timed_out=True))
    elif problem == "bad_index":
        es = FakeES(_page([_hit(1, index="unauthorized_prod_index")]))
    elif problem == "full_page_limit":
        es = FakeES(_page([_hit(1)]))
    elif problem == "failed_cleanup":
        es = FakeES(_page([_hit(1)]),
                    closing=RuntimeError("PRIVATE-CLEANUP-DETAIL"))
    elif problem == "negative_cleanup":
        es = FakeES(_page([_hit(1)]))
        def failed_close(**kwargs):
            es.calls.append(("close", kwargs))
            return {"succeeded": False}
        es.close_point_in_time = failed_close
    with pytest.raises(LiveRoundESFailure) as err:
        _run(c, scope, es, page_size=1, max_pages=1)
    assert "PRIVATE" not in str(err.value)
    assert c.safe_progress()["phase"] == "TERMINAL"
    assert not c.safe_progress()["ready_for_external_report_generation"]
    assert not c.admit_es_call()
    if problem not in ("open_exception", "missing_pit"):
        assert es.calls[-1][0] == "close"


def test_fail_closed_scope_cannot_silently_drop_field_entity_analysis_date():
    c, scope, _ = _coordinator()
    for changed in (
        replace(scope, required_entities=("PRIVATE_ENTITY",)),
        replace(scope, fixed_fields=(("news.flag", "yes"),)),
        replace(scope, analysis_date=DateWindow(
            "2023-01-01", "2023-12-31", "year",
            "explicit_user", "2023")),
    ):
        from agent.adaptive_retrieval.coordinator import AdaptiveRequestCoordinator
        # The same-object identity guard must be exercised, not bypassed:
        # reuse coordinator but replace scope to match it for this isolated test.
        c._constraints = changed
        es = FakeES()
        with pytest.raises(LiveRoundESFailure, match="unsupported_es_hard_scope"):
            _run(c, changed, es)
        assert es.calls == []
    c._constraints = scope


def test_unauthorized_index_or_plan_is_denied_before_any_es_io():
    c, scope, _ = _coordinator()
    es = FakeES()
    with pytest.raises(LiveRoundESFailure, match="untrusted_es_adapter_context"):
        search_fenced_es_round(
            coordinator=c, constraints=scope, client=es,
            authorized_indexes=("private_other_index",))
    assert not es.calls
    from agent.adaptive_retrieval.planner import BoundNextRoundPlan
    forged = BoundNextRoundPlan(
        round_number=2, constraints=scope,
        optional_terms=("私人搜索",), target_aspects=("政策",))
    with pytest.raises(LiveRoundESFailure, match="untrusted_next_round_strategy"):
        _run(c, scope, es, plan=forged)
    assert not es.calls


def test_pit_open_still_consumes_es_budget_before_any_network():
    c, scope, budget = _coordinator(es_calls=1)
    es = FakeES(_page([_hit(1)]))
    with pytest.raises(LiveRoundESFailure):
        _run(c, scope, es)
    assert [entry[0] for entry in es.calls] == ["open", "close"]
    assert budget.snapshot().remaining_es_calls == 0
    assert c.safe_progress()["phase"] == "TERMINAL"


def test_untrusted_non_callable_client_rejected_without_network():
    c, scope, _ = _coordinator()
    with pytest.raises(LiveRoundESFailure, match="untrusted_es_adapter_context"):
        _run(c, scope, object())


def test_second_semantic_round_requires_genuine_coordinator_plan():
    c, scope, _ = _coordinator()
    from agent.adaptive_retrieval.planner import BoundNextRoundPlan
    # Do not mutate state to forge Round 2. At round one, a self-constructed
    # BoundNextRoundPlan cannot initiate another search.
    plan = BoundNextRoundPlan(
        2, scope, ("外交政策",), ("政策反應",))
    es = FakeES(_page([_hit(1)]))
    with pytest.raises(LiveRoundESFailure, match="untrusted_next_round_strategy"):
        _run(c, scope, es, plan=plan)
    assert es.calls == []


def test_active_round_two_only_accepts_exact_coordinator_approved_plan():
    # Construct a genuine canonical round 1 and let the coordinator itself
    # approve round 2. A forged same-round plan is then invalid, even when
    # it points at the exact same frozen QueryConstraints object.
    from test_sraf_shared_evidence_budget import _hit as canonical_hit

    c, scope, budget = _coordinator()
    assert c.admit_es_call()  # canonical synthetic round 1 used one ES slot
    first = c.complete_round(
        [canonical_hit(1, "A", inner=False)],
        query_for_snippet="甲軸乙軸丙軸", complete=True,
        request_wide_attested=True,
        missing_aspects=("外交回應",), coverage_sufficient=False,
    )
    assert first.number == 1
    admission = c.plan_next_round()
    assert admission.approved and admission.plan is not None
    assert c.safe_progress()["round"] == 2
    assert admission.plan is c._approved_plan

    fake = replace(admission.plan, optional_terms=("未准入的新搜尋詞",))
    es = FakeES(_page([]))
    with pytest.raises(LiveRoundESFailure, match="untrusted_next_round_strategy"):
        _run(c, scope, es, plan=fake)
    assert es.calls == []
    # The actual planner-approved strategy can request a full PIT chain.
    result = _run(c, scope, es, plan=admission.plan)
    assert result.hits == []
    assert result.request_wide_attested is False
    request_dump = json.dumps(es.searches[0]["body"], ensure_ascii=False)
    assert "聯合國聲明" in request_dump
    assert "未准入的新搜尋詞" not in request_dump
    assert c.safe_progress()["phase"] == "SEARCHING"
