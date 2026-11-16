"""No-network canonical Event/topic Evidence receipt ledger regressions."""
from __future__ import annotations

import copy
import json
import pytest

from agent.adaptive_retrieval.evidence_ledger import (
    RequestWideEvidenceLedger, RoundObservation, observe_canonical_round,
)
from agent.adaptive_retrieval import (
    AdaptiveRetrievalPlanner, BudgetSnapshot, DateWindow, QueryConstraints,
)
from test_sraf_shared_evidence_budget import _hit, D0, D1

GROUPS = [{"甲軸"}, {"乙軸"}, {"丙軸"}]


def _observe(hits, *, complete=True, effective_terms=None):
    return observe_canonical_round(
        copy.deepcopy(hits), date_from=D0, date_to=D0,
        term_groups=copy.deepcopy(GROUPS),
        effective_terms=(["甲軸", "乙軸", "丙軸"] if
                         effective_terms is None else effective_terms),
        query_for_snippet="甲軸乙軸丙軸",
        original_question="請分析甲軸乙軸丙軸涉及的事件", complete=complete,
    )


def _append(ledger, receipt, *, missing=("事件背景",), sufficient=False,
            attested=True, search=("甲軸", "乙軸", "丙軸")):
    return ledger.append(
        receipt, search_terms=search,
        missing_aspects=missing, coverage_sufficient=sufficient,
        request_wide_attested=attested,
    )


def test_same_evidence_across_reordered_rounds_is_not_new():
    ledger = RequestWideEvidenceLedger()
    a, b = _hit(4, "A", inner=False), _hit(2, "B", inner=False)
    first = _append(ledger, _observe([a, b]))
    assert first.verified_evidence == 6
    assert first.newly_verified_evidence == 6
    assert first.known_sources == 2
    assert first.request_wide is True
    next_round = _append(ledger, _observe([b, a]), search=("新詞",))
    assert next_round.verified_evidence == 6
    assert next_round.newly_verified_evidence == 0
    assert next_round.known_sources == 2
    assert ledger.safe_audit()[-1]["new_sources"] == 0
    assert "A" not in json.dumps(ledger.safe_audit())


def test_new_verified_evidence_and_sources_are_counted_separately():
    ledger = RequestWideEvidenceLedger()
    a = _hit(4, "A", inner=False)
    b = _hit(2, "B", inner=False)
    _append(ledger, _observe([a]))
    row = _append(ledger, _observe([a, b]), search=("補充",))
    assert row.verified_evidence == 6
    assert row.newly_verified_evidence == 2
    assert row.known_sources == 2
    assert ledger.safe_audit()[-1]["candidate_sources"] == 2
    assert ledger.safe_audit()[-1]["new_sources"] == 1


def test_event_only_date_is_retained_and_wrong_event_date_not_borrowed():
    hit = _hit(4, "EVENT-ONLY", other_date_every=2, inner=False)
    # Timeline already empty; Event E1 is requested date, E2 is not.
    assert hit["_source"]["multidim_event_json"][0]["Event_Timeline"] == []
    report = _observe([hit])
    assert report.parser_output_rows == 2
    assert len(report.verified_evidence) == 2
    assert len(report.verified_sources) == 1
    assert report.fallback_rows == 0


def test_same_event_ids_and_text_in_different_nested_blocks_stay_distinct():
    hit = _hit(1, "TWO-BLOCK", inner=False)
    block = copy.deepcopy(hit["_source"]["multidim_event_json"][0])
    # Same source_id/paragraph_id/Event IDs/time/text in a DIFFERENT block.
    hit["_source"]["multidim_event_json"].append(block)
    observation = _observe([hit])
    assert observation.parser_output_rows == 2
    assert len(observation.verified_evidence) == 2
    assert observation.validated_rows == 2
    assert observation.fallback_rows == 0


def test_duplicate_citations_in_same_block_do_not_become_new_across_rounds():
    hit = _hit(1, "DUP", inner=False)
    block = hit["_source"]["multidim_event_json"][0]
    block["evidence_snippets"].append(copy.deepcopy(block["evidence_snippets"][0]))
    obs = _observe([hit])
    assert obs.parser_output_rows == 2
    assert obs.validated_rows == 2
    assert obs.fallback_rows == 0
    assert len(obs.verified_evidence) == 1
    ledger = RequestWideEvidenceLedger()
    one = _append(ledger, obs)
    two = _append(ledger, obs, search=("新語意策略",))
    assert one.verified_evidence == 1 and two.newly_verified_evidence == 0


@pytest.mark.parametrize("any_term", [False, True])
def test_fallback_evidence_never_claims_topic_validity(any_term):
    hit = _hit(1, "UNRELATED", inner=False)
    hit["_source"]["multidim_event_json"][0]["evidence_snippets"][0]["text"] = (
        "一般非主題描述"
    )
    obs = _observe([hit], effective_terms=["一般"] if any_term else [])
    assert obs.parser_output_rows == 1
    assert obs.fallback_rows == 1
    assert obs.validated_rows == 0
    assert len(obs.verified_evidence) == 0
    assert len(obs.verified_sources) == 0
    ledger = RequestWideEvidenceLedger()
    entry = _append(ledger, obs)
    assert entry.known_sources == entry.verified_evidence == 0
    assert ledger.safe_audit()[0]["candidate_sources"] == 1


def test_partial_or_unattested_round_never_authorizes_more_search_or_sufficient():
    obs = _observe([_hit(1, "A", inner=False)], complete=False)
    ledger = RequestWideEvidenceLedger()
    row = _append(ledger, obs)
    assert row.result_incomplete is True
    assert row.request_wide is True
    with pytest.raises(ValueError, match="round_not_admissible"):
        _append(ledger, obs)
    with pytest.raises(ValueError, match="unattested_coverage"):
        _append(RequestWideEvidenceLedger(), obs, sufficient=True)
    unattested = RequestWideEvidenceLedger()
    record = _append(unattested, _observe([_hit(1, "A", inner=False)]),
                     attested=False)
    assert record.request_wide is False
    planner = AdaptiveRetrievalPlanner(
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not call LLM")
        ),
    )
    scope = QueryConstraints(
        question="甲軸乙軸丙軸",
        event_date=DateWindow(D0, D0, "day", "explicit_user", D0),
        analysis_date=DateWindow(),
        allowed_indexes=("news_test",),
    )
    result = planner.propose_next(
        constraints=scope, history=unattested.history,
        budget=BudgetSnapshot(2, 2, 1800, 600),
    )
    assert result.reason_code == "REQUEST_LEVEL_ASSESSMENT_REQUIRED"


def test_complete_sufficient_request_cannot_append_or_replan():
    ledger = RequestWideEvidenceLedger()
    first = _append(
        ledger, _observe([_hit(1, "A", inner=False)]),
        sufficient=True, missing=(),
    )
    assert first.coverage_sufficient
    with pytest.raises(ValueError, match="round_not_admissible"):
        _append(ledger, _observe([_hit(2, "B", inner=False)]))


def test_reject_untrusted_source_id_or_invalid_receipt_without_mutating_ledger():
    ledger = RequestWideEvidenceLedger()
    hit = _hit(1, "A", inner=False)
    del hit["_id"]
    with pytest.raises(ValueError, match="missing_es_source_identity"):
        _observe([hit])
    good = _observe([_hit(1, "A", inner=False)])
    assert not ledger.history
    with pytest.raises(ValueError, match="unattested_coverage"):
        _append(ledger, good, sufficient=True, attested=False)
    assert not ledger.history


def test_one_request_ledger_never_leaks_raw_identifiers_or_source_text():
    ledger = RequestWideEvidenceLedger()
    row = _append(ledger, _observe([_hit(2, "PRIVATE-ES-ID", inner=False)]))
    assert row.newly_verified_evidence == 2
    metrics = json.dumps(ledger.safe_audit(), ensure_ascii=False)
    for secret in ("PRIVATE-ES-ID", "甲軸", "2023-08-24", "E1", "第0筆"):
        assert secret not in metrics


def test_round_cap_and_invalid_public_receipts_fail_closed():
    ledger = RequestWideEvidenceLedger(max_rounds=1)
    obs = _observe([_hit(1, "A", inner=False)])
    _append(ledger, obs)
    with pytest.raises(ValueError, match="round_not_admissible"):
        _append(ledger, obs)
    with pytest.raises(ValueError, match="invalid_round_observation"):
        RoundObservation(
            candidate_sources=frozenset(), verified_evidence=frozenset(),
            verified_sources=frozenset({"0" * 64}), parser_output_rows=0,
            validated_rows=0, fallback_rows=0, complete=True,
        )



def _structured_observe(events, timeline, *, start="2020-06-18",
                        end="2020-06-18", eids=("E1",)):
    from test_sraf_structured_evidence_time import _hit as time_hit, _snippet
    hit = time_hit(
        events, timeline, [_snippet(list(eids), "重大事件造成影響")],
        article="2009-06-15",
    )
    hit["_id"] = "EVENT-STRUCTURED"
    hit["_index"] = "news_test"
    return observe_canonical_round(
        [hit], date_from=start, date_to=end,
        term_groups=[{"重大事件"}, {"造成"}, {"影響"}],
        effective_terms=["重大事件"],
        query_for_snippet="重大事件造成影響",
        original_question="請分析重大事件造成的影響",
        complete=True,
    )


@pytest.mark.parametrize("stamp,precision,day", [
    ("2020-06-17", "month", "2020-06-18"),
    ("2020-06-17", "year", "2020-12-18"),
    ("2020-06", "month", "2020-06-18"),
    ("2020", "year", "2020-12-18"),
])
def test_coarse_event_precision_remains_valid_without_inventing_a_day(
        stamp, precision, day):
    obs = _structured_observe([
        {"event_id": "E1", "time_iso": stamp,
         "time_precision": precision},
    ], [], start=day, end=day)
    assert obs.parser_output_rows == 1
    assert obs.validated_rows == 1
    assert len(obs.verified_evidence) == 1
    assert obs.fallback_rows == 0
    ledger = RequestWideEvidenceLedger()
    record = _append(ledger, obs)
    assert record.verified_evidence == 1
    assert record.known_sources == 1
    assert "2020-06" not in json.dumps(ledger.safe_audit())


def test_multiple_matched_event_times_are_kept_without_asserting_one_day():
    events = [
        {"event_id": "E1", "time_iso": "2020-06-17",
         "time_precision": "day"},
        {"event_id": "E2", "time_iso": "2020-06-18",
         "time_precision": "day"},
    ]
    obs = _structured_observe(
        events, [], start="2020-06-17", end="2020-06-18",
        eids=("E1", "E2"),
    )
    assert obs.validated_rows == 1
    assert len(obs.verified_evidence) == 1
    assert len(obs.verified_sources) == 1


def test_multiple_events_same_date_in_other_block_do_not_conflate():
    obs = _structured_observe([
        {"event_id": "E1", "time_iso": "2020-06-17",
         "time_precision": "day"},
    ], [], start="2020-06-17", end="2020-06-17")
    assert obs.validated_rows == 1


def test_undated_legacy_topic_evidence_only_when_no_date_filter():
    from test_sraf_structured_evidence_time import _hit as time_hit, _snippet
    hit = time_hit(None, None, [
        _snippet([], "重大事件造成影響")
    ], article=None)
    hit["_id"] = "UNDATED"
    hit["_index"] = "news_test"
    def observe(date_from, date_to):
        return observe_canonical_round(
            [hit], date_from=date_from, date_to=date_to,
            term_groups=[{"重大事件"}, {"造成"}, {"影響"}],
            effective_terms=["重大事件"],
            query_for_snippet="重大事件造成影響",
            original_question="請分析重大事件造成的影響",
            complete=True,
        )
    unbounded = observe(None, None)
    assert unbounded.parser_output_rows == 1
    assert len(unbounded.verified_evidence) == 1
    bounded = observe("2020-06-18", "2020-06-18")
    assert bounded.parser_output_rows == 0
    assert len(bounded.verified_evidence) == 0
