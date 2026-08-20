from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.parser import parse_es_hits
from agent.es.query_body import build_main_query_body
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
