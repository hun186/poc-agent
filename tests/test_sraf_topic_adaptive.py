"""Offline synthetic A/B of low-count, original-subject-anchored 3->2."""
from __future__ import annotations

import json
import logging

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.models import Citation, HitDoc
from agent.es.evidence_core.question_anchor import derive_explicit_question_anchor
from agent.es.evidence_core.topic_adaptive import (
    MAX_SCAN, consider_low_count,
)

from test_sraf_topic_shadow import _build, _hit, GROUPS

QUESTION = "主題：加薩\n請分析2023年停火、醫療與人道援助"


def _clean(monkeypatch):
    for key in (
        "SRAF_TOPIC_MATCH_ADAPTIVE", "SRAF_EVIDENCE_RESCUE",
        "SRAF_EVIDENCE_SOURCE_REFILL", "SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",
        "SRAF_EVIDENCE_VALID_FAIR_BUDGET", "SRAF_EVIDENCE_TRACE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_exact_equivalence_no_adaptive_log(monkeypatch, caplog):
    _clean(monkeypatch)
    baseline = _build([_hit()], original_question=QUESTION)
    assert len(baseline[1]) == 1
    assert baseline[1][0]["match_policy"] == "strict"
    assert not any("SRAF_TOPIC_ADAPTIVE" in row.message for row in caplog.records)


def test_shadow_does_not_admit_but_audits_proposals(monkeypatch, caplog):
    _clean(monkeypatch)
    baseline = _build([_hit()], original_question=QUESTION)
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "shadow")
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    with caplog.at_level(logging.WARNING):
        observed = _build([_hit()], original_question=QUESTION)
    assert observed == baseline
    audits = [r.message for r in caplog.records if
              r.name == "sraf.topic_adaptive" and "SRAF_TOPIC_ADAPTIVE" in r.message]
    assert len(audits) == 1
    assert "mode=shadow" in audits[0]
    assert "status=shadow" in audits[0]
    assert "proposed=2" in audits[0] and "selected=0" in audits[0]
    records = [json.loads(r.message.split("SRAF_EVIDENCE_TRACE=", 1)[1])
               for r in caplog.records if r.name == "sraf.evidence_trace"
               and r.message.startswith("SRAF_EVIDENCE_TRACE=")]
    assert len(records) == 1
    assert records[0]["counters"]["adaptive_3to2.proposed"] == 2
    assert records[0]["counters"]["adaptive_3to2.selected"] == 0
    private = json.dumps(records[0], ensure_ascii=False) + audits[0]
    for term in ("加薩", "PRIVATE", "STRONG-SECRET", "2023-08-24", "E1"):
        assert term not in private


def test_opt_in_promotes_only_two_bounded_weak_evidence(monkeypatch, caplog):
    _clean(monkeypatch)
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")
    with caplog.at_level(logging.WARNING):
        _, rows, _ = _build([_hit()], original_question=QUESTION)
    assert len(rows) == 3
    assert [e["match_policy"] for e in rows] == [
        "strict", "adaptive_two_axis", "adaptive_two_axis"
    ]
    assert [e.get("weak_evidence") for e in rows] == [None, True, True]
    assert rows[1]["text"].startswith("加薩 醫療")
    assert rows[2]["text"].startswith("聯合國 人道援助")
    assert all(e["date_iso"] == "2023-08-24" for e in rows)
    assert all("WRONG-DATE" not in e["text"] for e in rows)
    assert any("proposed=2 selected=2" in r.message for r in caplog.records
               if r.name == "sraf.topic_adaptive")


def test_absent_ambiguous_or_negated_question_fails_closed(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")
    for q in (
        None, "分析加薩停火", "主題：加薩\n主題：蘇丹",
        "主題：加薩\n請排除加薩", "主題：蘇丹\n分析加薩",
    ):
        _, evidence, _ = _build([_hit()], original_question=q)
        assert len(evidence) == 1
        assert evidence[0]["match_policy"] == "strict"


def test_bounded_and_no_meta_only_or_cross_event_borrow(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")
    rows = _hit()
    # Same source hit but different Event ID: cannot borrow the Gaza
    # context from Event E1 when the direct subject is missing.
    structured = rows["_source"]["multidim_event_json"][0]
    structured["Event"][1]["time_iso"] = "2023-08-24"
    structured["evidence_snippets"].append({
        "text": "聯合國 醫療 CROSS-EVENT-SECRET", "event_ids": ["E2"]
    })
    structured["evidence_snippets"].append({
        "text": "UNRELATED META-ONLY-SECRET", "event_ids": ["E1"]
    })
    _, evidence, _ = _build([rows], original_question=QUESTION)
    assert len(evidence) == 3
    assert all("CROSS-EVENT-SECRET" not in e["text"] for e in evidence)
    assert all("META-ONLY-SECRET" not in e["text"] for e in evidence)


def test_not_low_or_fewer_than_four_axes_never_promotes(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE", "on")
    _, rows, _ = _build([_hit()], groups=GROUPS[:3], original_question=QUESTION)
    assert all(e["match_policy"] != "adaptive_two_axis" for e in rows)
    # Empty strict scope is handled by the existing zero-only fallback,
    # not by the new nonzero adaptive stage.
    empty = _hit()
    for row in empty["_source"]["multidim_event_json"][0]["evidence_snippets"]:
        row["text"] = "無關內文"
    _, rows, _ = _build([empty], original_question=QUESTION)
    assert all(e["match_policy"] != "adaptive_two_axis" for e in rows)


def test_only_one_slice_scan_is_bounded(monkeypatch):
    anchor = derive_explicit_question_anchor(QUESTION, GROUPS)
    assert anchor is not None
    hit = HitDoc(
        uuid="synthetic", subject=None, article_title=None, score=0.0,
        raw_content="", source_hit_ordinal=0, citations=[
            Citation(text="加薩 醫療", date_iso="2023-08-24")
            for _ in range(MAX_SCAN + 16)
        ],
    )
    strict = [
        # use canonical build path to create baseline strong evidence
        # (a synthetic strict passage with matching date and subject)
    ]
    from agent.es.evidence_core.snippet import build_evidence_snippet
    strong = build_evidence_snippet(
        hit, Citation(text="加薩 停火 人道援助", date_iso="2023-08-24"),
        date_from="2023-08-24", date_to="2023-08-24", allowed_years=None,
    )
    assert strong is not None
    strong.match_scope = "text"
    strong.match_policy = "strict"
    result = consider_low_count(
        [hit], [strong], date_from="2023-08-24", date_to="2023-08-24",
        allowed_years=None, groups=GROUPS, anchor=anchor, mode="on",
    )
    assert result.inspected == MAX_SCAN
    assert result.uninspected_by_cap == 16
    assert result.selected <= 2
