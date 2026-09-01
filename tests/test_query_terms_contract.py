import json

import agent.es.query_terms as query_terms
import agent.tools_es.common as es_common
from agent.data_agent.report_prompts import REPORT_DATA_SYSTEM
from agent.data_agent.style_prompts import STYLE_DATA_CODE_SYSTEM


def _disable_nonsemantic_expansion(monkeypatch):
    monkeypatch.setattr(query_terms, "extract_manual_terms_from_query", lambda _q: [])
    monkeypatch.setattr(query_terms, "expand_synonyms_grouped_llm", lambda _q, _terms: {})
    monkeypatch.setattr(query_terms, "expand_zh_script_variants", lambda term: [term])


def test_parse_explicit_report_core_terms_is_ordered_trimmed_and_deduplicated():
    query = " 核心關鍵詞組如下 : 甲主題、 、乙制度，甲主題, 丙技術、 "

    assert query_terms._parse_explicit_core_terms_query(query) == [
        "甲主題",
        "乙制度",
        "丙技術",
    ]
    assert query_terms._parse_explicit_core_terms_query("核心關鍵詞組如下：  ") == []


def test_explicit_report_query_skips_topic_extraction_and_retains_terms(monkeypatch):
    _disable_nonsemantic_expansion(monkeypatch)
    monkeypatch.setattr(
        query_terms,
        "extract_topic_terms_llm",
        lambda _q: (_ for _ in ()).throw(AssertionError("extractor must not run")),
    )

    result = query_terms.compute_effective_terms(
        "核心關鍵詞組如下：甲主題、乙制度、丙技術"
    )

    assert result[0] == ["甲主題", "乙制度", "丙技術"]
    assert result[4] == ["甲主題", "乙制度", "丙技術"]
    assert len(result) == 6


def test_natural_language_query_keeps_topic_extraction_path(monkeypatch):
    _disable_nonsemantic_expansion(monkeypatch)
    received = []

    def fake_extract(query):
        received.append(query)
        return ["甲主題"]

    monkeypatch.setattr(query_terms, "extract_topic_terms_llm", fake_extract)

    result = query_terms.compute_effective_terms("請整理甲主題的資料")

    assert received == ["請整理甲主題的資料"]
    assert result[0] == ["甲主題"]


def test_style_structured_prefix_is_not_report_explicit_format():
    assert (
        query_terms._parse_explicit_core_terms_query(
            "風格仿寫關鍵詞組如下：甲文種、乙主題"
        )
        is None
    )


def test_style_primary_and_fallback_contract_remains_in_prompt():
    assert "primary_terms = style_terms + topic_terms" in STYLE_DATA_CODE_SYSTEM
    assert "if len(hits) < 5:" in STYLE_DATA_CODE_SYSTEM
    assert "query=fallback_query" in STYLE_DATA_CODE_SYSTEM
    assert "index_hint=index_hint" in STYLE_DATA_CODE_SYSTEM


def test_synonym_expander_rejects_llm_created_representative_key(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    monkeypatch.setattr(
        query_terms,
        "call_llm",
        lambda *_args, **_kwargs: json.dumps(
            {"模型自行新增的詞": ["甲主題"]}, ensure_ascii=False
        ),
    )

    assert query_terms.expand_synonyms_grouped_llm("甲主題資料", ["甲主題"]) == {}


def test_synonym_expander_keeps_legal_key_and_cleans_values(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    monkeypatch.setattr(
        query_terms,
        "call_llm",
        lambda *_args, **_kwargs: json.dumps(
            {"甲主題": ["", "甲主題", "甲主題別名", " 甲主題別名 "]},
            ensure_ascii=False,
        ),
    )

    assert query_terms.expand_synonyms_grouped_llm("甲主題資料", ["甲主題"]) == {
        "甲主題": ["甲主題別名"]
    }


def test_report_prompt_preserves_manual_keyword_control_contract():
    assert "至少保留 A、B" in REPORT_DATA_SYSTEM
    assert "core_terms 限定為 A、B" in REPORT_DATA_SYSTEM
    assert "不得把 C 放入 core_terms" in REPORT_DATA_SYSTEM
    assert "沒有最低數量要求" in REPORT_DATA_SYSTEM
    assert "受控的一階語義擴充" in REPORT_DATA_SYSTEM


def test_index_hint_resolution_remains_independent_of_keyword_processing(monkeypatch):
    received = []
    monkeypatch.setattr(
        es_common,
        "_resolve_es_index",
        lambda index_hint: received.append(index_hint) or ["甲索引", "乙索引"],
    )

    assert es_common.resolve_index("甲索引,乙索引") == "甲索引,乙索引"
    assert received == ["甲索引,乙索引"]
