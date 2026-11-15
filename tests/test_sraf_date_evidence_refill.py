"""Offline regressions: bounded ES candidate refill after Event date filtering.

This uses actual Evidence parsing, with only ES transport mocked. No live
Elasticsearch, SQL, or LLM service is contacted.
"""
from __future__ import annotations

from contextlib import nullcontext

import pytest

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.tools_es.date_refill import refill_date_filtered_evidence


def _hit(i: int, when: str, *, missing_precision: bool = True) -> dict:
    event = {"event_id": "E1", "time_iso": when}
    if not missing_precision:
        event["time_precision"] = "day"
    return {
        "_id": f"id-{i}",
        "_index": "news_test",
        "_score": 10.0 - i / 100,
        "_source": {
            "uuid": f"doc-{i}",
            "multidim_event_json": [{
                "article_title": "救援行動",
                "article_date_iso": "2026-08-01",
                "Event": [event],
                "Event_Timeline": [],
                "evidence_snippets": [{
                    "event_ids": ["E1"], "text": "救援行動的相關證據"
                }],
            }],
        },
    }


def _response(hits: list, start: int, size: int) -> dict:
    return {"hits": {
        "total": {"value": len(hits), "relation": "eq"},
        "hits": hits[start:start + size],
    }}


def _builder(rows: list):
    return build_hits_and_evidence(
        rows,
        date_from="2025-06-17", date_to="2025-06-17",
        effective_terms=[], term_groups=[], query_for_snippet="救援",
        include_source_hit_ordinal=True,
    )


def test_same_uuid_across_indices_never_joins_wrong_hit_to_evidence():
    # Codex P2: two ES documents can have identical source UUID values but
    # different actual ES identities. Rejected June 1 doc must NEVER borrow
    # the June 17 doc's Evidence or survive final trim as the first result.
    earlier = _hit(1, "2025-06-01")
    valid = _hit(2, "2025-06-17")
    earlier["_source"]["uuid"] = valid["_source"]["uuid"] = "shared-uuid"
    earlier["_source"]["multidim_event_json"][0]["article_title"] = "錯誤來源"
    valid["_source"]["multidim_event_json"][0]["article_title"] = "正確來源"
    earlier["_index"] = "archive"
    valid["_index"] = "news_test"
    rows = [earlier, valid]

    hits, evidence, _, meta = refill_date_filtered_evidence(
        body={"size": 1},
        first_response=_response(rows, 0, 1),
        requested_size=1,
        search_next=lambda next_body: _response(
            rows, next_body["from"], next_body["size"]
        ),
        build_evidence=_builder,
    )
    assert len(hits) == len(evidence) == 1
    assert hits[0]["uuid"] == evidence[0]["uuid"] == "shared-uuid"
    assert hits[0]["article_title"] == "正確來源"
    assert hits[0]["citations"][0]["text"] == evidence[0]["text"]
    assert "__sraf_source_hit_ordinal" not in hits[0]
    assert "__sraf_source_hit_ordinal" not in evidence[0]
    assert meta["result_limit_satisfied"] is True


def test_same_uuid_documents_with_different_dates_keep_only_right_source_even_without_refill():
    rows = [
        _hit(1, "2025-06-01"),
        _hit(2, "2025-06-17"),
    ]
    for row in rows:
        row["_source"]["uuid"] = "same-uuid"
    filtered_hits, evidence, _ = _builder(rows)
    assert len(filtered_hits) == 1
    assert len(evidence) == 1
    assert filtered_hits[0]["__sraf_source_hit_ordinal"] == 1
    assert evidence[0]["__sraf_source_hit_ordinal"] == 1
    assert filtered_hits[0]["article_date_iso"] == "2026-08-01"


def test_first_es_page_only_has_legacy_date_false_positives_then_refills():
    # Original bug: size=3 ES returns June 1/2/3, Evidence eliminates all;
    # fourth ES hit is the matching June 17 event.
    rows = [
        _hit(1, "2025-06-01"),
        _hit(2, "2025-06-02"),
        _hit(3, "2025-06-03"),
        _hit(4, "2025-06-17"),
    ]
    requests = []

    def next_search(body):
        requests.append((body["from"], body["size"]))
        return _response(rows, body["from"], body["size"])

    hits, evidence, syn, meta = refill_date_filtered_evidence(
        body={"size": 3, "query": {"match_all": {}}},
        first_response=_response(rows, 0, 3),
        requested_size=3,
        search_next=next_search,
        build_evidence=_builder,
    )
    assert requests == [(3, 32)]
    assert [hit["uuid"] for hit in hits] == ["doc-4"]
    assert [e["uuid"] for e in evidence] == ["doc-4"]
    assert evidence[0]["date_iso"] == "2025-06-17"
    assert syn == 0
    assert meta["candidates_scanned"] == 4
    assert meta["search_exhausted"] is True
    assert meta["incomplete_due_to_scan_limit"] is False
    assert meta["pages_fetched"] == 2


def test_keep_original_relevance_order_and_stop_after_enough_valid_hits():
    rows = [
        _hit(1, "2025-06-01"),
        _hit(2, "2025-06-17"),
        _hit(3, "2025-06-17"),
        _hit(4, "2025-06-17"),
        _hit(5, "2025-06-17"),
    ]
    requests = []

    def next_search(body):
        requests.append(body)
        return _response(rows, body["from"], body["size"])

    hits, evidence, _, meta = refill_date_filtered_evidence(
        body={"size": 3, "sort": ["_score"]},
        first_response=_response(rows, 0, 3),
        requested_size=3,
        search_next=next_search,
        build_evidence=_builder,
    )
    assert requests and requests[0]["from"] == 3
    assert requests[0]["sort"] == ["_score"]
    assert [hit["uuid"] for hit in hits] == ["doc-2", "doc-3", "doc-4"]
    assert [e["uuid"] for e in evidence] == ["doc-2", "doc-3", "doc-4"]
    assert meta["result_limit_satisfied"] is True
    assert meta["incomplete_due_to_scan_limit"] is False


def test_scan_limit_is_explicit_and_never_claims_exhaustive_zero():
    rows = [_hit(i, "2025-06-01") for i in range(1, 9)]
    requested_pages = []

    def next_search(body):
        requested_pages.append((body["from"], body["size"]))
        return _response(rows, body["from"], body["size"])

    hits, evidence, _, meta = refill_date_filtered_evidence(
        body={"size": 3},
        first_response=_response(rows, 0, 3),
        requested_size=3,
        search_next=next_search,
        build_evidence=_builder,
        max_candidates=5,
    )
    assert hits == []
    assert evidence == []
    assert requested_pages == [(3, 2)]
    assert meta["candidate_scan_limit"] == 5
    assert meta["candidates_scanned"] == 5
    assert meta["incomplete_due_to_scan_limit"] is True
    assert meta["search_exhausted"] is False
    assert meta["note"] == "candidate_scan_limit_reached"


def test_immediate_success_avoids_additional_es_calls():
    rows = [_hit(i, "2025-06-17") for i in range(1, 5)]
    def must_not_search(body):
        raise AssertionError(f"unexpected date refill: {body}")

    hits, evidence, _, meta = refill_date_filtered_evidence(
        body={"size": 3}, first_response=_response(rows, 0, 3),
        requested_size=3, search_next=must_not_search, build_evidence=_builder,
    )
    assert len(hits) == 3
    assert len(evidence) == 3
    assert meta["pages_fetched"] == 1
    assert meta["result_limit_satisfied"] is True


def test_no_candidate_page_is_exhausted_and_not_incomplete():
    called = []
    hits, ev, _, meta = refill_date_filtered_evidence(
        body={"size": 3}, first_response=_response([], 0, 3),
        requested_size=3, search_next=lambda b: called.append(b),
        build_evidence=_builder,
    )
    assert hits == ev == []
    assert called == []
    assert meta["search_exhausted"] is True
    assert meta["incomplete_due_to_scan_limit"] is False


def test_refill_bound_validation_rejects_invalid_budget():
    for budget in (0, 10001):
        with pytest.raises(ValueError):
            refill_date_filtered_evidence(
                body={"size": 3}, first_response=_response([], 0, 3),
                requested_size=3, search_next=lambda b: None,
                build_evidence=_builder, max_candidates=budget,
            )


def test_tool_forward_refills_date_query_and_surfaces_candidate_stats(monkeypatch):
    import agent.tools_es.search_news as search_module

    rows = [
        _hit(1, "2025-06-01"), _hit(2, "2025-06-02"),
        _hit(3, "2025-06-03"), _hit(4, "2025-06-17"),
    ]
    offsets = []
    monkeypatch.setattr(
        search_module, "compute_effective_terms",
        lambda q: ([], {}, False, [], [], []),
    )
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "news_test")
    monkeypatch.setattr(search_module, "log_duration", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(search_module, "log_total", lambda *a, **kw: None)

    def fake_es(body, *, index):
        assert index == "news_test"
        offset = body.get("from", 0)
        offsets.append(offset)
        return _response(rows, offset, body["size"])

    monkeypatch.setattr(search_module, "_safe_es_search", fake_es)
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="救援", size=3,
        date_from="2025-06-17", date_to="2025-06-17",
    )
    assert offsets == [0, 3]
    assert [x["uuid"] for x in result["hits"]] == ["doc-4"]
    assert [x["uuid"] for x in result["evidence_snippets"]] == ["doc-4"]
    assert result["query_meta"]["date_candidate_refill"]["pages_fetched"] == 2
    assert result["query_meta"].get("result_incomplete") is not True


def test_tool_forward_reports_incomplete_when_bounded_candidates_are_all_filtered(monkeypatch):
    import agent.tools_es.search_news as search_module

    rows = [_hit(i, "2025-06-01") for i in range(300)]
    offsets = []
    monkeypatch.setattr(
        search_module, "compute_effective_terms",
        lambda q: ([], {}, False, [], [], []),
    )
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "news_test")
    monkeypatch.setattr(search_module, "log_duration", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(search_module, "log_total", lambda *a, **kw: None)

    def fake_es(body, *, index):
        assert index == "news_test"
        offset = body.get("from", 0)
        offsets.append(offset)
        return _response(rows, offset, body["size"])

    monkeypatch.setattr(search_module, "_safe_es_search", fake_es)
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="救援", size=3,
        date_from="2025-06-17", date_to="2025-06-17",
    )
    assert result["hits"] == []
    assert result["evidence_snippets"] == []
    assert len(offsets) > 1
    assert result["query_meta"]["result_incomplete"] is True
    assert result["query_meta"]["note"] == "date_candidate_scan_limit_reached"
    scan = result["query_meta"]["date_candidate_refill"]
    assert scan["candidates_scanned"] == scan["candidate_scan_limit"] == 256
    assert scan["search_exhausted"] is False


def test_year_in_query_also_refills_and_no_date_query_stays_one_shot(monkeypatch):
    import agent.tools_es.search_news as search_module

    rows = [
        _hit(1, "2024-06-01"), _hit(2, "2024-06-02"),
        _hit(3, "2024-06-03"), _hit(4, "2025-06-17"),
    ]
    offsets = []
    monkeypatch.setattr(
        search_module, "compute_effective_terms",
        lambda q: ([], {}, False, [], [], []),
    )
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "news_test")
    monkeypatch.setattr(search_module, "log_duration", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(search_module, "log_total", lambda *a, **kw: None)

    def fake_es(body, *, index):
        offset = body.get("from", 0)
        offsets.append(offset)
        return _response(rows, offset, body["size"])

    monkeypatch.setattr(search_module, "_safe_es_search", fake_es)
    tool_forward = search_module.ESSearchNews.forward.__wrapped__
    scoped = tool_forward(object(), query="2025年救援", size=3)
    assert offsets == [0, 3]
    assert [e["uuid"] for e in scoped["evidence_snippets"]] == ["doc-4"]
    assert scoped["query_meta"]["date_candidate_refill"]["enabled"] is True

    offsets.clear()
    plain = tool_forward(object(), query="救援", size=3)
    assert offsets == [0]  # no date -> original single ES query
    assert len(plain["hits"]) >= 1
    assert "date_candidate_refill" not in plain["query_meta"]

def test_opt_in_page_admission_denial_preserves_first_valid_date_evidence():
    """No second ES call after budget denial; return verified partial records."""
    from agent.tools_es.retrieval_budget import ESPageAdmissionBudget

    rows = [
        _hit(1, "2025-06-17"), _hit(2, "2025-06-01"),
        _hit(3, "2025-06-17"), _hit(4, "2025-06-17"),
    ]
    calls = []
    denied = ESPageAdmissionBudget(
        max_additional_es_calls=0, deadline_monotonic=100.0,
        generation_reserve_seconds=20.0, clock=lambda: 0.0,
    )
    hits, evidence, _, meta = refill_date_filtered_evidence(
        body={"size": 2}, first_response=_response(rows, 0, 2),
        requested_size=3,
        search_next=lambda body: calls.append(body) or _response(rows, 2, 2),
        build_evidence=_builder,
        admit_next_page=denied,
    )
    assert not calls
    assert [h["uuid"] for h in hits] == ["doc-1"]
    assert [e["uuid"] for e in evidence] == ["doc-1"]
    assert meta["incomplete_due_to_page_admission"] is True
    assert meta["incomplete_due_to_scan_limit"] is False
    assert meta["note"] == "additional_page_admission_denied"
    assert meta["pages_fetched"] == 1


def test_opt_in_page_admission_enables_bounded_additional_es_call():
    from agent.tools_es.retrieval_budget import ESPageAdmissionBudget

    rows = [
        _hit(1, "2025-06-17"), _hit(2, "2025-06-01"),
        _hit(3, "2025-06-17"), _hit(4, "2025-06-17"),
    ]
    calls = []
    budget = ESPageAdmissionBudget(
        max_additional_es_calls=1, deadline_monotonic=100.0,
        generation_reserve_seconds=20.0, clock=lambda: 60.0,
    )

    def additional_search(body):
        calls.append(body)
        return _response(rows, body["from"], body["size"])

    hits, ev, _, meta = refill_date_filtered_evidence(
        body={"size": 2}, first_response=_response(rows, 0, 2),
        requested_size=3, search_next=additional_search,
        build_evidence=_builder, admit_next_page=budget,
    )
    assert len(calls) == 1
    assert [x["uuid"] for x in hits] == ["doc-1", "doc-3", "doc-4"]
    assert [x["uuid"] for x in ev] == ["doc-1", "doc-3", "doc-4"]
    assert meta["incomplete_due_to_page_admission"] is False
    assert meta["result_limit_satisfied"] is True


def test_generation_reserve_denies_page_before_call_without_false_success():
    from agent.tools_es.retrieval_budget import ESPageAdmissionBudget

    rows = [_hit(1, "2025-06-01"), _hit(2, "2025-06-17")]
    budget = ESPageAdmissionBudget(
        max_additional_es_calls=10, deadline_monotonic=100,
        generation_reserve_seconds=20, clock=lambda: 80,
    )
    hits, evidence, _, meta = refill_date_filtered_evidence(
        body={"size": 1}, first_response=_response(rows, 0, 1),
        requested_size=1,
        search_next=lambda body: pytest.fail("budget denied but ES called"),
        build_evidence=_builder, admit_next_page=budget,
    )
    assert hits == evidence == []
    assert meta["incomplete_due_to_page_admission"] is True


@pytest.mark.parametrize("bad_policy", [
    lambda: "yes",
    lambda: None,
    lambda: (_ for _ in ()).throw(ValueError("PRIVATE_POLICY_DETAILS")),
])
def test_invalid_page_admission_fails_closed_and_keeps_private_error_out(
    bad_policy, capsys,
):
    rows = [_hit(1, "2025-06-01"), _hit(2, "2025-06-17")]
    _, _, _, meta = refill_date_filtered_evidence(
        body={"size": 1}, first_response=_response(rows, 0, 1),
        requested_size=1,
        search_next=lambda _: pytest.fail("non-boolean policy was admitted"),
        build_evidence=_builder, admit_next_page=bad_policy,
    )
    assert meta["incomplete_due_to_page_admission"] is True
    assert "PRIVATE_POLICY_DETAILS" not in capsys.readouterr().out


def test_optional_page_gate_absent_retains_exact_legacy_metadata_and_results():
    rows = [_hit(1, "2025-06-01"), _hit(2, "2025-06-17")]
    args = dict(
        body={"size": 1}, first_response=_response(rows, 0, 1),
        requested_size=1,
        search_next=lambda b: _response(rows, b["from"], b["size"]),
        build_evidence=_builder,
    )
    old = refill_date_filtered_evidence(**args)
    same = refill_date_filtered_evidence(**args, admit_next_page=None)
    assert old == same
    assert "incomplete_due_to_page_admission" not in old[3]


def test_es_page_admission_budget_validates_and_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor
    from agent.tools_es.retrieval_budget import ESPageAdmissionBudget

    with pytest.raises(ValueError, match="invalid_es_call_budget"):
        ESPageAdmissionBudget(max_additional_es_calls=True,
                              deadline_monotonic=100, generation_reserve_seconds=2)
    with pytest.raises(ValueError, match="invalid_deadline"):
        ESPageAdmissionBudget(max_additional_es_calls=2,
                              deadline_monotonic=float("nan"), generation_reserve_seconds=2)
    with pytest.raises(ValueError, match="invalid_generation_reserve"):
        ESPageAdmissionBudget(max_additional_es_calls=2,
                              deadline_monotonic=100, generation_reserve_seconds=-1)
    budget = ESPageAdmissionBudget(
        max_additional_es_calls=2, deadline_monotonic=100,
        generation_reserve_seconds=1, clock=lambda: 10,
    )
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: budget(), range(30)))
    assert sum(results) == 2
    assert budget() is False


def test_search_tool_marks_optional_page_budget_incomplete_from_authoritative_meta(
    monkeypatch,
):
    import agent.tools_es.search_news as search_module

    monkeypatch.setattr(
        search_module, "compute_effective_terms",
        lambda q: ([], {}, False, [], [], []),
    )
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "news_test")
    monkeypatch.setattr(search_module, "log_duration",
                        lambda *a, **kw: nullcontext())
    monkeypatch.setattr(search_module, "log_total", lambda *a, **kw: None)
    monkeypatch.setattr(
        search_module, "_safe_es_search",
        lambda body, *, index: _response([_hit(1, "2025-06-01")], 0, 1),
    )

    def denied_refill(**kwargs):
        return [], [], 0, {
            "incomplete_due_to_scan_limit": False,
            "incomplete_due_to_page_admission": True,
            "note": "additional_page_admission_denied",
        }

    monkeypatch.setattr(search_module, "refill_date_filtered_evidence",
                        denied_refill)
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="救援", size=1,
        date_from="2025-06-17", date_to="2025-06-17",
    )
    assert result["query_meta"]["result_incomplete"] is True
    assert result["query_meta"]["note"] == "additional_page_admission_denied"
