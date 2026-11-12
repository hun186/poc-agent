"""SRAF P1-c source Evidence refill after ES inner_hits truncation.

Offline fixtures exercise the real parser, Event/Timeline date binding and
Evidence builder. These are NOT private Elasticsearch / report acceptance.
"""
import json

import pytest

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.evidence_core import source_refill


AXES = [{"甲軸"}, {"乙軸"}, {"丙軸"}]
D0 = "2023-08-24"
D1 = "2023-09-24"


def _snippet(text, eid="E1", source_id="S1", paragraph_id=None):
    return {
        "text": text,
        "source_id": source_id,
        "paragraph_id": paragraph_id,
        "event_ids": [eid],
    }


def _inner(row, block_index=0):
    return {
        "_nested": {
            "field": "multidim_event_json",
            "offset": block_index,
            "_nested": {"field": "evidence_snippets", "offset": 0},
        },
        "_source": row,
    }


def _hit(
    source_rows,
    *,
    inner_rows=None,
    uuid="same-uuid",
    index="news_test",
    docid="A",
    multidim=None,
):
    if multidim is None:
        multidim = [{
            "article_date_iso": D0,
            "article_title": "重大事件",
            "Event": [
                {"event_id": "E1", "time_iso": D0, "time_precision": "day"},
                {"event_id": "E2", "time_iso": D1, "time_precision": "day"},
            ],
            "Event_Timeline": [],
            "evidence_snippets": source_rows,
        }]
    item = {
        "_index": index,
        "_id": docid,
        "_score": 5.0,
        "_source": {
            "uuid": uuid,
            "communication": {"subject": "某事件"},
            "multidim_event_json": multidim,
        },
    }
    if inner_rows is not None:
        item["inner_hits"] = {
            "evi": {"hits": {"hits": [
                _inner(row, block_index=0) for row in inner_rows
            ]}}
        }
    return item


def _build(hits, *, allowed_years=None, date_from=D0, date_to=D0):
    return build_hits_and_evidence(
        hits,
        date_from=date_from,
        date_to=date_to,
        allowed_years=allowed_years,
        effective_terms=["甲軸", "乙軸", "丙軸"],
        term_groups=AXES,
        query_for_snippet="甲軸乙軸丙軸",
        include_source_hit_ordinal=True,
    )


def _enable(monkeypatch):
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    monkeypatch.setenv("SRAF_EVIDENCE_SOURCE_REFILL", "1")


def test_unseen_source_citations_restored_from_same_inner_hits_document(monkeypatch):
    rows = [
        _snippet("甲軸乙軸丙軸核心事實"),
        _snippet("這是無關的背景一"),
        _snippet("這是無關的背景二"),
        _snippet("甲軸新增的細節"),
        _snippet("乙軸另一項細節"),
    ]
    h = _hit(rows, inner_rows=rows[:3])
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE", raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_SOURCE_REFILL", raising=False)
    previous = _build([h])
    assert len(previous[1]) == 1
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    assert _build([h]) == previous  # #404 alone cannot see omitted source
    _enable(monkeypatch)
    hits, evidence, _ = _build([h])
    assert len(hits) == 1
    assert [x["text"] for x in evidence] == [
        "甲軸乙軸丙軸核心事實", "甲軸新增的細節", "乙軸另一項細節"
    ]
    assert [x["match_policy"] for x in evidence] == [
        "strict", "bounded_rescue", "bounded_rescue"
    ]
    assert all(x["date_iso"] == D0 and x["weak_evidence"] is True
               for x in evidence[1:])
    assert len(hits[0]["citations"]) == 5
    assert _build([h])[1] == evidence  # stable deterministic order


def test_strict_source_match_outranks_weak_inner_and_source(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("甲軸這是弱補充"),
        _snippet("與主題無關的內容"),
        _snippet("甲軸乙軸丙軸新找到的強證據"),
        _snippet("乙軸另一段補充"),
    ]
    _, ev, _ = _build([_hit(rows, inner_rows=rows[:3])])
    assert [x["text"] for x in ev] == [
        "甲軸乙軸丙軸核心",
        "甲軸乙軸丙軸新找到的強證據",
        "甲軸這是弱補充",
    ]
    assert [x["match_policy"] for x in ev] == [
        "strict", "strict", "bounded_rescue"
    ]


def test_wrong_event_date_and_publication_date_do_not_authorize_source_refill(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心", "E1"),
        _snippet("與主題無關的背景"),
        _snippet("其他無關內容"),
        _snippet("甲軸屬於另一事件的資訊", "E2"),
        _snippet("乙軸有效的進展", "E1"),
    ]
    _, evidence, _ = _build([_hit(rows, inner_rows=rows[:3])])
    assert [x["text"] for x in evidence] == [
        "甲軸乙軸丙軸核心", "乙軸有效的進展"
    ]
    assert all(x["date_iso"] == D0 for x in evidence)


def test_same_event_id_in_different_blocks_remains_block_local(monkeypatch):
    _enable(monkeypatch)
    blocks = [
        {
            "article_date_iso": D0,
            "Event": [{"event_id": "E1", "time_iso": D0}],
            "Event_Timeline": [],
            "evidence_snippets": [
                _snippet("甲軸乙軸丙軸核心"),
                _snippet("甲軸補充第一區塊"),
            ],
        },
        {
            "article_date_iso": D0,
            "Event": [{"event_id": "E1", "time_iso": D1}],
            "Event_Timeline": [],
            "evidence_snippets": [_snippet("乙軸第二區塊日期不符")],
        },
    ]
    h = _hit([], inner_rows=[blocks[0]["evidence_snippets"][0]],
             multidim=blocks)
    _, evidence, _ = _build([h])
    assert [x["text"] for x in evidence] == [
        "甲軸乙軸丙軸核心", "甲軸補充第一區塊"
    ]
    assert all(x["date_iso"] == D0 for x in evidence)


def test_multiple_event_ids_must_all_be_resolved_before_refill(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"),
        _snippet("無關二"),
        {"text": "甲軸日期不明", "event_ids": ["E1", "E_UNKNOWN"], "source_id": "S2"},
        _snippet("乙軸正常補充"),
    ]
    _, ev, _ = _build([_hit(rows, inner_rows=rows[:3])])
    assert [e["text"] for e in ev] == [
        "甲軸乙軸丙軸核心", "乙軸正常補充"
    ]


def test_same_uuid_different_index_never_supplies_unanchored_source(monkeypatch):
    _enable(monkeypatch)
    a = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("與主題無關一"), _snippet("與主題無關二"),
    ]
    b = [
        _snippet("甲軸並不是本篇強證據"), _snippet("乙軸新內容"),
        _snippet("丙軸更多內容"), _snippet("甲軸後續段落"),
    ]
    hits = [
        _hit(a, inner_rows=a, index="news_a", docid="A"),
        _hit(b, inner_rows=b[:3], index="news_b", docid="B"),
    ]
    _, ev, _ = _build(hits)
    assert len(ev) == 1
    assert ev[0]["text"] == "甲軸乙軸丙軸核心"
    assert all(x["__sraf_source_hit_ordinal"] == 0 for x in ev)


def test_source_flag_alone_has_no_effect(monkeypatch):
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("甲軸補充"),
    ]
    h = _hit(rows, inner_rows=rows[:3])
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE", raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_SOURCE_REFILL", raising=False)
    baseline = _build([h])
    monkeypatch.setenv("SRAF_EVIDENCE_SOURCE_REFILL", "1")
    assert _build([h]) == baseline
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "false")
    assert _build([h]) == baseline


def test_zero_strict_count_never_uses_source_to_invent_anchor(monkeypatch):
    _enable(monkeypatch)
    source_rows = [
        _snippet("甲軸只有一軸"),
        _snippet("乙軸只有一軸"),
        _snippet("無關內容"),
        _snippet("甲軸乙軸丙軸未被取到的強段"),
    ]
    h = _hit(source_rows, inner_rows=source_rows[:3])
    _, ev, _ = _build([h])
    assert all(e["text"] != source_rows[-1]["text"] for e in ev)


def test_no_date_context_does_not_infer_event_date_from_article(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心", "E1"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("乙軸沒有對應Event的候選", "E_X"),
    ]
    _, ev, _ = _build([_hit(rows, inner_rows=rows[:3])],
                       date_from=None, date_to=None)
    assert all("沒有對應Event" not in e["text"] for e in ev)


def test_json_encoded_source_block_is_supported_if_bounded(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("乙軸 JSON 新段"),
    ]
    h = _hit(rows, inner_rows=rows[:3])
    h["_source"]["multidim_event_json"] = json.dumps(
        h["_source"]["multidim_event_json"], ensure_ascii=False
    )
    _, ev, _ = _build([h])
    assert [x["text"] for x in ev] == [
        "甲軸乙軸丙軸核心", "乙軸 JSON 新段"
    ]


def test_source_refill_only_inspects_bounded_candidates(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
    ]
    rows.extend(_snippet(f"甲軸巨量資料第{i}段") for i in range(500))
    h = _hit(rows, inner_rows=rows[:3])
    _, ev, _ = _build([h])
    assert len(ev) <= 3
    assert all(e["__sraf_source_hit_ordinal"] == 0 for e in ev)
    assert source_refill.MAX_SOURCE_CITATIONS_SCANNED <= 64
    assert source_refill.MAX_SOURCE_CITATIONS_PARSED <= 16
    assert source_refill.MAX_SOURCE_DOCUMENTS <= 4
    assert source_refill.MAX_SOURCE_CANDIDATES <= 16


def test_excessive_source_string_is_safely_skipped(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("甲軸嘗試補回"),
    ]
    h = _hit(rows, inner_rows=rows[:3])
    h["_source"]["multidim_event_json"] = "x" * (
        source_refill.MAX_SOURCE_JSON_CHARS + 1
    )
    # Parser itself receives an invalid JSON block and uses fallback, so
    # source-refill must not produce a fabricated result.
    _, ev, _ = _build([h], date_from=None, date_to=None)
    assert all("嘗試補回" not in e["text"] for e in ev)


def test_huge_candidate_skipped_but_short_source_passes(monkeypatch):
    _enable(monkeypatch)
    huge = "甲軸" + ("字" * (source_refill.MAX_SOURCE_TEXT_CHARS + 1))
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet(huge),
        _snippet("乙軸正常來源補充"),
    ]
    _, ev, _ = _build([_hit(rows, inner_rows=rows[:3])])
    assert [e["text"] for e in ev] == [
        "甲軸乙軸丙軸核心", "乙軸正常來源補充"
    ]


def test_no_inner_hits_source_already_parsed_is_not_re_read(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("甲軸直接從source讀取"),
    ]
    h = _hit(rows, inner_rows=None)
    _, ev, _ = _build([h])
    assert [e["text"] for e in ev] == [
        "甲軸乙軸丙軸核心", "甲軸直接從source讀取"
    ]
    assert ev[1]["match_policy"] == "bounded_rescue"


@pytest.mark.parametrize("field", ["event_ids", "source_id", "paragraph_id"])
def test_source_identifier_bomb_rejected_before_parse(monkeypatch, field):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("甲軸惡意超長欄位"),
        _snippet("乙軸正常後續"),
    ]
    if field == "event_ids":
        # Reproduces the P1 review: short text, 100k JSON-encoded IDs.
        rows[3][field] = json.dumps(["E1"] * 100_000)
    else:
        rows[3][field] = "X" * 600_000
    h = _hit(rows, inner_rows=rows[:3])
    _, evidence, _ = _build([h])
    assert [ev["text"] for ev in evidence] == [
        "甲軸乙軸丙軸核心", "乙軸正常後續"
    ]
    assert len(str(evidence)) < 10000


@pytest.mark.parametrize("encoded", [False, True])
def test_source_event_ids_over_cardinality_cap_are_not_truncated(monkeypatch, encoded):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("甲軸不應只取部分Event"),
        _snippet("乙軸後續合法資料"),
    ]
    ids = ["E1"] * (source_refill.MAX_IDS_PER_FIELD + 1)
    rows[3]["event_ids"] = json.dumps(ids) if encoded else ids
    _, ev, _ = _build([_hit(rows, inner_rows=rows[:3])])
    assert [x["text"] for x in ev] == [
        "甲軸乙軸丙軸核心", "乙軸後續合法資料"
    ]


def test_oversized_structured_timeline_identifiers_fail_closed(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("甲軸理應放棄這個結構化文件"),
    ]
    h = _hit(rows, inner_rows=rows[:3])
    h["_source"]["multidim_event_json"][0]["Event_Timeline"] = [{
        "event_ids": json.dumps(["E1"] * 100_000),
        "time_iso": D0,
        "time_precision": "day",
    }]
    _, ev, _ = _build([h])
    assert [x["text"] for x in ev] == ["甲軸乙軸丙軸核心"]


def test_rejected_id_does_not_create_partial_event_link(monkeypatch):
    _enable(monkeypatch)
    rows = [
        _snippet("甲軸乙軸丙軸核心"),
        _snippet("無關一"), _snippet("無關二"),
        _snippet("甲軸包含無法確認的事件"),
    ]
    rows[3]["event_ids"] = ["E1", "E_UNKNOWN" * 100]
    _, ev, _ = _build([_hit(rows, inner_rows=rows[:3])])
    assert [x["text"] for x in ev] == ["甲軸乙軸丙軸核心"]
