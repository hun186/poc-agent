"""Offline SRAF core-term alias grouping regressions.

No real Elasticsearch, LLM, service credentials or network traffic.
"""
import json

import pytest

import agent.es.query_terms as query_terms
from agent.es.evidence_core.topic_match import match_topic
from agent.es.query_body import build_main_query_body


def _compute(monkeypatch, original_cores, synonym_map, variants=None):
    monkeypatch.setattr(
        query_terms, "extract_topic_terms_llm", lambda _query: list(original_cores)
    )
    monkeypatch.setattr(query_terms, "extract_manual_terms_from_query", lambda _q: [])
    calls = []

    def fake_expander(_query, cores):
        calls.append(list(cores))
        return synonym_map

    monkeypatch.setattr(query_terms, "expand_synonyms_grouped_llm", fake_expander)
    if variants is None:
        monkeypatch.setattr(query_terms, "expand_zh_script_variants", lambda t: [t])
    else:
        monkeypatch.setattr(
            query_terms, "expand_zh_script_variants",
            lambda t: variants.get(t, [t]),
        )
    output = query_terms.compute_effective_terms("桃園機場事件")
    assert calls == [list(original_cores)]  # existing one expansion call, no new LLM
    return output


def test_llm_explicit_alias_core_does_not_become_second_required_axis(monkeypatch):
    core, grouped, _manual, _matched, effective, axes = _compute(
        monkeypatch,
        ["桃園機場", "桃園國際機場"],
        {"桃園機場": ["桃園國際機場"]},
    )
    assert core == ["桃園機場"]
    assert grouped == {"桃園機場": ["桃園國際機場"]}
    assert effective == ["桃園機場", "桃園國際機場"]
    assert axes == [{"桃園機場", "桃園國際機場"}]
    # Previous grouping produced two required axes and rejected the common name.
    assert not match_topic(
        "桃園機場今日進行整修", None, None,
        [{"桃園機場", "桃園國際機場"}, {"桃園國際機場"}],
    )[0]
    for phrase in ("桃園機場今日進行整修", "桃園國際機場今日進行整修"):
        assert match_topic(phrase, None, None, axes)[0]


def test_official_name_to_common_name_is_symmetric(monkeypatch):
    core, grouped, _, _, _, axes = _compute(
        monkeypatch,
        ["桃園國際機場", "桃園機場"],
        {"桃園國際機場": ["桃園機場"]},
    )
    assert core == ["桃園國際機場"]
    assert grouped == {"桃園國際機場": ["桃園機場"]}
    assert axes == [{"桃園國際機場", "桃園機場"}]
    for phrase in ("桃園機場", "桃園國際機場"):
        assert match_topic(phrase, None, None, axes)[0]


def test_overlapping_llm_representatives_are_transitively_one_axis(monkeypatch):
    core, grouped, _, _, effective, axes = _compute(
        monkeypatch,
        ["桃園機場", "桃園國際機場", "臺灣桃園國際機場"],
        {
            "桃園機場": ["桃園國際機場"],
            "桃園國際機場": ["臺灣桃園國際機場"],
        },
    )
    assert core == ["桃園機場"]
    assert axes == [{"桃園機場", "桃園國際機場", "臺灣桃園國際機場"}]
    assert len(effective) == 3
    assert grouped["桃園機場"] == ["桃園國際機場", "臺灣桃園國際機場"]


def test_aliases_added_before_simplified_traditional_variants(monkeypatch):
    variants = {
        "桃園機場": ["桃園機場", "桃园机场"],
        "桃園國際機場": ["桃園國際機場", "桃园国际机场"],
    }
    core, grouped, _, _, _, axes = _compute(
        monkeypatch,
        ["桃園機場", "桃園國際機場"],
        {"桃園機場": ["桃園國際機場"]},
        variants,
    )
    assert core == ["桃園機場"]
    assert grouped == {
        "桃園機場": ["桃园机场", "桃園國際機場", "桃园国际机场"]
    }
    assert len(axes) == 1
    assert match_topic("桃园国际机场更新作業", "", "", axes)[0]


def test_distinct_subjects_remain_independent_required_axes(monkeypatch):
    core, _, _, _, _, axes = _compute(
        monkeypatch,
        ["桃園機場", "桃園國際機場", "第三航廈"],
        {"桃園機場": ["桃園國際機場"]},
    )
    assert core == ["桃園機場", "第三航廈"]
    assert len(axes) == 2
    assert not match_topic("桃園機場跑道事件", "", "", axes)[0]
    assert match_topic("桃園國際機場第三航廈工程", "", "", axes)[0]
    assert not match_topic("松山機場第三航廈工程", "", "", axes)[0]


def test_no_llm_equivalence_claim_keeps_independent_core_axes(monkeypatch):
    core, grouped, _, _, _, axes = _compute(
        monkeypatch,
        ["桃園機場", "第三航廈"], {},
    )
    assert core == ["桃園機場", "第三航廈"]
    assert grouped == {}
    assert axes == [{"桃園機場"}, {"第三航廈"}]


def test_shared_noncore_alias_does_not_collapse_distinct_entities(monkeypatch):
    core, _, _, _, _, axes = _compute(
        monkeypatch,
        ["甲機構", "乙機構"],
        {"甲機構": ["共同簡稱"], "乙機構": ["共同簡稱"]},
    )
    assert core == ["甲機構", "乙機構"]
    assert len(axes) == 2


def test_query_builder_carries_generated_full_name_into_es_synonym_clauses(monkeypatch):
    cores, _, _, _, all_terms, axes = _compute(
        monkeypatch,
        ["桃園機場", "桃園國際機場"],
        {"桃園機場": ["桃園國際機場"]},
    )
    body = build_main_query_body(
        query="桃園機場",
        must_high_value=False,
        must_selected=False,
        size=5,
        date_from=None,
        date_to=None,
        selected_boost=6.0,
        high_value_boost=2.5,
        recency_boost=False,
        recency_field="importDT",
        recency_scale="30d",
        core_terms=cores,
        syn_terms=["桃園國際機場"],
        all_terms=all_terms,
    )
    serialized = json.dumps(body, ensure_ascii=False)
    assert '"match_phrase": {"multidim_event_json.evidence_snippets.text": "桃園國際機場"}' in serialized
    assert len(axes) == 1
    # This asserts generated DSL only, not live ES mapping/analyzer behavior.


@pytest.mark.parametrize("input_name", ["桃園機場", "桃園國際機場"])
def test_prompt_explicitly_checks_official_and_common_names_both_directions(monkeypatch, input_name):
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    prompts = []

    def fake_llm(_user_prompt, system_prompt):
        prompts.append(system_prompt)
        return json.dumps({input_name: []}, ensure_ascii=False)

    monkeypatch.setattr(query_terms, "call_llm", fake_llm)
    assert query_terms.expand_synonyms_grouped_llm(input_name, [input_name]) == {}
    assert len(prompts) == 1
    assert "雙向" in prompts[0]
    assert "官方正式名稱" in prompts[0]
    assert "通稱" in prompts[0]
    assert "俗稱" in prompts[0]
    assert "不確定的名稱不要生成" in prompts[0]
    assert "不得把松山機場或機場捷運列為同義詞" in prompts[0]
