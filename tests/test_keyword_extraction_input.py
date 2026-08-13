import logging

import agent.es.query_terms as query_terms


def test_large_query_is_compacted_only_for_keyword_extraction(monkeypatch, caplog):
    query = "請分析航空母艦活動。" + ("資料列,123456\n" * 2000) + "最後聚焦遼寧號。"
    received = {}

    def fake_extract(value):
        received["extract"] = value
        return ["遼寧號"]

    def fake_manual(value):
        received["manual"] = value
        return []

    def fake_synonyms(value, core_terms):
        received["synonyms"] = value
        return {}

    monkeypatch.setattr(query_terms, "extract_topic_terms_llm", fake_extract)
    monkeypatch.setattr(query_terms, "extract_manual_terms_from_query", fake_manual)
    monkeypatch.setattr(query_terms, "expand_synonyms_grouped_llm", fake_synonyms)

    with caplog.at_level(logging.WARNING, logger="agent.es.query_terms"):
        query_terms.compute_effective_terms(query)

    extractor_input = received["extract"]
    assert len(extractor_input) == query_terms.KEYWORD_EXTRACTION_MAX_CHARS
    assert extractor_input.startswith("請分析航空母艦活動。")
    assert extractor_input.endswith("最後聚焦遼寧號。")
    assert "中間大量任務資料已省略" in extractor_input
    assert received["manual"] == query
    assert received["synonyms"] == query
    assert "只裁切關鍵字提取器的暫時輸入" in caplog.text
    assert query not in caplog.text


def test_short_query_is_unchanged_for_keyword_extraction(monkeypatch, caplog):
    query = "請分析遼寧號近期活動"
    received = {}

    def fake_extract(value):
        received["extract"] = value
        return []

    monkeypatch.setattr(query_terms, "extract_topic_terms_llm", fake_extract)
    monkeypatch.setattr(query_terms, "extract_manual_terms_from_query", lambda value: [])

    with caplog.at_level(logging.WARNING, logger="agent.es.query_terms"):
        query_terms.compute_effective_terms(query)

    assert received["extract"] == query
    assert "關鍵字提取裁切機制" not in caplog.text
