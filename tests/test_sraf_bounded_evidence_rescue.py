"""Opt-in low-count Evidence rescue: privacy-safe, bounded, and date-correct.

Exercises real SRAF builder/parser/topic/date validators with synthetic ES rows.
No live ES, LLM calls, SQL, or production mutation.
"""
import pytest

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.rescue import (
    MAX_ANCHOR_DOCUMENTS,
    MAX_CANDIDATE_CHARACTERS,
    MAX_CITATIONS_INSPECTED,
    MAX_CITATIONS_PER_DOCUMENT,
    MAX_POOL_CANDIDATES,
    MAX_POOL_CHARACTERS,
    TARGET_EVIDENCE_COUNT,
    bounded_rescue,
)
from agent.es.evidence_core.models import Citation, EvidenceSnippet, HitDoc


AXES = [{"甲軸"}, {"乙軸"}, {"丙軸"}]


def _citation(text, eid="E1"):
    return {"text": text, "source_id": "S1", "event_ids": [eid]}


def _hit(texts, *, uuid="same-uuid", eid="E1", date="2023-08-24", index="news_a", docid="a"):
    if isinstance(texts[0], str):
        rows = [_citation(t, eid) for t in texts]
    else:
        rows = list(texts)
    return {
        "_index": index, "_id": docid, "_score": 3.0,
        "_source": {
            "uuid": uuid,
            "communication": {"subject": "測試文章"},
            "multidim_event_json": [{
                "article_title": "文章內容",
                "article_date_iso": "2023-08-24",
                "Event": [
                    {"event_id": "E1", "time_iso": date, "time_precision": "day"},
                    {"event_id": "E2", "time_iso": "2023-09-24", "time_precision": "day"},
                ],
                "Event_Timeline": [],
                "evidence_snippets": rows,
            }],
        },
    }


def _build(hits, *, date_from="2023-08-24", date_to="2023-08-24", axes=None):
    return build_hits_and_evidence(
        hits,
        date_from=date_from, date_to=date_to,
        effective_terms=["甲軸", "乙軸", "丙軸"],
        term_groups=AXES if axes is None else axes,
        query_for_snippet="甲軸乙軸丙軸",
    )


def test_default_off_keeps_entire_legacy_result_unchanged(monkeypatch):
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE", raising=False)
    rows = [_hit(["甲軸乙軸丙軸完整事件", "甲軸補充", "乙軸補充", "丙軸補充", "完全無關"])]
    unchanged = _build(rows)
    assert len(unchanged[1]) == 1
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "0")
    assert _build(rows) == unchanged
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "false")
    assert _build(rows) == unchanged


def test_one_of_five_date_valid_strict_rescues_two_bounded_weak(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    rows = [_hit(["甲軸乙軸丙軸完整事件", "甲軸補充", "乙軸補充", "丙軸補充", "完全無關"])]
    hits, evidence, _ = _build(rows)
    assert len(hits) == 1
    assert len(evidence) == TARGET_EVIDENCE_COUNT
    assert evidence[0]["text"] == "甲軸乙軸丙軸完整事件"
    assert evidence[0]["match_policy"] == "strict"
    assert not evidence[0].get("weak_evidence")
    assert [e["text"] for e in evidence[1:]] == ["甲軸補充", "乙軸補充"]
    assert all(e["match_policy"] == "bounded_rescue" for e in evidence[1:])
    assert all(e["weak_evidence"] is True for e in evidence[1:])
    assert all(e["group_hits"] == 1 for e in evidence[1:])
    assert all(e["date_iso"] == "2023-08-24" for e in evidence)
    assert _build(rows)[1] == evidence  # deterministic


def test_date_invalid_evidence_not_rescued_despite_publication_date(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    rows = [_hit([
        _citation("甲軸乙軸丙軸完整事件", "E1"),
        _citation("甲軸不應跨事件借日", "E2"),
        _citation("乙軸合法補充", "E1"),
    ])]
    _, evidence, _ = _build(rows)
    assert [e["text"] for e in evidence] == [
        "甲軸乙軸丙軸完整事件", "乙軸合法補充"
    ]
    assert all(e["date_iso"] == "2023-08-24" for e in evidence)


def test_no_date_guarantee_from_cross_block_duplicate_event_id(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    hit = _hit(["甲軸乙軸丙軸完整事件", "乙軸合法補充"])
    hit["_source"]["multidim_event_json"].append({
        "Event": [{"event_id": "E1", "time_iso": "2024-10-11", "time_precision": "day"}],
        "evidence_snippets": [_citation("甲軸異日事件", "E1")],
    })
    _, evidence, _ = _build([hit])
    assert len(evidence) == 2
    assert {e["text"] for e in evidence} == {
        "甲軸乙軸丙軸完整事件", "乙軸合法補充"
    }


def test_weak_document_cannot_rescue_from_another_same_uuid_hit(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    hits = [
        _hit(["甲軸乙軸丙軸完整事件"], index="news_a", docid="a"),
        _hit(["甲軸另篇補充"], index="news_b", docid="b"),
    ]
    found, evidence, _ = _build(hits)
    assert len(evidence) == 1
    assert found[0]["citations"][0]["text"] == "甲軸乙軸丙軸完整事件"


def test_meta_only_candidate_is_not_rescued(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    hit = _hit(["乙軸丙軸完整事件", "毫不相干文字"])
    hit["_source"]["communication"]["subject"] = "甲軸主題"
    _, evidence, _ = _build([hit])
    assert len(evidence) == 1
    assert evidence[0]["text"] == "乙軸丙軸完整事件"
    assert evidence[0]["match_scope"] == "mixed"


def test_no_rescue_when_strict_is_zero_or_sufficient(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    empty = _hit(["甲軸補充", "乙軸補充"])
    _, found, _ = _build([empty])
    # Existing zero-result relaxation, not the new bounded rescue.
    assert all(e["match_policy"] != "bounded_rescue" for e in found)
    abundant = _hit([
        "甲軸乙軸丙軸事件一",
        "甲軸乙軸丙軸事件二",
        "甲軸乙軸丙軸事件三",
        "甲軸補充",
    ])
    _, found, _ = _build([abundant])
    assert len(found) == 3
    assert all(e["match_policy"] == "strict" for e in found)


def test_no_multi_axis_means_no_rescue(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    hits = [_hit(["甲軸主要事件", "甲軸補充"])]
    _, found, _ = _build(hits, axes=[{"甲軸"}])
    assert len(found) == 2
    assert all(e["match_policy"] == "strict" for e in found)


def test_oversized_candidate_is_skipped_not_truncated(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    huge = "甲軸" + ("資料" * MAX_CANDIDATE_CHARACTERS)
    hit = _hit(["甲軸乙軸丙軸完整事件", huge, "乙軸正常補充"])
    _, found, _ = _build([hit])
    assert [e["text"] for e in found] == [
        "甲軸乙軸丙軸完整事件", "乙軸正常補充"
    ]


def test_500_document_input_has_bounded_rescue_and_no_cross_document(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    hits = [_hit(["甲軸乙軸丙軸事件", "甲軸補充", "乙軸補充"])]
    hits.extend([
        _hit(["甲軸其他文章補充"], index="news_b", docid=f"other-{i}")
        for i in range(500)
    ])
    returned_hits, returned, _ = _build(hits)
    assert len(returned) == TARGET_EVIDENCE_COUNT
    assert len(returned_hits) == 1
    assert all(e["date_iso"] == "2023-08-24" for e in returned)
    assert all(e["uuid"] == "same-uuid" for e in returned)


def test_hard_pool_limits_are_finite():
    assert 0 < MAX_ANCHOR_DOCUMENTS <= 16
    assert 0 < MAX_CITATIONS_INSPECTED <= 128
    assert 0 < MAX_CITATIONS_PER_DOCUMENT <= 20
    assert 0 < MAX_POOL_CANDIDATES <= 32
    assert 0 < MAX_CANDIDATE_CHARACTERS <= 4096
    assert MAX_POOL_CHARACTERS <= 65536
    assert TARGET_EVIDENCE_COUNT <= 4


def test_bounded_rescue_is_pure_and_does_not_call_external_system(monkeypatch):
    import agent.es.evidence_core.rescue as rescue
    monkeypatch.setattr(
        rescue, "build_evidence_snippet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("not allowed to inspect citations with no trusted anchor")
        ),
    )
    only_weak_anchor = EvidenceSnippet(
        uuid="doc", text="甲軸乙軸丙軸", date_iso="2023-08-24",
        article_date_iso="2023-08-24", source_hit_ordinal=0,
        weak_evidence=True, match_scope="meta",
    )
    hit = HitDoc(
        uuid="doc", subject="甲軸", article_title="其他",
        score=5.0, raw_content="", source_hit_ordinal=0,
        citations=[Citation(text="甲軸補充")],
    )
    assert bounded_rescue(
        [hit], [only_weak_anchor], date_from="2023-08-24",
        date_to="2023-08-24", allowed_years=None, term_groups=AXES,
    ) == []
