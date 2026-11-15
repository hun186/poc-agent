"""Bounded shared Evidence source candidate budget: 500-row server documents.

All rows are synthetic; exercises real ES-result parser and Evidence date/topic
guard. Never contacts Elasticsearch, SQL, LLM, runtime services or real data.
"""
from __future__ import annotations

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core.parser import parse_es_hits
from agent.es.evidence_core.models import EvidenceBuildConfig


D0 = "2023-08-24"
D1 = "2023-09-24"


def _hit(count, doc="big-doc", *, other_date_every=0, inner=True):
    snippets = [
        {
            "text": f"甲軸乙軸丙軸資訊第{i}筆",
            "source_id": f"record-{i}",
            "paragraph_id": str(i),
            "event_ids": (["E2"] if other_date_every and i % other_date_every == 1 else ["E1"]),
        }
        for i in range(count)
    ]
    block = {
        "article_title": "結構化 Server 記錄",
        "article_date_iso": "2026-01-01",  # distinct from actual event time
        "Event": [
            {"event_id": "E1", "time_iso": D0, "time_precision": "day"},
            {"event_id": "E2", "time_iso": D1, "time_precision": "day"},
        ],
        "Event_Timeline": [],
        "evidence_snippets": snippets,
    }
    hit = {
        "_id": doc, "_index": "news_test", "_score": 5.0,
        "_source": {
            "uuid": doc,
            "communication": {"subject": "結構化伺服器"},
            "multidim_event_json": [block],
        },
    }
    if inner:
        hit["inner_hits"] = {
            "evi": {"hits": {"hits": [
                {
                    "_nested": {"field": "multidim_event_json", "offset": 0,
                                "_nested": {"field": "evidence_snippets", "offset": i}},
                    "_source": snippets[i],
                }
                for i in range(min(3, count))
            ]}}
        }
    return hit


def _build(rows, *, date_from=D0, date_to=D0):
    return build_hits_and_evidence(
        rows, date_from=date_from, date_to=date_to,
        effective_terms=["甲軸", "乙軸", "丙軸"],
        term_groups=[{"甲軸"}, {"乙軸"}, {"丙軸"}],
        query_for_snippet="甲軸乙軸丙軸",
    )


def test_default_off_retains_inner_hits_3_and_source_fallback_20(monkeypatch):
    monkeypatch.delenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", raising=False)
    doc = _hit(500)
    assert len(_build([doc])[1]) == 3
    assert len(_build([_hit(500, inner=False)])[1]) == 20
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "0")
    assert len(_build([doc])[1]) == 3


def test_single_500_row_document_is_not_stuck_at_3_or_20(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    doc = _hit(500)
    parsed, stats = parse_es_hits(
        [doc], query_for_snippet="甲軸乙軸丙軸", config=EvidenceBuildConfig(
            shared_citation_budget=1024,
        ),
    )
    assert len(parsed[0].citations) == 500
    assert stats["n_total_citations"] == 500
    hits, ev, _ = _build([doc])
    assert len(hits) == 1
    assert len(ev) == 500
    assert len({e["text"] for e in ev}) == 500
    assert all(e["date_iso"] == D0 for e in ev)
    assert all(e["article_date_iso"] == "2026-01-01" for e in ev)


def test_wrong_date_evidence_never_borrows_core_event_date(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    hit = _hit(500, other_date_every=2)
    _, ev, _ = _build([hit])
    assert len(ev) == 250
    assert all(int(e["paragraph_id"]) % 2 == 0 for e in ev)
    assert _build([hit], date_from="2024-01-01", date_to="2024-01-31")[1] == []


def test_global_budget_is_shared_across_documents_not_20_each(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    first, second = _hit(800, "A"), _hit(500, "B")
    parsed, stats = parse_es_hits(
        [first, second], query_for_snippet="甲軸乙軸丙軸",
        config=EvidenceBuildConfig(shared_citation_budget=1024),
    )
    assert [len(hit.citations) for hit in parsed] == [800, 224]
    assert stats["n_total_citations"] == 1024
    _, ev, _ = _build([first, second])
    assert len(ev) == 1024
    assert sum(e["uuid"] == "A" for e in ev) == 800
    assert sum(e["uuid"] == "B" for e in ev) == 224


def test_second_small_document_retained_when_total_fits(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    _, ev, _ = _build([_hit(500, "A"), _hit(12, "B")])
    assert len(ev) == 512
    assert sum(x["uuid"] == "A" for x in ev) == 500
    assert sum(x["uuid"] == "B" for x in ev) == 12


def test_duplicate_event_ids_in_other_blocks_keep_local_scope(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    hit = _hit(4, inner=False)
    block2 = {
        "article_title": "相同 E1 但不同 block",
        "Event": [{"event_id": "E1", "time_iso": D1, "time_precision": "day"}],
        "Event_Timeline": [],
        "evidence_snippets": [
            {"event_ids": ["E1"], "text": "甲軸乙軸丙軸異日第0筆"},
        ],
    }
    hit["_source"]["multidim_event_json"].append(block2)
    _, ev, _ = _build([hit])
    assert len(ev) == 4
    assert all("異日" not in e["text"] for e in ev)


def test_opt_in_is_bounded_by_global_scan_and_character_ceiling(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    long_doc = _hit(2000)
    _, ev, _ = _build([long_doc])
    assert 0 < len(ev) <= 1024
    # Input remains untouched; no mutation of source JSON / Event identities.
    assert len(long_doc["_source"]["multidim_event_json"][0]["evidence_snippets"]) == 2000


def test_unstructured_docs_do_not_unintentionally_gain_large_budget(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET", "1")
    hit = _hit(500, inner=False)
    block = hit["_source"]["multidim_event_json"][0]
    block.pop("Event")
    block.pop("Event_Timeline")
    parsed, _ = parse_es_hits(
        [hit], query_for_snippet="甲軸乙軸丙軸",
        config=EvidenceBuildConfig(shared_citation_budget=1024),
    )
    assert len(parsed[0].citations) == 20
