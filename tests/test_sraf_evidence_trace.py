"""#397 P1-a: privacy-safe, opt-in Evidence retrieval diagnostics.

Only synthetic data. These tests never connect to Elasticsearch or call an LLM.
"""
from __future__ import annotations

import json
import logging

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.trace import EvidenceTrace


def _hit(texts: list[str], *, event_dates: dict[str, str] | None = None) -> dict:
    event_dates = event_dates or {"E1": "2023-08-24"}
    return {
        "_index": "news_test",
        "_id": "SENSITIVE-ES-ID",
        "_source": {
            "uuid": "SENSITIVE-UUID",
            "communication": {"subject": "SENSITIVE-SUBJECT"},
            "multidim_event_json": [{
                "article_title": "SENSITIVE-TITLE",
                "article_date_iso": "2026-11-11",
                "Event": [
                    {"event_id": eid, "time_iso": d, "time_precision": "day"}
                    for eid, d in event_dates.items()
                ],
                "Event_Timeline": [],
                "evidence_snippets": [
                    {"text": txt, "event_ids": ["E1"] if i < 4 else ["E2"]}
                    for i, txt in enumerate(texts)
                ],
            }],
        },
    }


def _build(rows: list[dict], **overrides):
    kwargs = {
        "date_from": "2023-08-24", "date_to": "2023-08-24",
        "effective_terms": ["金磚", "峰會"],
        "term_groups": [{"金磚"}, {"峰會"}],
        "query_for_snippet": "Sensitive query words",
    }
    kwargs.update(overrides)
    return build_hits_and_evidence(rows, **kwargs)


def _traces(caplog):
    prefix = "SRAF_EVIDENCE_TRACE="
    return [
        json.loads(record.message.partition(prefix)[2])
        for record in caplog.records if record.name == "sraf.evidence_trace"
        and record.message.startswith(prefix)
    ]


def test_trace_disabled_preserves_existing_output_and_does_not_emit(monkeypatch, caplog):
    monkeypatch.delenv("SRAF_EVIDENCE_TRACE", raising=False)
    rows = [_hit(["金磚 峰會 one", "不相關 two", "不相關 three"])]
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        baseline = _build(rows)
    assert baseline[1] and len(baseline[1]) == 1
    assert not _traces(caplog)
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "not-one")
    _build(rows)
    assert not _traces(caplog)
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        traced = _build(rows)
    assert traced == baseline


def test_strict_five_to_one_explains_topic_and_date_rejections(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    rows = [_hit([
        "金磚 峰會 joined", "報告 other", "僅談其他主題",
        "local media unrelated", "SENSITIVE-RAW-EVIDENCE",
    ], event_dates={"E1": "2023-08-24", "E2": "2023-08-25"})]
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, evidence, _ = _build(rows)
    assert len(evidence) == 1
    result, = _traces(caplog)
    assert result["schema"] == "sraf_evidence_retrieval_trace_v1"
    assert result["scope"] == "single_builder_evaluation_not_final_report"
    assert result["strict_accepted"] == result["output_evidence"] == 1
    assert result["counters"]["parser.source_candidates"] == 5
    assert result["counters"]["parser.citations_selected"] == 5
    assert result["counters"]["strict.accepted"] == 1
    assert result["counters"]["strict.topic_rejected"] == 3
    assert result["counters"]["strict.date_unmatched"] == 1
    assert not result["relaxed_used"]
    assert all(isinstance(item["hit_ordinal"], int) for item in result["citations"])
    assert len(result["citations"]) == 5
    trace_line = json.dumps(result, ensure_ascii=False)
    for secret in (
        "SENSITIVE-ES-ID", "SENSITIVE-UUID", "SENSITIVE-SUBJECT",
        "SENSITIVE-TITLE", "SENSITIVE-RAW-EVIDENCE",
        "金磚", "峰會", "2023-08-24", "2023-08-25",
        "Sensitive query words",
    ):
        assert secret not in trace_line


def test_inner_hits_cap_is_visible_without_resurrecting_source_snippets(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    h = _hit(["金磚 峰會 one"] * 5)
    h["inner_hits"] = {"evi": {"hits": {"hits": [
        {
            "_source": {"text": "金磚 峰會 matched", "event_ids": ["E1"]},
            "_nested": {"field": "multidim_event_json", "offset": 0},
        } for _ in range(5)
    ]}}}
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, evidence, _ = _build(
            [h], config=EvidenceBuildConfig(inner_hit_topk=5, citations_per_doc=2),
        )
    t, = _traces(caplog)
    assert len(evidence) == 2
    assert t["documents"][0]["mode"] == "inner"
    assert t["documents"][0]["source_candidates"] == 5
    assert t["documents"][0]["inner_returned"] == 5
    assert t["documents"][0]["parsed"] == 5
    assert t["documents"][0]["selected"] == 2
    assert t["counters"]["parser.citations_capped"] == 3
    assert t["counters"]["strict.accepted"] == 2


def test_trace_records_bounded_overflow_without_content(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    trace = EvidenceTrace.from_env()
    assert trace is not None
    for index in range(1000):
        trace.parsed_hit(ordinal=index, source_count=1, inner_count=0,
                         parsed_count=1, selected_count=1, mode="source")
        trace.citation(stage="strict", hit_ordinal=index,
                       citation_ordinal=0, reason="topic_rejected")
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        trace.emit(output_hits=0, output_evidence=0,
                   strict_count=0, relaxed_used=False)
    obj, = _traces(caplog)
    assert obj["counters"]["parser.hits"] == 1000
    assert obj["counters"]["strict.topic_rejected"] == 1000
    assert len(obj["documents"]) == 64
    assert len(obj["citations"]) == 256
    assert obj["document_records_overflow"] == 936
    assert obj["citation_records_overflow"] == 744
    assert len(json.dumps(obj)) < 35000


def test_date_invalid_structured_event_is_never_restored_by_trace(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    row = _hit(["金磚 峰會 incorrect"], event_dates={"E1": "2023-08-25"})
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        hits, evidence, _ = _build([row])
    assert hits == evidence == []
    result, = _traces(caplog)
    assert result["counters"]["strict.date_unmatched"] == 1
    assert result["output_evidence"] == 0
    # Trace visibility cannot change date-qualified Evidence or public output.


def test_source_cap_observes_uninspected_not_proven_valid(monkeypatch, caplog):
    """A source-side 25→20 cap is a distinct loss from post-parse capping."""
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    h = _hit(["金磚 峰會 valid"] * 25, event_dates={
        "E1": "2023-08-24", "E2": "2023-08-24",
    })
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, evidence, _ = _build([h], config=EvidenceBuildConfig(citations_per_doc=20))
    t, = _traces(caplog)
    assert len(evidence) == 20  # no automatic refill or change in selection
    assert t["counters"]["parser.source_candidates"] == 25
    assert t["counters"]["parser.citations_parsed"] == 20
    assert t["counters"]["parser.citations_capped"] == 0
    assert t["counters"]["parser.source_uninspected_after_cap"] == 5
    assert t["documents"][0]["source_uninspected_after_cap"] == 5
    assert t["counters"]["strict.accepted"] == 20



def _inner_hit(text: str, eid: str = "E1") -> dict:
    return {
        "_source": {"text": text, "event_ids": [eid]},
        "_nested": {"field": "multidim_event_json", "offset": 0},
    }


def test_trace_counts_inner_hit_omissions_and_source_rescue_without_data(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_SOURCE_REFILL", "1")
    rows = [
        "金磚 峰會 first STRONG_SECRET",
        "unrelated inner secret",
        "second unrelated inner secret",
        "金磚 fourth SOURCE_SECRET",
        "峰會 fifth SOURCE_SECRET",
    ]
    hit = _hit(rows)
    hit["inner_hits"] = {"evi": {"hits": {"hits": [
        _inner_hit(text) for text in rows[:3]
    ]}}}
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, evidence, _ = _build([hit])
    assert len(evidence) == 3
    assert evidence[0]["match_policy"] == "strict"
    assert [row["match_policy"] for row in evidence[1:]] == [
        "bounded_rescue", "bounded_rescue"
    ]
    trace, = _traces(caplog)
    counts = trace["counters"]
    assert trace["strict_accepted"] == 1
    assert counts["parser.source_candidates"] == 5
    assert counts["parser.inner_returned"] == 3
    assert counts["strict.topic_rejected"] == 2
    assert counts["source_refill.weak_candidates"] == 2
    assert counts["source_refill.weak_selected"] == 2
    assert counts["bounded_rescue.selected"] == 0
    assert trace["output_evidence"] == 3
    serialized = json.dumps(trace, ensure_ascii=False)
    for secret in [
        "STRONG_SECRET", "SOURCE_SECRET", "SENSITIVE-UUID",
        "SENSITIVE-ES-ID", "SENSITIVE-TITLE", "金磚", "峰會",
    ]:
        assert secret not in serialized


def test_trace_source_strict_selected_precedes_weak(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_SOURCE_REFILL", "1")
    rows = [
        "金磚 峰會 initial strong",
        "irrelevant first inner",
        "irrelevant second inner",
        "金磚 峰會 source strong",
        "金磚 source weak",
    ]
    hit = _hit(rows)
    hit["inner_hits"] = {"evi": {"hits": {"hits": [
        _inner_hit(text) for text in rows[:3]
    ]}}}
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, evidence, _ = _build([hit])
    assert [row["match_policy"] for row in evidence] == [
        "strict", "strict", "bounded_rescue"
    ]
    trace, = _traces(caplog)
    counts = trace["counters"]
    assert counts["source_refill.strict_candidates"] == 1
    assert counts["source_refill.strict_selected"] == 1
    assert counts["source_refill.weak_candidates"] == 1
    assert counts["source_refill.weak_selected"] == 1
    assert counts["source_refill.unselected_by_target"] == 0
    assert trace["strict_accepted"] == 1  # original pre-rescue count


def test_trace_records_original_bounded_rescue_when_source_flag_off(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    monkeypatch.delenv("SRAF_EVIDENCE_SOURCE_REFILL", raising=False)
    hit = _hit([
        "金磚 峰會 baseline strong", "金磚 weak one", "峰會 weak two"
    ])
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, evidence, _ = _build([hit])
    assert len(evidence) == 3
    trace, = _traces(caplog)
    assert trace["counters"]["bounded_rescue.selected"] == 2
    assert "source_refill.strict_candidates" not in trace["counters"]


def test_trace_rejects_arbitrary_key_and_non_integer_count(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    trace = EvidenceTrace.from_env()
    assert trace is not None
    trace.stage_count("SENSITIVE-EVENT-ID", 3)
    trace.stage_count("source_refill.weak_selected", True)
    trace.stage_count("bounded_rescue.selected", 9999999999)
    trace.stage_count("bounded_rescue.selected", 2)
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        trace.emit(output_hits=0, output_evidence=0, strict_count=0, relaxed_used=False)
    record, = _traces(caplog)
    assert record["counters"] == {"bounded_rescue.selected": 2}
    assert "SENSITIVE-EVENT-ID" not in json.dumps(record)
