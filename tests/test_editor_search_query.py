"""Offline regressions for editor mapping-aware substring/nested search (#398)."""
from types import SimpleNamespace

import pytest

from api.services.editor_search_query import build_editor_search_query


def _mapping():
    return {
        "title": {"type": "text", "fields": ["keyword"]},
        "subject": {"type": "text", "fields": ["keyword"]},
        "uuid": {"type": "keyword"},
        "rawInfo": {"type": "object", "has_properties": True},
        "rawInfo.title": {"type": "text", "fields": ["keyword"]},
        "communication": {"type": "object", "has_properties": True},
        "communication.subject": {"type": "keyword"},
        "multidim_event_json": {"type": "nested", "has_properties": True},
        "multidim_event_json.article_title": {"type": "text", "fields": ["keyword"]},
        "multidim_event_json.evidence_snippets": {"type": "nested", "has_properties": True},
        "multidim_event_json.evidence_snippets.text": {"type": "text"},
    }


FIELDS = [
    "title^3", "subject^3", "uuid^2", "rawInfo.title^3",
    "communication.subject^3", "multidim_event_json.article_title^3",
    "multidim_event_json.evidence_snippets.text^2",
]


def _walk(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


@pytest.mark.parametrize("part", ["this_is", "a_title", "this_is_a_title"])
def test_underscore_token_automatically_has_safe_keyword_substring_clause(part):
    query, warnings = build_editor_search_query(part, FIELDS, _mapping(), True)
    wildcard = [node["wildcard"] for node in _walk(query) if "wildcard" in node]
    assert {"subject.keyword": {
        "value": f"*{part}*", "case_insensitive": True, "boost": 3.0
    }} in wildcard
    assert not any("rawInfo.content" in str(node) for node in wildcard)
    assert any("包含字串" in msg for msg in warnings)


def test_nested_text_and_substring_queries_keep_nested_path():
    query, _ = build_editor_search_query(
        "a_title", FIELDS, _mapping(), True
    )
    nested = [node["nested"] for node in _walk(query) if "nested" in node]
    assert any(n["path"] == "multidim_event_json" and
               "article_title" in str(n["query"]) for n in nested)
    assert any(n["path"] == "multidim_event_json.evidence_snippets" and
               "evidence_snippets.text" in str(n["query"]) for n in nested)
    assert any(n["path"] == "multidim_event_json" and
               "wildcard" in n["query"] for n in nested)
    # The ES nested-child mapping requires both the outer and inner contexts.
    assert any(
        n["path"] == "multidim_event_json" and any(
            child.get("nested", {}).get("path")
            == "multidim_event_json.evidence_snippets"
            for child in _walk(n["query"])
        )
        for n in nested
    )


def test_regular_words_preserve_full_text_and_explicit_contains_is_opt_in():
    query, warnings = build_editor_search_query("title", FIELDS, _mapping(), True)
    assert not any("wildcard" in n for n in _walk(query))
    assert warnings == []
    query2, _ = build_editor_search_query("title", FIELDS, _mapping(), True, "contains")
    assert any("wildcard" in n for n in _walk(query2))
    query3, _ = build_editor_search_query("a_title", FIELDS, _mapping(), True, "text")
    assert not any("wildcard" in n for n in _walk(query3))


@pytest.mark.parametrize("bad", ["*", "*title*", "a title", "a", "a" * 65])
def test_substring_rejects_unbounded_or_nonliteral_patterns(bad):
    query, warnings = build_editor_search_query(bad, FIELDS, _mapping(), True, "contains")
    assert not any("wildcard" in n for n in _walk(query))
    assert any("僅支援" in msg for msg in warnings)


def test_unknown_or_keywordless_mapping_never_claims_substring_match():
    no_keyword = {"subject": {"type": "text"}}
    query, warnings = build_editor_search_query(
        "a_title", ["subject^3"], no_keyword, True,
    )
    assert not any("wildcard" in n for n in _walk(query))
    assert any("沒有可用" in msg for msg in warnings)
    query2, warnings2 = build_editor_search_query(
        "a_title", ["subject^3"], {}, False,
    )
    assert "simple_query_string" in query2
    assert any("Mapping 無法取得" in w for w in warnings2)


def test_mapping_omits_nonsearchable_fields_and_fails_closed_if_none():
    query, warnings = build_editor_search_query(
        "hello", ["importDT", "number"], {
            "importDT": {"type": "date"}, "number": {"type": "integer"},
        }, True,
    )
    assert query == {"match_none": {}}
    assert any("沒有可用" in w for w in warnings)


def test_empty_query_does_not_scan_keyword_fields():
    assert build_editor_search_query("", FIELDS, _mapping(), True) == (
        {"match_all": {}}, []
    )


def test_editor_search_api_substring_and_date_filter_with_mapping(monkeypatch):
    from api.routers import editor as routes

    class FakeEs:
        def __init__(self):
            self.body = None
        def search(self, *, index, body):
            assert index == "news_test"
            self.body = body
            return {"hits": {"total": {"value": 1}, "hits": [
                {"_index": index, "_id": "id1", "_score": 1.0,
                 "_source": {"subject": "this_is_a_title"}}
            ]}}

    fake = FakeEs()
    monkeypatch.setattr(routes, "ensure_allowed_index", lambda index: None)
    monkeypatch.setattr(routes, "get_editor_schema", lambda index: {
        "search_fields": FIELDS, "search_date_field": "importDT",
    })
    monkeypatch.setattr(
        routes, "get_index_field_metadata_map",
        lambda index: ({**_mapping(), "importDT": {"type": "date"}}, True),
    )
    monkeypatch.setattr(routes.es_client, "get_es", lambda: fake)
    monkeypatch.setattr(routes.es_client, "using_mock_es", lambda: False)
    response = routes.search_documents(
        index="news_test", q="a_title", search_mode="auto",
        size=20, page=1, start_ts="2023-08-01", end_ts="2023-08-31",
        user=SimpleNamespace(mock_preview=False),
    )
    assert response["total"] == 1
    assert response["hits"][0]["source"]["subject"] == "this_is_a_title"
    assert fake.body["query"]["bool"]["filter"] == [{
        "range": {"importDT": {"gte": "2023-08-01", "lte": "2023-08-31"}}
    }]
    assert any("wildcard" in n for n in _walk(fake.body["query"]))
    assert response["warnings"]


def test_editor_ui_displays_search_warnings_and_search_mode():
    from pathlib import Path

    html = Path("sra_api/static/editor.html").read_text(encoding="utf-8")
    js = Path("sra_api/static/editor_documents.js").read_text(encoding="utf-8")
    assert 'id="searchMode"' in html
    assert "data.warnings" in js
    assert "search_mode: $('searchMode').value" in js


def test_mapping_reader_exposes_real_multifield_types(monkeypatch):
    from api.services import editor_index_utils as utils

    class FakeIndices:
        def get_mapping(self, *, index):
            assert index == "news_test"
            return {"news_test": {"mappings": {"properties": {
                "title": {"type": "text", "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256},
                    "suggest": {"type": "search_as_you_type"},
                }},
            }}}}

    monkeypatch.setattr(utils.es_client, "get_es",
                        lambda: SimpleNamespace(indices=FakeIndices()))
    metadata, ok = utils.get_index_field_metadata_map("news_test")
    assert ok
    assert metadata["title"]["fields"] == ["keyword", "suggest"]
    assert metadata["title.keyword"]["type"] == "keyword"
    assert metadata["title.suggest"]["type"] == "search_as_you_type"
    query, warnings = build_editor_search_query(
        "a_title", ["title.keyword^3"], metadata, True,
    )
    assert query["bool"]["minimum_should_match"] == 1
    text_queries = [n["simple_query_string"] for n in _walk(query)
                    if "simple_query_string" in n]
    assert any(q["fields"] == ["title.keyword^3"] for q in text_queries)
    keyword_queries = [n["wildcard"] for n in _walk(query) if "wildcard" in n]
    assert {"title.keyword": {
        "value": "*a_title*", "case_insensitive": True, "boost": 3.0,
    }} in keyword_queries
    assert any("包含字串" in warning for warning in warnings)


def test_original_long_fulltext_query_is_not_rejected_by_substring_bounds():
    long_query = "report " * 60
    query, warnings = build_editor_search_query(
        long_query, ["subject^3"], _mapping(), True,
    )
    assert query["simple_query_string"]["query"] == long_query.strip()
    assert warnings == []


@pytest.mark.parametrize("mode", ["auto", "text", "contains"])
@pytest.mark.parametrize("term", [
    "report -secret", "report (-secret)", "report +-secret",
    "report+-secret", "report (+-secret)", "report|+-secret",
    "subject_part -sensitive",
])
def test_document_negation_never_bypassed_by_another_nested_context(mode, term):
    # The old root SQS executes negation once across its configured fields.
    # A new OR of separately scoped root/nested clauses would allow an
    # excluded document back through a nested hit. Keep the legacy contract.
    query, warnings = build_editor_search_query(
        term, FIELDS, _mapping(), True, mode,
    )
    assert "simple_query_string" in query
    assert query["simple_query_string"]["query"] == term
    assert query["simple_query_string"]["default_operator"] == "and"
    assert not any("wildcard" in n or "nested" in n for n in _walk(query))
    assert any("排除詞" in warning for warning in warnings)
