"""#413 A0: non-actionable retrieval slice health and privacy regressions.

Synthetic ES hits only; never connects to ES or invokes an LLM.
"""
from __future__ import annotations

import json
import logging

import pytest

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.models import EvidenceBuildConfig
from agent.es.evidence_core.retrieval_health import assess_retrieval_slice


def _hit(texts: list[str], *, date: str = "2023-08-24") -> dict:
    return {
        "_index": "news_test", "_id": "SENSITIVE-ES-ID",
        "_source": {
            "uuid": "SENSITIVE-UUID",
            "communication": {"subject": "SENSITIVE-SUBJECT"},
            "multidim_event_json": [{
                "article_title": "SENSITIVE-TITLE",
                "Event": [{"event_id": "E1", "time_iso": date,
                           "time_precision": "day"}],
                "Event_Timeline": [],
                "evidence_snippets": [
                    {"text": row, "event_ids": ["E1"]}
                    for row in texts
                ],
            }],
        },
    }


def _build(rows: list[dict], **extras):
    opts = dict(
        date_from="2023-08-24", date_to="2023-08-24",
        effective_terms=["金磚", "峰會"],
        term_groups=[{"金磚"}, {"峰會"}],
        query_for_snippet="SENSITIVE-QUERY",
    )
    opts.update(extras)
    return build_hits_and_evidence(rows, **opts)


def _trace(caplog):
    lines = [
        json.loads(r.message.partition("SRAF_EVIDENCE_TRACE=")[2])
        for r in caplog.records
        if r.name == "sraf.evidence_trace"
        and r.message.startswith("SRAF_EVIDENCE_TRACE=")
    ]
    assert len(lines) == 1
    return lines[0]


def test_pure_health_requires_request_level_assessment_even_if_slice_good():
    h = assess_retrieval_slice({
        "parser.citations_selected": 5,
        "strict.accepted": 4,
        "strict.topic_rejected": 1,
    }, strict_accepted=4)
    assert h.reason == "REQUEST_LEVEL_ASSESSMENT_REQUIRED"
    assert h.parsed == 5 and h.date_eligible == 5
    assert h.known_uninspected == h.known_capped == 0


def test_slice_flags_known_unknown_work_not_presumed_valid():
    h = assess_retrieval_slice({
        "parser.citations_selected": 20,
        "strict.accepted": 20,
        "parser.source_uninspected_after_cap": 5,
    }, strict_accepted=20)
    assert h.reason == "SEARCH_INCOMPLETE"
    assert h.known_uninspected == 5
    assert h.date_eligible == 20


@pytest.mark.parametrize("counts,accepted", [
    ({"strict.accepted": 1, "parser.citations_selected": 0}, 1),
    ({"strict.accepted": 1, "parser.citations_selected": True}, 1),
    ({"strict.accepted": 1, "parser.citations_selected": -1}, 1),
    ({"strict.accepted": 1, "parser.citations_selected": 1}, 0),
    ({"parser.citations_selected": 1, "strict.topic_rejected": 2}, 0),
])
def test_rejects_inconsistent_or_non_numeric_input(counts, accepted):
    with pytest.raises(ValueError):
        assess_retrieval_slice(counts, strict_accepted=accepted)


def test_default_off_returns_exact_output_and_no_trace(monkeypatch, caplog):
    for flag in ("SRAF_EVIDENCE_TRACE", "SRAF_EVIDENCE_RESCUE",
                 "SRAF_EVIDENCE_SOURCE_REFILL",
                 "SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",
                 "SRAF_EVIDENCE_VALID_FAIR_BUDGET"):
        monkeypatch.delenv(flag, raising=False)
    hit = _hit(["金磚 峰會 correct", "金磚 unrelated", "峰會 unrelated"])
    baseline = _build([hit])
    assert not any(r.name == "sraf.evidence_trace" for r in caplog.records)
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        observed = _build([hit])
    assert observed == baseline
    trace = _trace(caplog)
    assert trace["counters"]["health.date_eligible"] == 3
    assert trace["counters"]["health.reason.LOW_STRICT_COVERAGE"] == 1
    assert trace["strict_accepted"] == 1
    assert trace["output_evidence"] == 1
    raw = json.dumps(trace, ensure_ascii=False)
    for forbidden in ("SENSITIVE-", "金磚", "峰會", "2023-08-24"):
        assert forbidden not in raw


def test_known_uninspected_source_is_not_proclaimed_complete(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.delenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_VALID_FAIR_BUDGET", raising=False)
    rows = [_hit(["金磚 峰會 record"] * 25)]
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, ev, _ = _build(rows, config=EvidenceBuildConfig(citations_per_doc=20))
    trace = _trace(caplog)
    assert len(ev) == 20
    assert trace["counters"]["health.known_uninspected"] == 5
    assert trace["counters"]["health.reason.SEARCH_INCOMPLETE"] == 1
    assert trace["counters"]["health.date_eligible"] == 20


def test_event_only_wrong_day_cannot_be_marked_date_eligible(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, ev, _ = _build([_hit(["金磚 峰會 secret"], date="2023-08-25")])
    trace = _trace(caplog)
    assert ev == []
    assert trace["counters"].get("health.date_eligible", 0) == 0
    assert trace["counters"]["health.reason.NO_DATE_ELIGIBLE_CITATIONS"] == 1


def test_zero_hit_slice_does_not_auto_issue_more_queries(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        result = _build([])
    assert result[0] == result[1] == []
    trace = _trace(caplog)
    assert trace["counters"]["health.reason.NO_PARSED_CANDIDATES"] == 1
