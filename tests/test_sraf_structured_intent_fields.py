"""GLM blueprint TEXT-only, question-intent query expansion (offline)."""
from __future__ import annotations
import copy
import json
import logging

from agent.es.structured_intent_fields import (
    build_intent_shoulds, select_text_fields, MAX_EXTRA_FIELDS,
)
from agent.es.query_body import build_main_query_body


def _query():
    return build_main_query_body(
        query="加薩 停火", must_high_value=False, must_selected=False,
        size=30, date_from="2023-08-24", date_to="2023-08-24",
        selected_boost=6.0, high_value_boost=2.5, recency_boost=False,
        recency_field="importDT", recency_scale="30d",
        original_question="評估政策的影響與人物發言",
    )


def _shoulds(body):
    return body["query"]["function_score"]["query"]["bool"]["should"]


def test_default_off_and_shadow_are_byte_identical_queries(monkeypatch, caplog):
    monkeypatch.delenv("SRAF_STRUCTURED_FIELD_EXPANSION", raising=False)
    baseline = _query()
    assert all("Impact.impact_description" not in str(x) for x in _shoulds(baseline))
    monkeypatch.setenv("SRAF_STRUCTURED_FIELD_EXPANSION", "shadow")
    with caplog.at_level(logging.WARNING, logger="sraf.structured_field_plan"):
        observed = _query()
    assert observed == baseline
    logs = [r.message for r in caplog.records if r.name == "sraf.structured_field_plan"]
    assert len(logs) == 1
    assert "mode=shadow" in logs[0]
    assert "applied=0" in logs[0]
    assert "加薩" not in logs[0] and "政策" not in logs[0]


def test_intent_selects_text_only_not_keyword_or_dates():
    fields = select_text_fields("政策對人物態度的影響是什麼？")
    assert fields and len(fields) <= MAX_EXTRA_FIELDS
    result = {f for _, f, _ in fields}
    assert {"Event_Summary", "consequence", "impact_description", "action"} <= result
    assert not result & {
        "subject", "object", "location", "core_entities", "facet",
        "locations", "stance", "party_name", "party_role", "time_iso",
    }
    assert select_text_fields("加薩地區新聞回顧") == ()
    assert select_text_fields("影響" * 3000) == ()  # bounded question


def test_nested_context_each_field_is_separate_and_unmapped_safe():
    clauses = build_intent_shoulds(
        search_query="中國政策", original_question="政策後果如何？",
    )
    assert clauses
    paths = []
    for root in clauses:
        assert set(root) == {"nested"}
        assert root["nested"]["path"] == "multidim_event_json"
        assert root["nested"]["ignore_unmapped"] is True
        inner = root["nested"]["query"]
        if "nested" in inner:
            assert inner["nested"]["ignore_unmapped"] is True
            path = inner["nested"]["path"]
            assert path in {
                "multidim_event_json.Event",
                "multidim_event_json.Impact",
            }
            leaf = next(iter(inner["nested"]["query"]["match"]))
            assert leaf.startswith(path + ".")
            paths.append(path)
        else:
            assert list(inner["match"]) == ["multidim_event_json.Event_Summary"]
    assert "multidim_event_json.Event" in paths
    assert "multidim_event_json.Impact" in paths
    assert not any("keyword" in str(x) for x in clauses)


def test_on_adds_only_should_boosts_never_changes_date_or_sort(monkeypatch):
    monkeypatch.setenv("SRAF_STRUCTURED_FIELD_EXPANSION", "off")
    baseline = _query()
    monkeypatch.setenv("SRAF_STRUCTURED_FIELD_EXPANSION", "on")
    expanded = _query()
    assert expanded["query"]["function_score"]["query"]["bool"]["filter"] == (
        baseline["query"]["function_score"]["query"]["bool"]["filter"])
    assert expanded["sort"] == baseline["sort"]
    assert len(_shoulds(expanded)) > len(_shoulds(baseline))
    assert _shoulds(expanded)[:len(_shoulds(baseline))] == _shoulds(baseline)
    assert all(set(x) == {"nested"} for x in
               _shoulds(expanded)[len(_shoulds(baseline)):])
    assert "Event_Timeline.time_iso" not in str(
        _shoulds(expanded)[len(_shoulds(baseline)):])
    # These query-only clauses do not change Evidence parser validation.


def test_no_original_or_unrecognized_intent_does_not_boost(monkeypatch):
    monkeypatch.setenv("SRAF_STRUCTURED_FIELD_EXPANSION", "on")
    def query(original):
        return build_main_query_body(
            query="加薩", must_high_value=False, must_selected=False,
            size=10, date_from=None, date_to=None, selected_boost=6,
            high_value_boost=2.5, recency_boost=False, recency_field="importDT",
            recency_scale="30d", original_question=original)
    base = query(None)
    assert query("無明確事件問題") == base
    assert query("影響" * 3000) == base


def test_keyword_partial_chinese_is_not_mistaken_for_analyzed_text():
    text = json.dumps(build_intent_shoulds(
        search_query="中美關係", original_question="分析政策影響",
    ), ensure_ascii=False)
    for field in (
        ".Event.action", ".Event.subject", ".Event.object",
        ".Person.stance", ".Involved_Parties.party_role",
        ".core_entities", ".facet", ".locations",
    ):
        assert field not in text
