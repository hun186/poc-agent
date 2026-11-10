"""Event/Timeline temporal retrieval contract (no real ES, SQL or LLM calls)."""
from __future__ import annotations

import json

from agent.es.date_filters import dual_event_date_filter
from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.parser import parse_es_hits
from agent.es.temporal import parse_temporal_interval
from agent.es.query_body import build_main_query_body


def _body(**overrides):
    kwargs = dict(query="救援", must_high_value=False, must_selected=False,
                  size=10, date_from=None, date_to=None, selected_boost=None,
                  high_value_boost=None, recency_boost=False,
                  recency_field=None, recency_scale=None)
    kwargs.update(overrides)
    return build_main_query_body(**kwargs)


def _snippets(md, start="2025-06-01", end="2025-06-30"):
    hit = {"_source": {
        "uuid": "doc-1",
        "rawInfo": {"content": "事件完整報導"},
        "multidim_event_json": md,
    }}
    return build_hits_and_evidence([hit], date_from=start, date_to=end,
                                   effective_terms=[], term_groups=[],
                                   query_for_snippet="事件")[1]


def _date_filter(body):
    return body["query"]["function_score"]["query"]["bool"]["filter"]


def test_event_and_timeline_date_are_both_nested_and_outer_scoped():
    query = dual_event_date_filter("2025-06-10", "2025-06-20")
    assert query["bool"]["minimum_should_match"] == 1
    assert len(query["bool"]["should"]) == 2
    for clause, child in zip(query["bool"]["should"], ("Event", "Event_Timeline")):
        parent = clause["nested"]
        assert parent["path"] == "multidim_event_json"
        assert parent["score_mode"] == "none"
        inner = parent["query"]["nested"]
        assert inner["path"] == f"multidim_event_json.{child}"
        assert inner["score_mode"] == "none"
        assert inner["query"]["bool"]["minimum_should_match"] == 1
        cases = inner["query"]["bool"]["should"]
        field = f"multidim_event_json.{child}.time_iso"
        precision = f"multidim_event_json.{child}.time_precision"
        assert cases[0] == {"range": {field: {"gte": "2025-06-10", "lt": "2025-06-21"}}}
        assert cases[1]["bool"]["filter"] == [
            {"term": {precision: "month"}},
            {"range": {field: {"gte": "2025-06-01", "lt": "2025-07-01"}}},
        ]
        assert cases[2]["bool"]["filter"] == [
            {"term": {precision: "year"}},
            {"range": {field: {"gte": "2025-01-01", "lt": "2026-01-01"}}},
        ]


def test_explicit_year_only_years_in_question_and_undated_paths():
    explicit = _body(date_from="2025-06-15", date_to="2025-06-20")
    assert len(_date_filter(explicit)) == 1
    assert "multidim_event_json.Event.time_iso" in json.dumps(_date_filter(explicit))
    assert "multidim_event_json.Event_Timeline.time_iso" in json.dumps(_date_filter(explicit))
    assert "multidim_event_json.Event" in explicit["_source"]
    assert "multidim_event_json.Event_Timeline" in explicit["_source"]

    years = _body(query="2023 或 2025 年救援")
    assert len(_date_filter(years)) == 1
    assert len(_date_filter(years)[0]["bool"]["should"]) == 2
    assert "2023-01-01" in json.dumps(_date_filter(years))
    assert "2025-12-31" not in json.dumps(_date_filter(years))
    assert "2026-01-01" in json.dumps(_date_filter(years))

    assert _date_filter(_body()) == []
    assert _date_filter(_body(query="2025 年救援", with_date=False)) == []
    assert dual_event_date_filter("2025-07-01", "2025-06-01") == {"match_none": {}}


def test_calendar_parsing_handles_partial_periods_leap_year_invalid_and_unknown():
    assert (parse_temporal_interval("2020", "year").start.isoformat(),
            parse_temporal_interval("2020", "year").end.isoformat()) == (
                "2020-01-01", "2020-12-31")
    assert (parse_temporal_interval("2020-02-29", "month").start.isoformat(),
            parse_temporal_interval("2020-02-29", "month").end.isoformat()) == (
                "2020-02-01", "2020-02-29")
    assert parse_temporal_interval("2020-02-29T15:00:00Z").precision == "day"
    assert parse_temporal_interval("2020-02").precision == "month"
    assert parse_temporal_interval("2020-02-30", "year") is None
    assert parse_temporal_interval("2021-02-29", "day") is None
    assert parse_temporal_interval("n/a") is None
    assert parse_temporal_interval("2020-07-05", "unknown").precision == "day"


def test_event_only_timeline_empty_keeps_evidence_even_when_article_is_outside():
    rows = _snippets([{
        "article_date_iso": "2026-08-01",
        "Event": [{"event_id": "E1", "time_iso": "2025-06-12", "time_precision": "day"}],
        "Event_Timeline": [],
        "evidence_snippets": [{"text": "救援行動已展開", "event_ids": ["E1"]}],
    }])
    assert len(rows) == 1
    assert rows[0]["date_iso"] == "2025-06-12"
    assert rows[0]["article_date_iso"] == "2026-08-01"
    assert rows[0]["event_ids"] == ["E1"]


def test_independent_events_do_not_cross_date_filter_or_invent_other_event_day():
    rows = _snippets([{
        "article_date_iso": "2026-10-01",
        "Event": [
            {"event_id": "E1", "time_iso": "2025-06-12", "time_precision": "day"},
            {"event_id": "E2", "time_iso": "2025-07-15", "time_precision": "day"},
        ],
        "evidence_snippets": [
            {"event_ids": ["E1"], "text": "六月救援"},
            {"event_ids": ["E2"], "text": "七月後續"},
            {"text": "無法對應單一事件的背景資料"},
        ],
    }])
    assert [r["text"] for r in rows] == ["六月救援", "無法對應單一事件的背景資料"]
    assert rows[0]["date_iso"] == "2025-06-12"
    assert rows[1]["date_iso"] == ""
    assert rows[1]["weak_evidence"] is True


def test_linked_timeline_can_match_when_same_core_event_date_does_not():
    rows = _snippets([{
        "article_date_iso": "2026-01-01",
        "Event": [{"event_id": "E1", "time_iso": "2025-03-01", "time_precision": "day"}],
        "Event_Timeline": [{"event_ids": ["E1"], "time_iso": "2025-06-20", "time_precision": "day"}],
        "evidence_snippets": [{"event_ids": ["E1"], "text": "階段性進展"}],
    }])
    assert len(rows) == 1
    assert rows[0]["date_iso"] == "2025-06-20"


def test_block_local_event_links_and_reused_event_id_are_not_crossed():
    rows = _snippets([
        {"Event": [{"event_id": "E1", "time_iso": "2025-07-02"}],
         "evidence_snippets": [{"event_ids": ["E1"], "text": "七月資料"}]},
        {"Event": [{"event_id": "E1", "time_iso": "2025-06-02"}],
         "evidence_snippets": [{"event_ids": ["E1"], "text": "六月資料"}]},
    ])
    assert [r["text"] for r in rows] == ["六月資料"]
    assert rows[0]["date_iso"] == "2025-06-02"


def test_year_month_precision_intersect_but_do_not_fabricate_day():
    rows = _snippets([{
        "Event": [
            {"event_id": "E1", "time_iso": "2020", "time_precision": "year"},
            {"event_id": "E2", "time_iso": "2020-06", "time_precision": "month"},
        ],
        "evidence_snippets": [
            {"event_ids": ["E1"], "text": "年度分析"},
            {"event_ids": ["E2"], "text": "月度分析"},
        ],
    }], "2020-06-15", "2020-06-20")
    assert len(rows) == 2
    assert rows[0]["date_iso"] == ""
    assert rows[0]["event_time_precision"] == "year"
    assert rows[0]["event_time_start_iso"] == "2020-01-01"
    assert rows[0]["event_time_end_iso"] == "2020-12-31"
    assert rows[1]["date_iso"] == ""
    assert rows[1]["event_time_precision"] == "month"
    assert rows[1]["event_time_end_iso"] == "2020-06-30"


def test_explicit_snippet_date_precedes_event_date_and_legacy_article_only_remains():
    doc = [{
        "article_date_iso": "2026-07-01",
        "Event": [{"event_id": "E1", "time_iso": "2025-06-03"}],
        "evidence_snippets": [{"event_ids": ["E1"], "text": "報導指出2025年6月15日正式發布"}],
    }]
    rows = _snippets(doc)
    assert rows[0]["date_iso"] == "2025-06-15"
    old = _snippets([{
        "article_date_iso": "2025-06-20",
        "evidence_snippets": [{"event_ids": ["E1"], "text": "舊文資料"}],
    }])
    assert old[0]["date_iso"] == "2025-06-20"


def test_no_fake_article_date_from_timeline_and_absent_temporal_rows():
    hit = {"_source": {
        "uuid": "doc",
        "multidim_event_json": [{
            "Event_Timeline": [{"event_ids": ["E1"], "time_iso": "2025-06-20"}],
            "evidence_snippets": [{"event_ids": ["E1"], "text": "查明日期"}],
        }],
    }}
    parsed, _ = parse_es_hits([hit], query_for_snippet="查明", config=EvidenceBuildConfig())
    assert parsed[0].article_date_iso is None
    assert parsed[0].citations[0].linked_dates[0].interval.iso == "2025-06-20"


def test_stat_aggregation_uses_linked_event_day_before_publication_day():
    from agent.tools_stats import AggregateMonthQuarter

    evidence = _snippets([{
        "article_date_iso": "2026-08-03",
        "Event": [{"event_id": "E1", "time_iso": "2025-06-12", "time_precision": "day"}],
        "evidence_snippets": [{"event_ids": ["E1"], "text": "事件當日救援"}],
    }])
    stats = AggregateMonthQuarter().forward(evidence_snippets=evidence)
    assert stats["day_counts"] == {"2025-06-12": 1}
    assert stats["month_counts"] == {"2025-06": 1}
    assert stats["active_days"] == 1


def test_statistics_never_turn_coarse_or_unresolved_event_dates_into_pub_days():
    from agent.tools_stats import AggregateMonthQuarter

    evidence = _snippets([{
        "article_date_iso": "2026-08-03",
        "Event": [{"event_id": "E1", "time_iso": "2025", "time_precision": "year"}],
        "evidence_snippets": [
            {"event_ids": ["E1"], "text": "全年事件"},
            {"text": "沒有事件關聯的說明"},
        ],
    }])
    assert evidence[0]["event_time_precision"] == "year"
    assert evidence[0]["date_iso"] == ""
    assert evidence[1]["event_time_unresolved"] is True
    result = AggregateMonthQuarter().forward(evidence_snippets=evidence)
    assert result["snippet_count"] == 2
    assert result["doc_count"] == 0
    assert result["active_days"] == 0
    assert result["day_counts"] == {}
