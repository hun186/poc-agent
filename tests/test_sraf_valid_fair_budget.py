"""SRAF valid Evidence count after canonical date/topic filters and fair hit quotas.

Uses real parser/builder, fully synthetic ES input, no ES/SQL/LLM/network.
This feature is OFF by default and requires *both* opt-in flags.
"""
from __future__ import annotations

import json
import logging

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.fair_budget import (
    allocate_fair_source_quotas, select_valid_fair_evidence,
)

from test_sraf_shared_evidence_budget import _hit, D0, D1


AXES = [{"甲軸"}, {"乙軸"}, {"丙軸"}]


def _build(hits, *, date_from=D0, date_to=D0):
    return build_hits_and_evidence(
        hits, date_from=date_from, date_to=date_to,
        effective_terms=["甲軸", "乙軸", "丙軸"],
        term_groups=AXES,
        query_for_snippet="甲軸乙軸丙軸",
    )


def _enable(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_VALID_FAIR_BUDGET", "1")
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE", raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_SOURCE_REFILL", raising=False)


def test_is_noop_without_both_explicit_flags(monkeypatch):
    doc = _hit(500)
    monkeypatch.delenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_VALID_FAIR_BUDGET", raising=False)
    baseline = _build([doc])
    assert len(baseline[1]) == 3

    monkeypatch.setenv("SRAF_EVIDENCE_VALID_FAIR_BUDGET", "1")
    assert _build([doc]) == baseline
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    assert len(_build([doc])[1]) == 500
    monkeypatch.setenv("SRAF_EVIDENCE_VALID_FAIR_BUDGET", "0")
    assert len(_build([doc])[1]) == 500


def test_500_plus_12_records_use_available_global_capacity(monkeypatch):
    _enable(monkeypatch)
    a, b = _hit(500, "A"), _hit(12, "B")
    assert allocate_fair_source_quotas([a, b]) == [500, 12]
    hits, ev, _ = _build([a, b])
    assert len(hits) == 2
    assert len(ev) == 512
    assert sum(row["uuid"] == "A" for row in ev) == 500
    assert sum(row["uuid"] == "B" for row in ev) == 12
    assert all(row["date_iso"] == D0 for row in ev)


def test_invalid_dates_do_not_consume_final_valid_budget(monkeypatch):
    doc = _hit(1100, "late-valid", inner=False)
    rows = doc["_source"]["multidim_event_json"][0]["evidence_snippets"]
    for i in range(980):
        rows[i]["event_ids"] = ["E2"]
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    monkeypatch.delenv("SRAF_EVIDENCE_VALID_FAIR_BUDGET", raising=False)
    old = _build([doc])[1]
    assert len(old) == 44  # previous first 1024 candidates
    _enable(monkeypatch)
    current = _build([doc])[1]
    assert len(current) == 120
    assert all(e["date_iso"] == D0 for e in current)
    assert all(int(e["paragraph_id"]) >= 980 for e in current)
    assert _build([doc], date_from="2024-01-01", date_to="2024-01-31")[1] == []


def test_invalid_topic_does_not_consume_final_valid_budget(monkeypatch):
    doc = _hit(1100, "late-topic", inner=False)
    rows = doc["_source"]["multidim_event_json"][0]["evidence_snippets"]
    for i in range(1000):
        rows[i]["text"] = f"無關背景資料第{i}筆"
    _enable(monkeypatch)
    _, result, _ = _build([doc])
    assert len(result) == 100
    assert all("甲軸乙軸丙軸" in e["text"] for e in result)


def test_large_first_hit_does_not_starve_small_later_valid_hit(monkeypatch):
    _enable(monkeypatch)
    a, b = _hit(2000, "many-wrong", inner=False), _hit(12, "small-valid")
    for item in a["_source"]["multidim_event_json"][0]["evidence_snippets"]:
        item["event_ids"] = ["E2"]
    assert allocate_fair_source_quotas([a, b]) == [2000, 12]
    hits, result, _ = _build([a, b])
    assert len(result) == 12
    assert len(hits) == 1
    assert all(e["uuid"] == "small-valid" and e["date_iso"] == D0
               for e in result)


def test_fair_round_robin_after_date_topic_validation(monkeypatch):
    _enable(monkeypatch)
    a, b = _hit(800, "A"), _hit(500, "B")
    hits, rows, _ = _build([a, b])
    assert len(hits) == 2
    assert len(rows) == 1024
    assert sum(e["uuid"] == "A" for e in rows) == 524
    assert sum(e["uuid"] == "B" for e in rows) == 500
    # Every B source gets a chance before A's unbounded long tail.
    # When B's 500 items are exhausted, A uses the remaining 524 slots.
    assert rows[0]["uuid"] == "A" and rows[1]["uuid"] == "B"


def test_identical_uuid_across_indices_still_has_distinct_es_hit_origin(monkeypatch):
    _enable(monkeypatch)
    a, b = _hit(800, "shared-uuid"), _hit(800, "shared-uuid")
    a["_index"], b["_index"] = "archive", "news_test"
    a["_id"], b["_id"] = "A", "B"
    _, rows, _ = _build([a, b])
    assert len(rows) == 1024
    # Distinct ES-hit ordinals are not merged by application UUID.
    assert rows[0]["paragraph_id"] == "0"
    assert rows[1]["paragraph_id"] == "0"
    assert rows[2]["paragraph_id"] == "1"


def test_single_article_never_hits_per_document_20_cap(monkeypatch):
    _enable(monkeypatch)
    _, evidence, _ = _build([_hit(500)])
    assert len(evidence) == 500
    assert all(e["date_iso"] == D0 for e in evidence)


def test_byte_budget_reserved_for_later_document(monkeypatch):
    _enable(monkeypatch)
    a, b = _hit(900, "long-A", inner=False), _hit(12, "small-B", inner=False)
    for row in a["_source"]["multidim_event_json"][0]["evidence_snippets"]:
        row["text"] = "甲軸乙軸丙軸" + "X" * 3490
    _, evidence, _ = _build([a, b])
    assert any(e["uuid"] == "small-B" for e in evidence)
    assert sum(e["uuid"] == "small-B" for e in evidence) == 12
    assert len(evidence) <= 1024


def test_trace_shows_valid_before_after_and_never_logs_private_data(
        monkeypatch, caplog):
    _enable(monkeypatch)
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    a, b = _hit(800, "SENSITIVE-A"), _hit(500, "SENSITIVE-B")
    with caplog.at_level(logging.WARNING, logger="sraf.evidence_trace"):
        _, rows, _ = _build([a, b])
    payloads = [
        json.loads(record.message.split("SRAF_EVIDENCE_TRACE=", 1)[1])
        for record in caplog.records
        if record.name == "sraf.evidence_trace"
        and record.message.startswith("SRAF_EVIDENCE_TRACE=")
    ]
    assert len(payloads) == 1
    counters = payloads[0]["counters"]
    assert counters["valid_budget.eligible"] == 1300
    assert counters["valid_budget.selected"] == 1024
    assert counters["valid_budget.not_selected"] == 276
    assert payloads[0]["output_evidence"] == len(rows) == 1024
    text = json.dumps(payloads[0], ensure_ascii=False)
    for sensitive in ("SENSITIVE-", "甲軸", "乙軸", "丙軸",
                      "2023-08-24", "record-"):
        assert sensitive not in text


def test_helper_invalid_limits_fail_closed():
    a, b = _hit(800, "A"), _hit(50, "B")
    assert allocate_fair_source_quotas([a, b], -1) == [0, 0]
    assert allocate_fair_source_quotas([a, b], 999999) == [0, 0]
    assert select_valid_fair_evidence([1, 2, 3], -1) == []


def test_single_later_long_valid_source_does_not_lose_byte_allocation(monkeypatch):
    _enable(monkeypatch)
    a, b = _hit(2000, "huge-wrong", inner=False), _hit(1, "tiny-long", inner=False)
    for row in a["_source"]["multidim_event_json"][0]["evidence_snippets"]:
        row["event_ids"] = ["E2"]
    b["_source"]["multidim_event_json"][0]["evidence_snippets"][0]["text"] = (
        "甲軸乙軸丙軸" + "Y" * 2500
    )
    from agent.es.evidence_core.fair_budget import source_text_quotas
    byte_shares = source_text_quotas(allocate_fair_source_quotas([a, b]))
    assert byte_shares[1] >= 2500
    assert sum(byte_shares) <= 1048576
    _, ev, _ = _build([a, b])
    assert len(ev) == 1
    assert ev[0]["uuid"] == "tiny-long"


def test_nested_evi_only_source_keeps_all_three_inner_hits(monkeypatch):
    _enable(monkeypatch)
    doc = _hit(3, "inner-only")
    del doc["_source"]["multidim_event_json"][0]["evidence_snippets"]
    quotas = allocate_fair_source_quotas([doc])
    assert quotas == [3]
    _, rows, _ = _build([doc])
    assert len(rows) == 3
    assert all(row["uuid"] == "inner-only" for row in rows)


def test_byte_quota_when_zero_capacity_fails_closed():
    from agent.es.evidence_core.fair_budget import source_text_quotas
    assert source_text_quotas([2, 1], -1) == [0, 0]
    assert source_text_quotas([2, 1], 99999999) == [0, 0]
    assert source_text_quotas([2, 1], 0) == [0, 0]


def test_unused_text_reservation_flows_forward_to_last_long_valid_doc(monkeypatch):
    """Many tiny earlier docs must not strand available global text budget."""
    _enable(monkeypatch)
    hits = [_hit(1, f"tiny-{i}", inner=False) for i in range(300)]
    last = _hit(1, "last-long", inner=False)
    last["_source"]["multidim_event_json"][0]["evidence_snippets"][0]["text"] = (
        "甲軸乙軸丙軸" + "Z" * 3990
    )
    hits.append(last)
    _, evidence, _ = _build(hits)
    assert len(evidence) == 301
    assert evidence[-1]["uuid"] == "last-long"
    assert len(evidence[-1]["text"]) > 3900
