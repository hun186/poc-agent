"""Offline regressions for SRAF #393: GLM Event/Timeline → Evidence dates.

No ES credentials, network, or live data required.
"""
import json

import pytest

from agent.es.event_time import parse_structured_time, collect_linked_times, query_period_bounds
from agent.es.evidence_core.parser import parse_es_hits
from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.query_body import build_main_query_body


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


def test_json_block_shapes_and_stable_ids():
    hit = _hit(multidim=json.dumps([{
        "article_date_iso": "2009-06-15",
        "Event": {"event_id": "E1", "time_iso": "2008-07-20"},
        "evidence_snippets": {"event_ids": "E1", "text": "重大事件造成影響"},
    }], ensure_ascii=False))
    assert _evidence(hit, "2008-07-01", "2008-07-31")[0]["date_iso"] == "2008-07-20"


def test_legacy_no_structured_event_keeps_publication_date_fallback():
    hit = _hit(snippets=[_snippet(["E1"])])
    assert _evidence(hit, "2009-06-01", "2009-06-30")[0]["date_iso"] == "2009-06-15"


def test_multiblock_duplicate_id_preserves_ambiguity():
    first = {"Event": [_event("E1", "2008-07-20")], "evidence_snippets": [_snippet(["E1"])]}
    second = {"Event": [_event("E1", "2009-06-15")]}
    hit = _hit(multidim=[first, second])
    found = _evidence(hit, "2008-07-01", "2008-07-31")
    assert len(found) == 1
    assert found[0]["date_iso"] == ""
    assert len(found[0]["event_time_candidates"]) == 2


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


def test_no_date_query_has_no_date_filter_and_preserves_fallback_fields():
    body = _query(query="重大事件", date_from=None, date_to=None)
    assert not body["query"]["function_score"]["query"]["bool"]["filter"]
