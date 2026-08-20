from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.parser import parse_es_hits
from agent.es.query_body import build_main_query_body
from agent.es.mock_es_client import MAPPING, MOCK_INDEX
from agent.tools_stats import AggregateMonthQuarter
from agent.tools_es.timeline import ESTimeline


def _body(**kwargs):
    defaults = dict(
        query="颱風救援",
        must_high_value=False,
        must_selected=False,
        size=10,
        date_from="2026-08-01",
        date_to="2026-08-31",
        selected_boost=6.0,
        high_value_boost=2.5,
        recency_boost=False,
        recency_field="importDT",
        recency_scale="30d",
    )
    defaults.update(kwargs)
    return build_main_query_body(**defaults)


def _nested_paths(value):
    paths = []
    if isinstance(value, dict):
        nested = value.get("nested")
        if isinstance(nested, dict) and nested.get("path"):
            paths.append(nested["path"])
        for child in value.values():
            paths.extend(_nested_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.extend(_nested_paths(child))
    return paths


def test_query_enters_outer_and_child_nested_paths_and_uses_new_timeline_fields():
    body = _body()
    paths = _nested_paths(body["query"])

    assert "multidim_event_json" in paths
    assert "multidim_event_json.Event" in paths
    assert "multidim_event_json.Event_Timeline" in paths
    assert "multidim_event_json.evidence_snippets" in paths

    rendered = str(body)
    assert "multidim_event_json.Event_Timeline.time_iso" in rendered
    assert "multidim_event_json.Event_Timeline.date_iso" not in rendered
    sort_nested = body["sort"][1]["multidim_event_json.Event_Timeline.time_iso"]["nested"]
    assert sort_nested["path"] == "multidim_event_json"
    assert sort_nested["nested"]["path"] == "multidim_event_json.Event_Timeline"


def test_mock_mapping_matches_production_nested_paths_and_timeline_names():
    mdj = MAPPING[MOCK_INDEX]["mappings"]["properties"]["multidim_event_json"]

    assert mdj["type"] == "nested"
    for name in ("Event", "Event_Timeline", "Person", "Involved_Parties", "evidence_snippets"):
        assert mdj["properties"][name]["type"] == "nested"
    timeline = mdj["properties"]["Event_Timeline"]["properties"]
    assert {"time_iso", "time_raw", "time_precision"} <= timeline.keys()
    assert not {"date_iso", "date_raw", "date_precision"} & timeline.keys()


def test_parser_reads_multilevel_inner_hits_and_preserves_event_links():
    hits = [{
        "_source": {
            "uuid": "doc-1",
            "multidim_event_json": [{
                "article_title": "測試",
                "article_date_iso": "2026-08-20",
                "Event_Timeline": [{"event_ids": ["evt-1"], "time_iso": "2026-08-18"}],
            }],
        },
        "inner_hits": {
            "event_block": {"hits": {"hits": [{
                "inner_hits": {"evi": {"hits": {"hits": [{
                    "_source": {
                        "text": "救援行動已展開",
                        "source_id": "src-1",
                        "event_ids": ["evt-1"],
                    }
                }]}}}
            }]}}
        },
    }]

    parsed, stats = parse_es_hits(
        hits,
        query_for_snippet="救援",
        config=EvidenceBuildConfig(),
    )

    assert stats["n_inner_used"] == 1
    assert parsed[0].article_date_iso == "2026-08-20"
    assert parsed[0].event_dates == ["2026-08-18"]
    assert parsed[0].citations[0].event_ids == ["evt-1"]


def _source_evidence_hit(multidim_event_json):
    return {
        "_source": {
            "uuid": "demo1",
            "communication": {"subject": "福隆12號"},
            "multidim_event_json": multidim_event_json,
        }
    }


def test_parser_uses_source_evidence_when_evi_inner_hits_are_absent():
    hit = _source_evidence_hit([{
        "article_title": "福隆12號高雄港刺網捕撈虱目魚作業紀錄",
        "article_date_iso": "2026-06-23",
        "Event_Timeline": [{"event_ids": ["E1"], "time_iso": "2026-06-23T00:00:00.000Z"}],
        "evidence_snippets": [{
            "event_ids": ["E1"],
            "text": "福隆12號今日自高雄港出港，以刺網捕撈虱目魚。",
        }],
    }])

    parsed, stats = parse_es_hits([hit], query_for_snippet="福隆12號", config=EvidenceBuildConfig())

    assert len(parsed) == 1
    assert len(parsed[0].citations) == 1
    assert "福隆12號今日自高雄港出港" in parsed[0].citations[0].text
    assert parsed[0].citations[0].event_ids == ["E1"]
    assert stats["n_source_evidence_used"] == 1
    assert stats["n_fallback_used"] == 0


def test_parser_prefers_inner_hits_without_duplicating_source_evidence():
    hit = _source_evidence_hit({
        "article_date_iso": "2026-06-23",
        "evidence_snippets": [{"event_ids": ["source"], "text": "source evidence"}],
    })
    hit["inner_hits"] = {"evi": {"hits": {"hits": [{
        "_source": {"event_ids": ["inner"], "text": "inner evidence"}
    }]}}}

    parsed, stats = parse_es_hits([hit], query_for_snippet="evidence", config=EvidenceBuildConfig())

    assert [citation.text for citation in parsed[0].citations] == ["inner evidence"]
    assert stats["n_inner_used"] == 1
    assert stats["n_source_evidence_used"] == 0


def test_parser_reads_multiple_source_snippets_and_normalizes_shapes_and_event_ids():
    hits = [
        _source_evidence_hit({
            "article_date_iso": "2026-06-23",
            "evidence_snippets": {"event_ids": "E1", "text": ["dict block snippet"]},
        }),
        _source_evidence_hit([{
            "article_date_iso": "2026-06-24",
            "evidence_snippets": [
                {"event_ids": ["E1", "E2"], "text": "list snippet one"},
                {"event_ids": None, "text": ["list snippet two"]},
                {"event_ids": ["bad"], "text": None},
            ],
        }]),
    ]
    hits[1]["_source"]["uuid"] = "demo2"

    parsed, _ = parse_es_hits(hits, query_for_snippet="snippet", config=EvidenceBuildConfig())

    assert [(c.text, c.event_ids) for c in parsed[0].citations] == [("dict block snippet", ["E1"])]
    assert [(c.text, c.event_ids) for c in parsed[1].citations] == [
        ("list snippet one", ["E1", "E2"]),
        ("list snippet two", []),
    ]


def test_parser_keeps_raw_content_as_last_backward_compatible_fallback():
    hit = {
        "_source": {
            "uuid": "legacy1",
            "rawInfo": {"content": "舊版全文仍可形成最後的相容證據片段。"},
            "multidim_event_json": [{"article_date_iso": "2026-06-25"}],
        }
    }

    parsed, stats = parse_es_hits([hit], query_for_snippet="相容證據", config=EvidenceBuildConfig())

    assert "相容證據" in parsed[0].citations[0].text
    assert stats["n_source_evidence_used"] == 0
    assert stats["n_fallback_used"] == 1


def test_source_evidence_flows_into_report_aggregation_counts():
    hit = _source_evidence_hit([{
        "article_date_iso": "2026-06-23",
        "evidence_snippets": [{"event_ids": "E1", "text": "福隆12號高雄港捕撈作業"}],
    }])
    _, evidence, _ = build_hits_and_evidence(
        [hit],
        date_from="2026-06-01",
        date_to="2026-06-30",
        effective_terms=[],
        term_groups=[],
        query_for_snippet="福隆12號",
    )

    aggregation = AggregateMonthQuarter().forward(evidence_snippets=evidence)

    assert len(evidence) == 1
    assert aggregation["doc_count"] == 1
    assert aggregation["snippet_count"] == 1
    assert aggregation["active_days"] == 1
    assert aggregation["day_counts"] == {"2026-06-23": 1}
    assert aggregation["month_counts"] == {"2026-06": 1}
    assert aggregation["quarter_counts"] == {"2026-Q2": 1}


def test_timeline_tool_returns_new_time_and_event_link_fields(monkeypatch):
    monkeypatch.setattr("agent.tools_es.timeline.resolve_index", lambda _: "events")
    monkeypatch.setattr(
        "agent.tools_es.timeline._safe_es_search",
        lambda *args, **kwargs: {"hits": {"hits": [{"_source": {
            "multidim_event_json": [{"Event_Timeline": [{
                "event_ids": ["evt-2"],
                "time_iso": "2026-08-19T10:00:00Z",
                "time_raw": "8月19日",
                "time_precision": "day",
                "description": "事件二",
            }]}]
        }}]}},
    )

    result = ESTimeline().forward(uuid="doc-2")

    assert result["timeline"] == [{
        "event_ids": ["evt-2"],
        "time_iso": "2026-08-19T10:00:00Z",
        "time_raw": "8月19日",
        "time_precision": "day",
        "description": "事件二",
    }]
