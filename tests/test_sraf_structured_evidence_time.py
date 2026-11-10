"""Offline regressions for SRAF #393: GLM Event/Timeline → Evidence dates.

No ES credentials, network, or live data required.
"""
import json

import pytest

from agent.es.event_time import parse_structured_time, collect_linked_times, query_period_bounds, query_untyped_period_bounds
from agent.es.evidence_core.parser import parse_es_hits
from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.query_body import build_main_query_body
from agent.tools_stats import AggregateMonthQuarter
from agent.utils.citations import compress_evidence, build_citations_from_ev, _build_citations_from_payload
from agent.utils.evidence_pack import pack_ev_for_llm


def _hit(event=None, timeline=None, snippets=None, article="2009-06-15", *, multidim=None):
    block = {"article_title": "事件來源", "article_date_iso": article}
    if event is not None:
        block["Event"] = event
    if timeline is not None:
        block["Event_Timeline"] = timeline
    if snippets is not None:
        block["evidence_snippets"] = snippets
    return {"_source": {"uuid": "doc-a", "multidim_event_json": multidim or [block]}}


def _evidence(hit, start=None, end=None):
    return build_hits_and_evidence(
        [hit], date_from=start, date_to=end, effective_terms=[],
        term_groups=[], query_for_snippet="重大事件",
    )[1]


def _event(eid="E1", when="2008-07-20", precision="day"):
    return {"event_id": eid, "time_iso": when, "time_precision": precision}


def _snippet(eids, text="重大事件造成影響"):
    return {"event_ids": eids, "text": text, "source_id": "S1"}


def test_structured_event_date_beats_different_article_date_and_empty_timeline():
    hit = _hit([_event()], [], [_snippet(["E1"])])
    parsed, _ = parse_es_hits([hit], query_for_snippet="重大事件", config=EvidenceBuildConfig())
    assert parsed[0].citations[0].date_iso == "2008-07-20"
    assert parsed[0].article_date_iso == "2009-06-15"
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    assert len(evidence) == 1
    assert evidence[0]["date_iso"] == "2008-07-20"
    assert evidence[0]["article_date_iso"] == "2009-06-15"
    assert evidence[0]["event_time_candidates"][0]["source"] == "Event"
    assert _evidence(hit, "2009-06-01", "2009-06-30") == []


def test_missing_article_date_is_not_invented_from_structured_event_or_raw_text():
    hit = _hit([_event()], [], [_snippet(["E1"])], article=None)
    hit["_source"]["rawInfo"] = {"content": "2008年7月20日事件相關正文"}
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    assert len(evidence) == 1
    assert evidence[0]["date_iso"] == "2008-07-20"
    assert evidence[0]["article_date_iso"] == ""


def test_text_month_day_cannot_borrow_publication_year_over_structured_event():
    hit = _hit([_event()], [], [_snippet(["E1"], "7月20日發生重大事件")])
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    assert evidence[0]["date_iso"] == "2008-07-20"


def test_two_events_never_choose_first_date_as_exact_day():
    hit = _hit(
        [_event("E1"), _event("E2", "2009-06-15")],
        [],
        [_snippet(["E1", "E2"])],
    )
    for start, end in [("2008-07-01", "2008-07-31"), ("2009-06-01", "2009-06-30")]:
        evidence = _evidence(hit, start, end)
        assert len(evidence) == 1
        assert evidence[0]["date_iso"] == ""
        assert {p["time_iso"] for p in evidence[0]["event_time_candidates"]} == {
            "2008-07-20", "2009-06-15"
        }
    assert _evidence(hit, "2010-01-01", "2010-12-31") == []


def test_date_scoped_document_is_not_retained_without_matching_event_evidence():
    # ES may match Event E1's date while the only Evidence belongs to E2.
    hit = _hit(
        [_event("E1", "2008-07-20"), _event("E2", "2009-06-15")],
        [],
        [_snippet(["E2"], "重大事件造成影響")],
    )
    hits, evidence, _ = build_hits_and_evidence(
        [hit], date_from="2008-07-01", date_to="2008-07-31",
        effective_terms=[], term_groups=[], query_for_snippet="重大事件",
    )
    assert hits == []
    assert evidence == []
    assert _evidence(hit, "2009-06-01", "2009-06-30")[0]["date_iso"] == "2009-06-15"


def test_query_year_filters_evidence_by_its_linked_event_not_other_event_in_document():
    hit = _hit(
        [_event("E1", "2008-07-20"), _event("E2", "2009-06-15")],
        [],
        [_snippet(["E2"], "重大事件造成影響")],
    )
    hits, evidence, _ = build_hits_and_evidence(
        [hit], date_from=None, date_to=None,
        allowed_years={2008}, effective_terms=[], term_groups=[],
        query_for_snippet="2008年重大事件",
    )
    assert hits == []
    assert evidence == []
    _, matching, _ = build_hits_and_evidence(
        [hit], date_from=None, date_to=None,
        allowed_years={2009}, effective_terms=[], term_groups=[],
        query_for_snippet="2009年重大事件",
    )
    assert len(matching) == 1
    assert matching[0]["date_iso"] == "2009-06-15"


def test_dangling_event_id_does_not_fall_back_to_article_date():
    hit = _hit([_event("E2")], [], [_snippet(["E1"])])
    assert _evidence(hit, "2009-06-01", "2009-06-30") == []
    hit["_source"]["multidim_event_json"][0]["evidence_snippets"][0]["text"] = (
        "2008年7月20日發生重大事件"
    )
    assert _evidence(hit, "2008-07-01", "2008-07-31")[0]["date_iso"] == "2008-07-20"


def test_timeline_only_date_is_correlated_by_event_id():
    hit = _hit(
        [], [{"event_ids": ["E1"], "time_iso": "2008-07-20", "time_precision": "day"}],
        [_snippet(["E1"])],
    )
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    assert evidence[0]["date_iso"] == "2008-07-20"
    assert evidence[0]["event_time_candidates"][0]["source"] == "Event_Timeline"


def test_event_and_related_timeline_dates_are_both_searchable_without_fake_exact_day():
    hit = _hit(
        [_event("E1", "2008-07-20")],
        [{"event_ids": ["E1"], "time_iso": "2009-01-01"}],
        [_snippet(["E1"])],
    )
    for start, end in [("2008-07-01", "2008-07-31"), ("2009-01-01", "2009-01-31")]:
        evidence = _evidence(hit, start, end)
        assert len(evidence) == 1
        assert evidence[0]["date_iso"] == ""  # two milestones, no arbitrary single day
        assert {p["source"] for p in evidence[0]["event_time_candidates"]} == {
            "Event", "Event_Timeline"
        }
    assert _evidence(hit, "2010-01-01", "2010-12-31") == []


def test_identical_event_and_timeline_day_is_not_duplicated():
    hit = _hit(
        [_event("E1", "2008-07-20")],
        [{"event_ids": ["E1"], "time_iso": "2008-07-20"}],
        [_snippet(["E1"])],
    )
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    assert evidence[0]["date_iso"] == "2008-07-20"
    assert evidence[0]["event_time_candidates"][0]["source"] == "Event"
    assert len(evidence[0]["event_time_candidates"]) == 1


def test_malformed_timestamp_is_not_assumed_valid():
    assert parse_structured_time("2020-06-17Tnot-a-time", "day", "Event") is None


@pytest.mark.parametrize("when,precision,expected,inside,outside", [
    ("2020-06-17", "year", ("2020", "2020-01-01", "2020-12-31"),
     ("2020-11-10", "2020-11-20"), ("2021-01-01", "2021-12-31")),
    ("2020-06-17", "month", ("2020-06", "2020-06-01", "2020-06-30"),
     ("2020-06-20", "2020-06-29"), ("2020-07-01", "2020-07-31")),
    ("2020-06-17T11:00:00Z", "day", ("2020-06-17", "2020-06-17", "2020-06-17"),
     ("2020-06-17", "2020-06-17"), ("2020-06-18", "2020-06-19")),
])
def test_precision_intersection_without_inventing_day(when, precision, expected, inside, outside):
    point = parse_structured_time(when, precision, "Event")
    assert (point.time_iso, point.start, point.end) == expected
    assert point.overlaps(*inside)
    assert not point.overlaps(*outside)
    hit = _hit([_event(when=when, precision=precision)], [], [_snippet(["E1"])])
    found = _evidence(hit, *inside)
    assert len(found) == 1
    assert found[0]["date_iso"] == (expected[0] if precision == "day" else "")
    assert found[0]["event_time_candidates"][0]["time_precision"] == precision
    assert _evidence(hit, *outside) == []


@pytest.mark.parametrize("when,precision", [
    ("2020-02-30", "day"), ("2020-13", "month"), ("2020-06", "day"),
    ("2020", "month"), ("2020-06-17", "unknown"), ("1899-01-01", "day"),
])
def test_invalid_or_unknown_times_are_not_claimed_exact(when, precision):
    assert parse_structured_time(when, precision, "Event") is None
    hit = _hit([_event(when=when, precision=precision)], [], [_snippet(["E1"])])
    assert _evidence(hit, "2020-01-01", "2020-12-31") == []


@pytest.mark.parametrize("precision,stamp", [
    ("hour", "2026-08-18T05:00:00"),
    ("minute", "2026-08-18T05:04:00"),
    ("second", "2026-08-18T05:04:03+08:00"),
])
def test_valid_subday_times_stay_searchable_and_count_for_the_correct_day(precision, stamp):
    point = parse_structured_time(stamp, precision, "Event")
    assert point is not None and point.precision == precision
    assert point.start == point.end == "2026-08-18"
    hit = _hit([_event(when=stamp, precision=precision)], [], [_snippet(["E1"])])
    found = _evidence(hit, "2026-08-18", "2026-08-18")
    assert found[0]["date_iso"] == "2026-08-18"
    assert AggregateMonthQuarter().forward(found)["day_counts"] == {"2026-08-18": 1}


def test_same_day_distinct_subday_milestones_retained_but_day_count_deduped():
    hit = _hit(
        [_event("E1", "2026-08-18T05:00:00", "hour")],
        [{"event_ids": ["E1"], "time_iso": "2026-08-18T17:00:00",
          "time_precision": "hour"}],
        [_snippet(["E1"])],
    )
    evidence = _evidence(hit, "2026-08-18", "2026-08-18")
    assert len(evidence) == 1
    assert evidence[0]["date_iso"] == ""  # two distinct time points
    assert {p["time_iso"] for p in evidence[0]["event_time_candidates"]} == {
        "2026-08-18T05:00:00", "2026-08-18T17:00:00"
    }
    assert AggregateMonthQuarter().forward(evidence)["day_counts"] == {"2026-08-18": 1}


def test_indexed_utc_offset_does_not_drop_local_calendar_event_day():
    # 2026-08-18 00:42 +08:00 is 2026-08-17 UTC, while -12:00
    # near 23:59 belongs to Aug 19 UTC. ES candidate range must include
    # both; postfilter keeps the original literal's local event date.
    assert query_period_bounds("2026-08-18", "2026-08-18", "minute") == {
        "gte": "2026-08-17", "lt": "2026-08-20",
    }
    for stamp in ("2026-08-18T00:42:00+08:00", "2026-08-18T23:59:00-12:00"):
        hit = _hit([_event(when=stamp, precision="minute")], [], [_snippet(["E1"])])
        evidence = _evidence(hit, "2026-08-18", "2026-08-18")
        assert evidence[0]["date_iso"] == "2026-08-18"
        assert evidence[0]["event_time_candidates"][0]["time_iso"] == stamp
        assert _evidence(hit, "2026-08-17", "2026-08-17") == []


def test_empty_legacy_precision_infers_day_without_dropping_event():
    hit = _hit([_event(when="2026-08-18", precision="")], [], [_snippet(["E1"])])
    assert _evidence(hit, "2026-08-18", "2026-08-18")[0]["date_iso"] == "2026-08-18"
    body = _query(date_from="2026-08-18", date_to="2026-08-18")
    assert '"time_precision": ""' in str(body) or "time_precision': ''" in str(body)


def test_json_block_shapes_and_stable_ids():
    hit = _hit(multidim=json.dumps([{
        "article_date_iso": "2009-06-15",
        "Event": {"event_id": "E1", "time_iso": "2008-07-20"},
        "evidence_snippets": {"event_ids": "E1", "text": "重大事件造成影響"},
    }], ensure_ascii=False))
    assert _evidence(hit, "2008-07-01", "2008-07-31")[0]["date_iso"] == "2008-07-20"


@pytest.mark.parametrize("inferred", [None, ""])
def test_legacy_timestamp_without_precision_gets_canonical_second(inferred):
    stamp = "2020-06-17T11:00:00Z"
    point = parse_structured_time(stamp, inferred, "Event")
    assert point is not None and point.precision == "second"
    hit = _hit([_event(when=stamp, precision=inferred)], [], [_snippet(["E1"])])
    evidence = _evidence(hit, "2020-06-17", "2020-06-17")
    assert evidence[0]["date_iso"] == "2020-06-17"
    assert evidence[0]["event_time_candidates"][0]["time_precision"] == "second"
    assert AggregateMonthQuarter().forward(evidence)["day_counts"] == {"2020-06-17": 1}


def test_unknown_structured_event_never_counts_article_as_an_event_day():
    hit = _hit([_event("E2")], [], [_snippet(["E1"])])
    evidence = _evidence(hit)
    assert evidence[0]["date_iso"] == ""
    assert evidence[0]["article_date_iso"] == "2009-06-15"
    assert AggregateMonthQuarter().forward(evidence)["day_counts"] == {}
    assert AggregateMonthQuarter().forward(evidence)["doc_count"] == 0


def test_legacy_no_structured_event_keeps_publication_date_fallback():
    hit = _hit(snippets=[_snippet(["E1"])])
    assert _evidence(hit, "2009-06-01", "2009-06-30")[0]["date_iso"] == "2009-06-15"


def test_multiblock_duplicate_id_source_evidence_stays_in_its_own_block():
    first = {"Event": [_event("E1", "2008-07-20")], "evidence_snippets": [_snippet(["E1"])]}
    second = {"Event": [_event("E1", "2009-06-15")]}
    hit = _hit(multidim=[first, second])
    found = _evidence(hit, "2008-07-01", "2008-07-31")
    assert len(found) == 1
    assert found[0]["date_iso"] == "2008-07-20"
    assert _evidence(hit, "2009-06-01", "2009-06-30") == []
    parsed, _ = parse_es_hits([hit], query_for_snippet="重大事件", config=EvidenceBuildConfig())
    assert parsed[0].citations[0].block_index == 0
    assert len(parsed[0].citations[0].linked_times) == 1


def test_multiblock_inner_hit_without_origin_must_not_cross_join_reused_id():
    hit = _hit(multidim=[
        {"Event": [_event("E1", "2008-07-20")]},
        {"Event": [_event("E1", "2009-06-15")]},
    ])
    hit["inner_hits"] = {"evi": {"hits": {"hits": [{
        "_source": {"text": "重大事件造成影響", "event_ids": ["E1"]}
    }]}}}
    assert _evidence(hit, "2008-07-01", "2008-07-31") == []
    assert _evidence(hit, "2009-06-01", "2009-06-30") == []


def test_merged_394_undated_reused_id_cannot_borrow_another_blocks_date():
    # PR #394 Codex P1: no parent offset, E1 exists in both blocks,
    # but only one has a valid date. This is NOT a globally unique E1.
    hit = _hit(multidim=[
        {"Event": [{"event_id": "E1", "time_iso": None}]},
        {"Event": [_event("E1", "2025-06-15")]},
    ])
    hit["inner_hits"] = {"evi": {"hits": {"hits": [{
        "_source": {"text": "救援進展", "event_ids": ["E1"]}
    }]}}}
    parsed, _ = parse_es_hits(
        [hit], query_for_snippet="救援", config=EvidenceBuildConfig()
    )
    assert parsed[0].citations[0].linked_times == []
    assert _evidence(hit, "2025-06-01", "2025-06-30") == []


def test_merged_394_unlocated_inner_hit_cannot_mix_ids_from_different_blocks():
    hit = _hit(multidim=[
        {"Event": [_event("E1", "2025-06-15")]},
        {"Event": [_event("E2", "2025-06-16")]},
    ])
    hit["inner_hits"] = {"evi": {"hits": {"hits": [{
        "_source": {"text": "救援進展", "event_ids": ["E1", "E2"]}
    }]}}}
    assert _evidence(hit, "2025-06-01", "2025-06-30") == []


def test_multiblock_inner_hit_with_offset_uses_correct_parent_event():
    hit = _hit(multidim=[
        {"Event": [_event("E1", "2008-07-20")]},
        {"Event": [_event("E1", "2009-06-15")]},
    ])
    hit["inner_hits"] = {"evi": {"hits": {"hits": [{
        "_nested": {"field": "multidim_event_json", "offset": 1,
                    "_nested": {"field": "evidence_snippets", "offset": 0}},
        "_source": {"text": "重大事件造成影響", "event_ids": ["E1"]}
    }]}}}
    matched = _evidence(hit, "2009-06-01", "2009-06-30")
    assert len(matched) == 1
    assert matched[0]["date_iso"] == "2009-06-15"
    assert _evidence(hit, "2008-07-01", "2008-07-31") == []


def test_multiblock_identical_id_and_date_keeps_link():
    block = {"Event": [_event("E1", "2008-07-20")], "evidence_snippets": [_snippet(["E1"])]}
    hit = _hit(multidim=[block, {"Event": [_event("E1", "2008-07-20")]}])
    assert _evidence(hit, "2008-07-01", "2008-07-31")[0]["date_iso"] == "2008-07-20"


def test_aggregate_counts_actual_event_date_not_article_publication_date():
    hit = _hit([_event()], [], [_snippet(["E1"])])
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    assert evidence[0]["article_date_iso"] == "2009-06-15"
    stats = AggregateMonthQuarter().forward(evidence)
    assert stats["day_counts"] == {"2008-07-20": 1}
    assert stats["month_counts"] == {"2008-07": 1}
    assert stats["quarter_counts"] == {"2008-Q3": 1}


def test_aggregate_uses_only_query_matched_milestones_not_all_linked_dates():
    hit = _hit(
        [_event("E1", "2008-07-20")],
        [{"event_ids": ["E1"], "time_iso": "2009-01-01"}],
        [_snippet(["E1"])],
    )
    selected = _evidence(hit, "2008-07-01", "2008-07-31")
    assert len(selected[0]["event_time_candidates"]) == 2
    assert len(selected[0]["matched_event_time_candidates"]) == 1
    assert AggregateMonthQuarter().forward(selected)["day_counts"] == {"2008-07-20": 1}
    unfiltered = _evidence(hit)
    assert AggregateMonthQuarter().forward(unfiltered)["day_counts"] == {
        "2008-07-20": 1, "2009-01-01": 1
    }


def test_month_precision_never_gets_counted_as_first_day_of_month():
    hit = _hit([_event(when="2020-06-17", precision="month")], [], [_snippet(["E1"])])
    evidence = _evidence(hit, "2020-06-01", "2020-06-30")
    assert evidence[0]["date_iso"] == ""
    stats = AggregateMonthQuarter().forward(evidence)
    assert stats["snippet_count"] == 1
    assert stats["day_counts"] == {}
    assert stats["doc_count"] == 0


def test_legacy_aggregator_prefers_explicit_evidence_date_over_article_date():
    stats = AggregateMonthQuarter().forward([{
        "uuid": "old", "date_iso": "2008-07-20", "article_date_iso": "2009-06-15"
    }])
    assert stats["day_counts"] == {"2008-07-20": 1}


@pytest.mark.parametrize("when,precision,display", [
    ("2020-06-17", "year", "2020"),
    ("2020-06-17", "month", "2020-06"),
])
def test_report_compression_preserves_partial_precision_not_article_day(when, precision, display):
    hit = _hit([_event(when=when, precision=precision)], [], [_snippet(["E1"])])
    evidence = _evidence(hit, "2020-06-01", "2020-06-30")
    compact = compress_evidence(evidence)
    assert compact[0]["d"] == display
    assert compact[0]["tp"] == precision
    packed = pack_ev_for_llm(compact, "年度事件整理", mode="rules")
    assert packed["ev_slim"][0]["tp"] == precision
    assert len(packed["ev_slim"][0]["times"]) == 1
    citations = build_citations_from_ev(compact)
    assert citations[0]["date_iso"] is None
    assert citations[0]["date_precision"] == precision
    assert citations[0]["event_time_candidates"][0]["date_start"] == (
        "2020-01-01" if precision == "year" else "2020-06-01"
    )
    payload_citations = _build_citations_from_payload({"evidence_snippets": evidence, "ev": compact})
    assert payload_citations[0]["date_iso"] is None


def test_report_compression_does_not_use_article_date_for_multiple_linked_dates():
    hit = _hit([_event("E1")], [
        {"event_ids": ["E1"], "time_iso": "2008-08-01"}
    ], [_snippet(["E1"])])
    evidence = _evidence(hit)
    compact = compress_evidence(evidence)
    assert compact[0]["d"] is None
    assert compact[0]["tp"] == "multiple"
    assert len(compact[0]["times"]) == 2
    packed = pack_ev_for_llm(compact, "時間軸", mode="rules")
    assert len(packed["ev_slim"][0]["times"]) == 2
    assert build_citations_from_ev(compact)[0]["date_iso"] is None


def test_report_compression_structured_dangling_link_does_not_borrow_article_date():
    hit = _hit([_event("E2")], [], [_snippet(["E1"])])
    evidence = _evidence(hit)
    assert evidence[0]["date_iso"] == ""
    assert evidence[0]["structured_time_context"] is True
    compact = compress_evidence(evidence)
    assert compact[0]["d"] is None
    assert compact[0]["tp"] == "unknown"
    assert build_citations_from_ev(compact)[0]["date_iso"] is None


def test_explicit_complete_evidence_date_survives_report_without_borrowing_article():
    hit = _hit([_event("E2")], [], [_snippet(["E1"], "2008年7月20日發生重大事件")])
    evidence = _evidence(hit, "2008-07-01", "2008-07-31")
    compact = compress_evidence(evidence)
    assert compact[0]["d"] == "2008-07-20"
    assert compact[0]["tp"] == "day"
    assert compact[0]["times"][0]["source"] == "evidence_text"
    assert build_citations_from_ev(compact)[0]["date_iso"] == "2008-07-20"


def test_report_compression_precise_date_remains_exact():
    hit = _hit([_event("E1")], [], [_snippet(["E1"])])
    evidence = _evidence(hit)
    compact = compress_evidence(evidence)
    assert compact[0]["d"] == "2008-07-20"
    assert compact[0]["tp"] == "day"
    assert build_citations_from_ev(compact)[0]["date_iso"] == "2008-07-20"


def _query(**overrides):
    params = dict(
        query="重大事件", must_high_value=False, must_selected=False, size=10,
        date_from="2008-07-10", date_to="2008-07-20",
        selected_boost=6.0, high_value_boost=2.5,
        recency_boost=False, recency_field="importDT", recency_scale="30d",
    )
    params.update(overrides)
    return build_main_query_body(**params)


def test_es_date_filter_uses_both_nested_children_and_retrieves_structured_event():
    body = _query()
    assert "multidim_event_json.Event" in body["_source"]
    assert "multidim_event_json.Event_Timeline" in body["_source"]
    clause = body["query"]["function_score"]["query"]["bool"]["filter"][0]
    outer = clause["nested"]
    assert outer["path"] == "multidim_event_json"
    children = outer["query"]["bool"]["should"]
    assert {child["nested"]["path"] for child in children} == {
        "multidim_event_json.Event", "multidim_event_json.Event_Timeline"
    }
    assert all(child["nested"]["query"]["bool"]["minimum_should_match"] == 1
               for child in children)
    assert outer["query"]["bool"]["minimum_should_match"] == 1
    assert query_period_bounds("2008-07-10", "2008-07-20", "day") == {
        "gte": "2008-07-10", "lt": "2008-07-21"
    }
    assert query_period_bounds("2008-07-10", "2008-07-20", "month") == {
        "gte": "2008-07-01", "lt": "2008-08-01"
    }
    assert query_period_bounds("2008-07-10", "2008-07-20", "year") == {
        "gte": "2008-01-01", "lt": "2009-01-01"
    }


def test_year_in_query_uses_same_dual_source_filter():
    body = _query(query="2008年重大事件", date_from=None, date_to=None)
    filters = body["query"]["function_score"]["query"]["bool"]["filter"]
    assert len(filters) == 1
    assert len(filters[0]["bool"]["should"]) == 1
    assert "multidim_event_json.Event.time_iso" in str(filters)
    assert "multidim_event_json.Event_Timeline.time_iso" in str(filters)


def test_merged_394_395_legacy_missing_precision_utc_candidate_bounds():
    # Codex P2: explicit precision had been fixed but missing/empty legacy
    # time_precision still queried a narrow UTC day. Both need an expanded
    # candidate range; Evidence then verifies the original local day.
    body = _query(date_from="2026-08-18", date_to="2026-08-18")
    first = body["query"]["function_score"]["query"]["bool"]["filter"][0]
    children = first["nested"]["query"]["bool"]["should"]
    for child in children:
        by_precision = child["nested"]["query"]["bool"]["should"]
        legacy_cases = [
            entry for entry in by_precision
            if isinstance(entry, dict)
            and "bool" in entry
            and any(
                isinstance(filt, dict) and "bool" in filt
                and {"term", "bool"} <= {next(iter(i)) for i in filt["bool"]["should"]}
                for filt in entry["bool"].get("filter", [])
            )
        ]
        assert len(legacy_cases) == 1
        date_filter = legacy_cases[0]["bool"]["filter"][1]
        field = child["nested"]["path"] + ".time_iso"
        assert date_filter == {"range": {
            field: {"gte": "2025-12-31", "lt": "2027-01-02"}
        }}

    for declared in (None, ""):
        for stamp in ("2026-08-18T00:42:00+08:00",
                      "2026-08-18T23:59:00-12:00"):
            hit = _hit([_event(when=stamp, precision=declared)], [], [_snippet(["E1"])])
            evidence = _evidence(hit, "2026-08-18", "2026-08-18")
            assert len(evidence) == 1
            assert evidence[0]["date_iso"] == "2026-08-18"
            assert evidence[0]["event_time_candidates"][0]["time_precision"] == "second"


@pytest.mark.parametrize("value,expected_precision,expected_start", [
    ("2020", "year", "2020-01-01"),
    ("2020-06", "month", "2020-06-01"),
])
@pytest.mark.parametrize("missing_precision", [None, ""])
def test_merged_394_395_legacy_untyped_partial_interval_is_retrieved(
    value, expected_precision, expected_start, missing_precision
):
    # Review P2: widening just ±one day around June 17 loses old ISO
    # year/month values indexed at Jan 1/June 1. The candidate query must
    # cover those stored instants, while postfilter uses actual precision.
    bounds = query_untyped_period_bounds("2020-06-17", "2020-06-17")
    assert bounds == {"gte": "2019-12-31", "lt": "2021-01-02"}
    assert bounds["gte"] <= expected_start < bounds["lt"]
    hit = _hit([_event("E1", value, missing_precision)], [], [_snippet(["E1"])])
    evidence = _evidence(hit, "2020-06-17", "2020-06-17")
    assert len(evidence) == 1
    assert evidence[0]["date_iso"] == ""
    assert evidence[0]["event_time_candidates"][0]["time_precision"] == expected_precision
    assert AggregateMonthQuarter().forward(evidence)["day_counts"] == {}
    assert _evidence(hit, "2021-06-17", "2021-06-17") == []


def test_merged_394_parenthesized_day_with_two_distinct_months_is_ambiguous():
    # PR #394 Codex P2: March 1 and June 1 must not be resolved to
    # whichever matching "(1)日" comes first. Both dated milestones remain.
    hit = _hit(
        [_event("E1", "2025-03-01", "day")],
        [{"event_ids": ["E1"], "time_iso": "2025-06-01", "time_precision": "day"}],
        [_snippet(["E1"], "今(1)日救援進展")],
        article="2026-08-01",
    )
    june = _evidence(hit, "2025-06-01", "2025-06-30")
    assert len(june) == 1
    assert june[0]["date_iso"] == ""
    assert {p["time_iso"] for p in june[0]["event_time_candidates"]} == {
        "2025-03-01", "2025-06-01"
    }
    assert [p["time_iso"] for p in june[0]["matched_event_time_candidates"]] == [
        "2025-06-01"
    ]
    assert AggregateMonthQuarter().forward(june)["day_counts"] == {"2025-06-01": 1}
    assert _evidence(hit, "2025-07-01", "2025-07-31") == []


def test_merged_394_reused_id_in_second_block_source_evidence_is_local():
    hit = _hit(multidim=[
        {"Event": [_event("E1", "2025-07-02")],
         "evidence_snippets": [_snippet(["E1"], "七月資料")]},
        {"Event": [_event("E1", "2025-06-02")],
         "evidence_snippets": [_snippet(["E1"], "六月資料")]},
    ])
    june = _evidence(hit, "2025-06-01", "2025-06-30")
    assert len(june) == 1
    assert june[0]["text"] == "六月資料"
    assert june[0]["date_iso"] == "2025-06-02"
    july = _evidence(hit, "2025-07-01", "2025-07-31")
    assert len(july) == 1
    assert july[0]["text"] == "七月資料"


def test_merged_394_parenthesized_day_cannot_convert_year_into_first_january():
    hit = _hit([_event("E1", "2020", "year")], [], [
        _snippet(["E1"], "今(1)日展開救援")
    ], article="2026-08-01")
    june = _evidence(hit, "2020-06-01", "2020-06-30")
    assert len(june) == 1
    assert june[0]["date_iso"] == ""
    assert june[0]["event_time_candidates"][0]["time_precision"] == "year"
    assert june[0]["event_time_candidates"][0]["date_start"] == "2020-01-01"
    assert june[0]["matched_event_time_candidates"][0]["date_end"] == "2020-12-31"


def test_no_date_query_has_no_date_filter_and_preserves_fallback_fields():
    body = _query(query="重大事件", date_from=None, date_to=None)
    assert not body["query"]["function_score"]["query"]["bool"]["filter"]
