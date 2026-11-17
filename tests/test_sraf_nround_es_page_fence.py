"""Offline-only ES page chain tests: no network, no production adapter."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json

import pytest

from agent.adaptive_retrieval.es_page_fence import (
    PageFenceError, PageTicket, RoundESPageFence,
)
from test_sraf_nround_coordinator import coordinator, scope


def _hit(n, *, index="news_test", title="PRIVATE-ARTICLE"):
    return {
        "_index": index, "_id": f"PRIVATE-ID-{n}",
        "_source": {"title": title}, "sort": [n],
    }


def _response(hits, *, timed_out=False, failed=0, successful=2, skipped=0):
    return {
        "timed_out": timed_out,
        "_shards": {
            "total": 2 + failed, "successful": successful,
            "skipped": skipped, "failed": failed,
        },
        "hits": {"hits": copy.deepcopy(hits)},
    }


def _fence(*, page_size=2, max_pages=5, clock=None, **opts):
    c, budget, calls = coordinator(clock=clock, **opts)
    assert c.start()
    fence = RoundESPageFence(
        coordinator=c, constraints=c._constraints, round_number=1,
        page_size=page_size, max_pages=max_pages,
    )
    return c, fence, budget


def test_strict_two_page_chain_and_private_ticket_cursor():
    c, fence, budget = _fence()
    first = fence.begin_page()
    assert first.page_number == 1 and first.search_after is None
    assert fence.submit_page(first, _response([_hit(1), _hit(2)])) is False
    with pytest.raises(PageFenceError, match="incomplete_es_page_chain"):
        fence.take_complete_hits()
    second = fence.begin_page()
    assert second.page_number == 2
    assert second.search_after == (2,)
    assert fence.submit_page(second, _response([_hit(3)])) is True
    hits = fence.take_complete_hits()
    assert len(hits) == 3
    assert budget.snapshot().remaining_es_calls == 22
    assert c.safe_progress()["phase"] == "SEARCHING"
    with pytest.raises(PageFenceError, match="incomplete_es_page_chain"):
        fence.take_complete_hits()
    with pytest.raises(PageFenceError, match="es_page_not_admissible"):
        fence.begin_page()
    audit = json.dumps(fence.safe_audit(), ensure_ascii=False)
    assert '"pages_accepted": 2' in audit
    assert '"request_wide_attested": false' in audit
    for private in ("PRIVATE-ID", "PRIVATE-ARTICLE", "news_test", "(2,)"):
        assert private not in audit


def test_successful_search_includes_skipped_shards_without_false_partial():
    c, fence, _ = _fence(page_size=2)
    ticket = fence.begin_page()
    page = _response([_hit(1)], successful=2, skipped=1)
    assert fence.submit_page(ticket, page) is True
    assert len(fence.take_complete_hits()) == 1
    assert c.safe_progress()["phase"] == "SEARCHING"
    assert fence.safe_audit()["failed"] == "NONE"


def test_short_page_marked_early_terminated_cannot_complete_chain():
    c, fence, _ = _fence(page_size=20)
    ticket = fence.begin_page()
    response = _response([_hit(1)])
    response["terminated_early"] = True
    with pytest.raises(PageFenceError, match="es_search_terminated_early"):
        fence.submit_page(ticket, response)
    assert fence.safe_audit()["complete_page_chain"] is False
    assert fence.safe_audit()["request_wide_attested"] is False
    assert c.safe_progress()["termination"] == "CANCELLED"
    with pytest.raises(PageFenceError, match="incomplete_es_page_chain"):
        fence.take_complete_hits()


def test_exactly_full_last_page_requires_extra_empty_page():
    _, fence, _ = _fence(page_size=1)
    first = fence.begin_page()
    assert not fence.submit_page(first, _response([_hit(1)]))
    second = fence.begin_page()
    assert second.search_after == (1,)
    assert fence.submit_page(second, _response([]))
    assert len(fence.take_complete_hits()) == 1


@pytest.mark.parametrize("mutate,reason", [
    (lambda r: r.update({"timed_out": True}), "es_timeout_or_bad_page"),
    (lambda r: r.update({"terminated_early": True}), "es_search_terminated_early"),
    (lambda r: r.update({"is_partial": True}), "es_search_terminated_early"),
    (lambda r: r.update({"terminated_early": "false"}), "untrusted_es_completeness_flags"),
    (lambda r: r.update({"terminated_early": 1}), "untrusted_es_completeness_flags"),
    (lambda r: r.update({"is_partial": 0}), "untrusted_es_completeness_flags"),
    (lambda r: r["_shards"].update({"failed": 1, "total": 3}), "partial_es_shards"),
    (lambda r: r["_shards"].update({"successful": 1}), "partial_es_shards"),
    (lambda r: r["_shards"].update({"successful": 1, "skipped": 1}), "partial_es_shards"),
    (lambda r: r["_shards"].update({"skipped": 3}), "partial_es_shards"),
    (lambda r: r["hits"]["hits"][0].update({"_index": "private_index"}), "untrusted_es_source"),
    (lambda r: r["hits"]["hits"][0].update({"_source": "PRIVATE"}), "untrusted_es_source"),
    (lambda r: r["hits"]["hits"].append(_hit(9)), "oversized_es_page"),
    (lambda r: r["hits"]["hits"][0].update({"sort": []}), "missing_es_sort_cursor"),
])
def test_bad_page_always_cancels_future_es(mutate, reason):
    c, fence, _ = _fence(page_size=1)
    ticket = fence.begin_page()
    response = _response([_hit(1)])
    mutate(response)
    with pytest.raises(PageFenceError, match=reason):
        fence.submit_page(ticket, response)
    assert c.safe_progress()["termination"] == "CANCELLED"
    assert not c.safe_progress()["ready_for_external_report_generation"]
    assert not c.admit_es_call()
    assert fence.safe_audit()["failed"] == reason
    with pytest.raises(PageFenceError, match="es_page_not_admissible"):
        fence.begin_page()


def test_repeated_cursor_and_duplicate_source_are_fail_closed():
    c, fence, _ = _fence(page_size=1)
    ticket = fence.begin_page()
    assert not fence.submit_page(ticket, _response([_hit(1)]))
    ticket2 = fence.begin_page()
    with pytest.raises(PageFenceError, match="unchanged_es_search_after"):
        fence.submit_page(ticket2, _response([_hit(2) | {"sort": [1]}]))
    assert c.safe_progress()["phase"] == "TERMINAL"

    c2, fence2, _ = _fence(page_size=1)
    assert not fence2.submit_page(fence2.begin_page(), _response([_hit(1)]))
    with pytest.raises(PageFenceError, match="duplicate_es_pagination_source"):
        fence2.submit_page(fence2.begin_page(), _response([_hit(1) | {"sort": [2]}]))
    assert c2.safe_progress()["termination"] == "CANCELLED"


def test_timeout_after_page_admission_does_not_attest_complete():
    clock = [0.0]
    c, fence, _ = _fence(clock=clock)
    ticket = fence.begin_page()
    clock[0] = 1800.0  # 30m retrieval cutoff; generation reserve remains.
    with pytest.raises(PageFenceError, match="es_page_after_retrieval_deadline"):
        fence.submit_page(ticket, _response([_hit(1)]))
    assert fence.safe_audit()["complete_page_chain"] is False
    assert c.safe_progress()["ready_for_external_report_generation"] is False


def test_budget_and_page_cap_prevent_truncation_from_becoming_complete():
    c, fence, _ = _fence(page_size=1, max_pages=1)
    assert not fence.submit_page(fence.begin_page(), _response([_hit(1)]))
    with pytest.raises(PageFenceError, match="es_page_limit_exhausted"):
        fence.begin_page()
    assert c.safe_progress()["termination"] == "CANCELLED"
    with pytest.raises(PageFenceError, match="incomplete_es_page_chain"):
        fence.take_complete_hits()

    c2, fence2, _ = _fence(page_size=1, max_es_calls=1)
    assert not fence2.submit_page(fence2.begin_page(), _response([_hit(1)]))
    with pytest.raises(PageFenceError, match="es_page_budget_exhausted"):
        fence2.begin_page()
    assert c2.safe_progress()["termination"] == "RESOURCE_BUDGET_EXHAUSTED"


def test_wrong_scope_round_replay_or_cancelled_pending_ticket_is_rejected():
    c, fence, _ = _fence()
    with pytest.raises(ValueError, match="invalid_es_page_fence_config"):
        RoundESPageFence(
            coordinator=c, constraints=scope(), round_number=1,
        )
    with pytest.raises(ValueError, match="es_page_round_not_active"):
        RoundESPageFence(
            coordinator=c, constraints=c._constraints, round_number=2,
        )
    ticket = fence.begin_page()
    forged = PageTicket(ticket.round_number, ticket.page_number,
                        ticket.size, ticket.search_after)
    with pytest.raises(PageFenceError, match="stale_es_page_ticket"):
        fence.submit_page(forged, _response([_hit(1)]))
    assert c.cancel()
    with pytest.raises(PageFenceError, match="es_page_round_no_longer_active"):
        fence.submit_page(ticket, _response([_hit(1)]))
    assert fence.safe_audit()["complete_page_chain"] is False


def test_concurrent_es_page_begin_has_one_pending_ticket():
    c, fence, _ = _fence()
    def begin(_):
        try:
            return fence.begin_page()
        except PageFenceError:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        tickets = list(pool.map(begin, range(10)))
    assert sum(t is not None for t in tickets) == 1
    assert c.safe_progress()["es_calls_admitted_this_round"] == 1


def test_es_hit_cap_is_failure_not_successful_attestation():
    c, fence, _ = _fence(page_size=100, max_pages=11)
    for page_no in range(10):
        start = page_no * 100
        ticket = fence.begin_page()
        assert fence.submit_page(
            ticket, _response([_hit(i) for i in range(start, start + 100)]),
        ) is False
    # Another page would breach canonical ledger's MAX_HITS=1000.
    ticket = fence.begin_page()
    with pytest.raises(PageFenceError, match="es_round_hit_limit_exhausted"):
        fence.submit_page(ticket, _response([_hit(1000)]))
    assert c.safe_progress()["termination"] == "CANCELLED"
