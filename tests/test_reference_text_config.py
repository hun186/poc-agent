import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent.es.query_body import build_fallback_query_body, build_main_query_body
from agent.es.reference_text import (
    DEFAULT_REFERENCE_TEXT_FIELD,
    add_reference_text_mapping,
    get_reference_text,
    get_reference_text_field,
    set_reference_text,
)
from agent.tools_es.fetch_doc import ESFetchDocById
from data_ingestion.sql_to_es import ingest_sql
from data_ingestion.txt_to_es import ingest_txt
from sra_api.routers import docs as docs_router
from sra_api.core.presenters.citation_views import build_citation_views
from sra_api.core.presenters.markdown_presenter import _render_citations
from sra_api.core.presenters.sections import AgentPresentation


class _FakeES:
    def get(self, **_kwargs):
        return {
            "found": True,
            "_index": "news_test",
            "_source": {
                "rawInfo": {"content": "雜亂原文"},
                "agent_context": {"coherent_text": "連貫參考文本"},
            },
        }


def test_reference_text_defaults_to_raw_info_content(monkeypatch):
    monkeypatch.delenv("SRA_REFERENCE_TEXT_FIELD", raising=False)

    assert get_reference_text_field() == DEFAULT_REFERENCE_TEXT_FIELD
    assert get_reference_text({"rawInfo": {"content": " 原始全文 "}}) == "原始全文"


def test_reference_text_supports_configured_nested_field(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    source = {
        "rawInfo": {"content": "雜亂原文"},
        "agent_context": {"coherent_text": "精煉且保留脈絡的詳文"},
    }

    assert get_reference_text_field() == "agent_context.coherent_text"
    assert get_reference_text(source) == "精煉且保留脈絡的詳文"


def test_invalid_reference_text_field_falls_back_to_safe_default(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", 'rawInfo.content"}}]')

    assert get_reference_text_field() == DEFAULT_REFERENCE_TEXT_FIELD


def test_reference_text_writer_rejects_object_path_collision():
    source = {"rawInfo": {"langCode": "C"}}

    try:
        set_reference_text(source, "內容", field="rawInfo")
    except ValueError as exc:
        assert "conflicts with object field" in str(exc)
    else:
        raise AssertionError("object path collision must be rejected")

    try:
        add_reference_text_mapping(
            {"properties": {"rawInfo": {"properties": {"langCode": {"type": "keyword"}}}}},
            field="rawInfo",
        )
    except ValueError as exc:
        assert "conflicts at" in str(exc)
    else:
        raise AssertionError("mapping collision must be rejected")


def test_es_queries_use_configured_reference_text_field(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")

    main = build_main_query_body(
        query="測試",
        must_high_value=None,
        must_selected=None,
        size=5,
        date_from=None,
        date_to=None,
        selected_boost=None,
        high_value_boost=None,
        recency_boost=None,
        recency_field=None,
        recency_scale=None,
        core_terms=["核心詞"],
        syn_terms=["同義詞"],
    )
    fallback = build_fallback_query_body("測試", None, None, 5)
    rendered_main = json.dumps(main, ensure_ascii=False)
    rendered_fallback = json.dumps(fallback, ensure_ascii=False)

    assert "agent_context.coherent_text" in rendered_main
    assert "rawInfo.content" not in rendered_main
    assert "agent_context.coherent_text" in fallback["_source"]
    assert "agent_context.coherent_text" in fallback["highlight"]["fields"]
    assert "rawInfo.content" not in rendered_fallback


def test_fetch_doc_uses_configured_reference_text_without_raw_fallback(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    tool = ESFetchDocById()
    tool._es = _FakeES()

    result = tool.forward("doc-1", index_hint="news_test")

    assert result["full_text"] == "連貫參考文本"


def test_docs_fulltext_uses_configured_reference_text(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    monkeypatch.setattr(
        docs_router,
        "_get_doc_source_or_404",
        lambda _doc_id: {
            "rawInfo": {"content": "雜亂原文"},
            "agent_context": {"coherent_text": "連貫參考文本"},
        },
    )

    response = docs_router.get_fulltext_on_demand("doc-1", format="json")
    payload = json.loads(response.body)

    assert payload["full_text"] == "連貫參考文本"
    assert payload["text_layer"] == "reference"
    assert payload["available_text_layers"]["raw"]["available"] is True


def test_docs_fulltext_can_return_raw_or_both_text_layers(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    monkeypatch.setattr(
        docs_router,
        "_get_doc_source_or_404",
        lambda _doc_id: {
            "uuid": "doc-1",
            "rawInfo": {"content": "未經處理的原文"},
            "agent_context": {"coherent_text": "去雜訊後的連貫詳文"},
        },
    )

    raw_response = docs_router.get_fulltext_on_demand(
        "doc-1", format="json", text_layer="raw"
    )
    both_response = docs_router.get_fulltext_on_demand(
        "doc-1", format="json", text_layer="both"
    )
    both_txt = docs_router.get_fulltext_on_demand(
        "doc-1", format="txt", download=True, text_layer="both"
    )
    raw_payload = json.loads(raw_response.body)
    both_payload = json.loads(both_response.body)

    assert raw_payload["full_text"] == "未經處理的原文"
    assert raw_payload["text_field"] == "rawInfo.content"
    assert both_payload["full_text"] == "去雜訊後的連貫詳文"
    assert both_payload["text_layers"]["reference"]["text"] == "去雜訊後的連貫詳文"
    assert both_payload["text_layers"]["raw"]["text"] == "未經處理的原文"
    assert "===== 代理人參考文本 (agent_context.coherent_text) =====" in both_txt.body.decode()
    assert "===== 原始未處理文本 (rawInfo.content) =====" in both_txt.body.decode()
    assert "_both.txt" in both_txt.headers["content-disposition"]


def test_docs_raw_layer_does_not_fall_back_to_refined_text(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    monkeypatch.setattr(
        docs_router,
        "_get_doc_source_or_404",
        lambda _doc_id: {"agent_context": {"coherent_text": "只有精煉詳文"}},
    )

    with pytest.raises(HTTPException, match="原始未處理文本") as exc_info:
        docs_router.get_fulltext_on_demand("doc-1", format="json", text_layer="raw")

    assert exc_info.value.status_code == 404


def test_legacy_document_without_agent_context_uses_raw_by_default(monkeypatch):
    monkeypatch.delenv("SRA_REFERENCE_TEXT_FIELD", raising=False)
    monkeypatch.setattr(
        docs_router,
        "_get_doc_source_or_404",
        lambda _doc_id: {"rawInfo": {"content": "舊文件原文"}},
    )

    response = docs_router.get_fulltext_on_demand("legacy-1", format="json")
    payload = json.loads(response.body)

    assert payload["full_text"] == "舊文件原文"
    assert payload["text_field"] == "rawInfo.content"
    assert payload["available_text_layers"]["reference"]["available"] is True


def test_legacy_document_remains_auditable_after_reference_field_switch(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    monkeypatch.setattr(
        docs_router,
        "_get_doc_source_or_404",
        lambda _doc_id: {"rawInfo": {"content": "舊文件原文"}},
    )

    with pytest.raises(HTTPException) as exc_info:
        docs_router.get_fulltext_on_demand(
            "legacy-1", format="json", text_layer="reference"
        )
    raw_response = docs_router.get_fulltext_on_demand(
        "legacy-1", format="json", text_layer="raw"
    )
    both_response = docs_router.get_fulltext_on_demand(
        "legacy-1", format="json", text_layer="both"
    )
    raw_payload = json.loads(raw_response.body)
    both_payload = json.loads(both_response.body)

    assert exc_info.value.status_code == 404
    assert raw_payload["full_text"] == "舊文件原文"
    assert both_payload["full_text"] == "舊文件原文"
    assert both_payload["text_layers"]["reference"]["available"] is False
    assert both_payload["text_layers"]["raw"]["available"] is True


def test_txt_ingestion_writes_and_maps_configured_reference_field(monkeypatch, tmp_path):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    source_file = tmp_path / "sample.txt"
    source_file.write_text("TXT 連貫文本", encoding="utf-8")

    _doc_id, source = ingest_txt.build_doc_from_file(str(source_file))
    mapping = ingest_txt.build_index_mappings()

    assert source["agent_context"]["coherent_text"] == "TXT 連貫文本"
    assert source["rawInfo"]["content"] == "TXT 連貫文本"
    assert mapping["properties"]["agent_context"]["properties"]["coherent_text"] == {
        "type": "text"
    }


def test_txt_ingestion_keeps_raw_info_content_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SRA_REFERENCE_TEXT_FIELD", raising=False)
    source_file = tmp_path / "legacy.txt"
    source_file.write_text("既有全文", encoding="utf-8")

    _doc_id, source = ingest_txt.build_doc_from_file(str(source_file))

    assert source["rawInfo"]["content"] == "既有全文"
    assert source["rawInfo"]["langCode"] == "C"


def test_sql_to_es_writes_and_maps_configured_reference_field(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "agent_context.coherent_text")
    cfg = {
        "db": {"server": "db-host", "database": "db-name"},
        "source": {
            "table": "dbo.Articles",
            "columns": {"id": "id", "title": "title", "content": "body"},
        },
        "import": {"dedup_by_content": True},
    }
    row = {"__id": 1, "__title": "標題", "__content": "SQL 連貫文本"}

    _doc_id, source = ingest_sql.build_doc_from_row(row, cfg)
    mapping = ingest_sql.build_sql_index_mappings()

    assert source["agent_context"]["coherent_text"] == "SQL 連貫文本"
    assert source["rawInfo"]["content"] == "SQL 連貫文本"
    assert mapping["properties"]["agent_context"]["properties"]["coherent_text"] == {
        "type": "text"
    }


def test_openwebui_citation_exposes_all_text_layer_downloads():
    request = Request({
        "type": "http",
        "scheme": "https",
        "server": ("sra.example", 443),
        "path": "/v1/chat/completions",
        "query_string": b"",
        "headers": [],
    })
    citation = {"uuid": "doc-1", "subject": "文件", "text": "證據"}

    view = build_citation_views([citation], request)[0]
    presentation = AgentPresentation(
        turn_id=None,
        user_question="",
        answer="",
        reasoning="",
        citations=[citation],
        da_section=None,
        llm_execution=[],
        raw_json_str="",
        raw_json_line_count=0,
        auto_collapse_json=False,
        raw_json_md="",
    )
    markdown = "\n".join(_render_citations(presentation, request))

    assert "text_layer=reference" in view.url_txt
    assert "text_layer=raw" in view.url_raw_txt
    assert "text_layer=both" in view.url_both_txt
    assert "[下載參考文本]" in markdown
    assert "[下載原始文本]" in markdown
    assert "[下載雙層比對]" in markdown
