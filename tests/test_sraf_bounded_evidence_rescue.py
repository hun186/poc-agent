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



def test_different_valid_event_same_day_does_not_borrow_weak_topic_anchor(monkeypatch):
    """Both events pass the date filter; only E1 is linked to strict Evidence."""
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    monkeypatch.delenv("SRAF_EVIDENCE_SOURCE_REFILL", raising=False)
    hit = _hit([
        _citation("甲軸乙軸丙軸 E1 完整", "E1"),
        _citation("甲軸 E2 另一件事", "E2"),
        _citation("乙軸 E1 延伸", "E1"),
    ])
    # Same date for both structured Events; a date-only guard would admit E2.
    hit["_source"]["multidim_event_json"][0]["Event"][1]["time_iso"] = "2023-08-24"
    _, evidence, _ = _build([hit])
    assert [row["text"] for row in evidence] == [
        "甲軸乙軸丙軸 E1 完整", "乙軸 E1 延伸",
    ]
    assert evidence[1]["match_policy"] == "bounded_rescue"


def test_reused_event_id_in_another_valid_block_cannot_borrow_anchor(monkeypatch):
    """Block-local Event ID E1 is not the same event across two blocks."""
    monkeypatch.setenv("SRAF_EVIDENCE_RESCUE", "1")
    monkeypatch.delenv("SRAF_EVIDENCE_SOURCE_REFILL", raising=False)
    hit = _hit([
        _citation("甲軸乙軸丙軸 block0 strong", "E1"),
        _citation("甲軸 block0 weak", "E1"),
    ])
    hit["_source"]["multidim_event_json"].append({
        "article_date_iso": "2023-08-24",
        "Event": [{"event_id": "E1", "time_iso": "2023-08-24",
                   "time_precision": "day"}],
        "Event_Timeline": [],
        "evidence_snippets": [_citation("乙軸 block1 unrelated", "E1")],
    })
    _, evidence, _ = _build([hit])
    assert [row["text"] for row in evidence] == [
        "甲軸乙軸丙軸 block0 strong", "甲軸 block0 weak",
    ]


def test_missing_block_or_event_identity_fails_closed_for_structured_hit():
    from agent.es.evidence_core.event_anchor import same_event_as_strict_anchor

    hit = HitDoc(
        uuid="id", subject=None, article_title=None, score=0.0,
        raw_content="", source_hit_ordinal=7, has_structured_events=True,
    )
    strong = EvidenceSnippet(
        uuid="id", text="strong", date_iso="2023-08-24",
        article_date_iso="2023-08-24", source_hit_ordinal=7,
        block_index=0, event_ids=["E1"],
    )
    assert same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E1"], block_index=0), strong,
    )
    assert not same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E2"], block_index=0), strong,
    )
    assert not same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E1"], block_index=1), strong,
    )
    assert not same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E1"], block_index=None), strong,
    )
    assert not same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E1"], block_index=0),
        EvidenceSnippet(
            uuid="id", text="strong", date_iso="2023-08-24",
            article_date_iso="2023-08-24", source_hit_ordinal=7,
            block_index=None, event_ids=["E1"],
        ),
    )
    assert not same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E1"], block_index=0),
        EvidenceSnippet(
            uuid="id", text="strong", date_iso="2023-08-24",
            article_date_iso="2023-08-24", source_hit_ordinal=8,
            block_index=0, event_ids=["E1"],
        ),
    )
    assert not same_event_as_strict_anchor(
        hit, Citation(text="weak", event_ids=["E1"] * 17, block_index=0), strong,
    )


def test_legacy_nonstructured_same_hit_rescue_behavior_is_retained():
    from agent.es.evidence_core.event_anchor import same_event_as_strict_anchor

    legacy = HitDoc(
        uuid="id", subject=None, article_title=None, score=0.0,
        raw_content="", source_hit_ordinal=3, has_structured_events=False,
    )
    anchor = EvidenceSnippet(
        uuid="id", text="strong", date_iso="2023-08-24",
        article_date_iso="2023-08-24", source_hit_ordinal=3,
    )
    assert same_event_as_strict_anchor(legacy, Citation(text="weak"), anchor)


def _a8_row(i, text, weak=False, scope="text", **kwargs):
    from agent.es.evidence_core.models import EvidenceSnippet
    return EvidenceSnippet(uuid="PRIVATE_UUID", text=text,
                           date_iso="2023-08-24", article_date_iso="2023-08-24",
                           source_id="PRIVATE_SOURCE", paragraph_id="PRIVATE_PARAGRAPH",
                           source_hit_ordinal=i, weak_evidence=weak,
                           match_scope=scope, group_hits=3, **kwargs)


def test_arc_a8_batch_is_bounded_diverse_and_does_not_change_evidence():
    import json
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    from copy import deepcopy
    groups = [{"美國"}, {"政策"}, {"出口管制"}]
    rows = [_a8_row(0, "美國政策一", True, "meta"),
            _a8_row(0, "美國政策二"),
            _a8_row(1, "美國出口管制"),
            _a8_row(2, "無明確關係", True, "meta"),
            _a8_row(3, "x" * 1501),
            _a8_row(4, "美國其他內容", match_policy="relaxed")]
    rows.extend(_a8_row(i, f"美國政策{i}") for i in range(5, 80))
    before = deepcopy(rows)
    batch = build_semantic_review_batch("主題：美國", groups, rows)
    assert rows == before
    assert batch.count == 8 and batch.prefix_count == 64 and batch.prefix_limited
    assert batch.skipped_rows == 2
    payload = json.loads(batch.payload)
    assert payload["query"] == "主題：美國"
    assert [p["ordinal"] for p in payload["passages"]] == list(range(1, 9))
    assert [p["text"] for p in payload["passages"]][:3] == [
        "美國政策一", "美國出口管制", "無明確關係"]
    assert all(set(p) == {"ordinal", "text"} for p in payload["passages"])
    assert "美國政策二" not in batch.payload
    assert "PRIVATE_" not in batch.payload and "2023-08-24" not in batch.payload
    assert "美國" not in repr(batch)
    assert batch.direct_anchor[:3] == (True, True, False)
    assert batch.strong[:3] == (False, True, False)


def test_arc_a8_response_must_cover_every_ordinal_and_cannot_authorize_deletion():
    import json
    from agent.es.evidence_core.arc_semantic_review import (
        build_semantic_review_batch, summarize_semantic_review,
    )
    batch = build_semantic_review_batch(
        "主題：美國", [{"美國"}, {"政策"}, {"出口管制"}],
        [_a8_row(0, "美國政策"), _a8_row(1, "其他內容", True, "meta")])
    result = summarize_semantic_review(
        '[{"ordinal":2,"verdict":"unrelated"},{"ordinal":1,"verdict":"uncertain"}]', batch)
    assert result["counts"] == {"relevant": 0, "uncertain": 1, "unrelated": 1}
    assert result["unrelated_with_direct_anchor"] == 1
    assert result["unrelated_with_strong_evidence"] == 1
    assert not any(k in result for k in ("rows", "ordinals", "deleted", "selected"))
    assert "美國" not in json.dumps(result, ensure_ascii=False)
    invalid = [
        '[]',
        '[{"ordinal":1,"verdict":"relevant"}]',
        '[{"ordinal":1,"verdict":"relevant"},{"ordinal":1,"verdict":"unrelated"}]',
        '[{"ordinal":true,"verdict":"relevant"},{"ordinal":2,"verdict":"uncertain"}]',
        '[{"ordinal":1,"verdict":"relevant","verdict":"uncertain"},{"ordinal":2,"verdict":"unrelated"}]',
        '[{"ordinal":1,"verdict":"delete"},{"ordinal":2,"verdict":"uncertain"}]',
        '[{"ordinal":1,"verdict":"relevant","text":"PRIVATE"},{"ordinal":2,"verdict":"uncertain"}]',
        '[{"ordinal":3,"verdict":"relevant"},{"ordinal":2,"verdict":"uncertain"}]',
        "x" * 4097,
    ]
    assert all(summarize_semantic_review(raw, batch) is None for raw in invalid)


def test_arc_a8_unsupported_or_oversized_input_abstains_without_truncation():
    import json
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    groups = [{"美國"}]
    assert build_semantic_review_batch(None, groups, [_a8_row(1, "美國")]) is None
    assert build_semantic_review_batch("主題：美國", groups, [_a8_row(-1, "美國")]) is None
    assert build_semantic_review_batch("主題：美國", groups, [_a8_row(1, "美" * 1501)]) is None
    batch = build_semantic_review_batch("主題：美國", groups,
                                      [_a8_row(i, "美" * 1500) for i in range(20)])
    assert batch.count == 8
    assert sum(len(r["text"]) for r in json.loads(batch.payload)["passages"]) == 12000
    assert len(batch.payload.encode("utf-8")) <= 64000


def test_arc_a8_transport_requires_explicit_egress_and_budget(monkeypatch, caplog):
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.external_capabilities import requirement_acceptance_scope
    batch = build_semantic_review_batch("主題：美國", [{"美國"}], [_a8_row(0, "美國政策")])
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://review.invalid:11434/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "private-model")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.delenv("SRAF_ARC_REVIEW_EGRESS", raising=False)
    calls = []
    monkeypatch.setattr(transport, "_request_review", lambda *a: calls.append(a))
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        transport.observe_semantic_review(batch, index="news_test", authorize=lambda _: True)
        monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
        transport.observe_semantic_review(batch, index="news_*", authorize=lambda _: True)
        transport.observe_semantic_review(batch, index="other", authorize=lambda _: True)
        with requirement_acceptance_scope():
            transport.observe_semantic_review(batch, index="news_test", authorize=lambda _: True)
    transport.observe_semantic_review(batch, index="news_test", authorize=lambda _: True)
    assert not calls and budget.snapshot()[0] == ArcUnits()
    assert "private-model" not in caplog.text and "review.invalid" not in caplog.text
    assert "美國" not in caplog.text


def test_arc_a8_transport_exact_endpoint_and_bounded_response(monkeypatch, caplog):
    import json
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    batch = build_semantic_review_batch("主題：美國", [{"美國"}], [_a8_row(0, "美國政策")])
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "private-model")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE", raising=False)
    for endpoint in ("http://review.invalid/api/chat", "https://u:p@review.invalid/api/chat",
                     "https://review.invalid/api/chat?x=1", "https://review.invalid/api/generate",
                     "https://review.invalid/api/chat#fragment", "https://review.invalid:0/api/chat"):
        monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", endpoint)
        assert transport._approved_endpoint("news_test") is None
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://review.invalid:11434/api/chat")
    calls = []
    good = json.dumps({"done": True, "message": {"role": "assistant",
                       "content": '[{"ordinal":1,"verdict":"unrelated"}]'}}).encode()
    cases = [
        (200, {}, [good], "observed_verdicts"),
        (302, {}, [good], "invalid_or_incomplete_response"),
        (200, {"Content-Encoding": "gzip"}, [good], "invalid_or_incomplete_response"),
        (200, {}, [b"x" * (transport.MAX_RESPONSE_BYTES + 1)], "invalid_or_incomplete_response"),
        (200, {}, [b'{"done":false}'], "invalid_or_incomplete_response"),
        (200, {}, [b'{"done":true,"done":true}'], "invalid_or_incomplete_response"),
    ]
    for status, headers, chunks, expected in cases:
        caplog.clear()
        class Response:
            status_code = status
            def __init__(self):
                self.headers = headers
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def iter_content(self, chunk_size):
                assert chunk_size == 4096
                yield from chunks
        class Session:
            trust_env = True
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, url, **kw):
                assert self.trust_env is False
                assert url == "https://review.invalid:11434/api/chat"
                assert kw["allow_redirects"] is False and kw["verify"] is True
                assert kw["stream"] is True and kw["timeout"] == (3, 15)
                assert kw["headers"] == {"Accept-Encoding": "identity"}
                assert kw["json"]["model"] == "private-model"
                assert kw["json"]["messages"][1]["content"] == batch.payload
                calls.append(1)
                return Response()
        monkeypatch.setattr(transport.requests, "Session", Session)
        budget = ArcRequestBudget()
        with bind_arc_budget((budget, 1)):
            transport.observe_semantic_review(batch, index="news_test", authorize=lambda _: True)
            transport.observe_semantic_review(batch, index="news_test", authorize=lambda _: True)
        records = [json.loads(r.getMessage().split("SRAF_ARC_SEMANTIC_REVIEW=", 1)[1])
                   for r in caplog.records if r.getMessage().startswith("SRAF_ARC_SEMANTIC_REVIEW=")]
        assert [r["status"] for r in records] == [expected, "shared_budget_exhausted"]
        assert budget.snapshot()[0] == ArcUnits(llm_calls=1)
        assert "美國" not in caplog.text and "review.invalid" not in caplog.text
        if expected == "observed_verdicts":
            assert records[0]["unrelated_with_direct_anchor"] == 1
    assert len(calls) == len(cases)


def test_arc_a8_real_session_rejects_redirect_before_body_read(monkeypatch):
    # Keep actual Session.send and redirect logic. Only replace its network
    # adapter; no live network or private prompt is sent by this regression.
    import requests
    from requests.adapters import BaseAdapter
    from requests.structures import CaseInsensitiveDict
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    batch = build_semantic_review_batch("主題：美國", [{"美國"}], [_a8_row(0, "美國政策")])
    approved = transport._ApprovedEndpoint(
        "https://review.invalid/api/chat", "test-model", "news_test", True)
    session_type = requests.Session
    reads = []
    sends = []
    closes = []
    class Raw:
        def stream(self, *args, **kwargs):
            reads.append(1)
            yield b"x" * (transport.MAX_RESPONSE_BYTES + 1)
        def read(self, *args, **kwargs):
            reads.append(1)
            return b"x" * (transport.MAX_RESPONSE_BYTES + 1)
        def close(self):
            closes.append(1)
        def release_conn(self):
            pass
    class Adapter(BaseAdapter):
        def send(self, request, **kwargs):
            sends.append(request.url)
            response = requests.Response()
            response.status_code = 302
            response.headers = CaseInsensitiveDict({
                "Location": "https://other.invalid/private",
                "Content-Encoding": "gzip"})
            response.url = request.url
            response.request = request
            response.raw = Raw()
            return response
        def close(self):
            pass
    def session():
        result = session_type()
        result.mount("https://", Adapter())
        return result
    monkeypatch.setattr(transport.requests, "Session", session)
    assert transport._request_review(approved, batch) is None
    assert sends == [approved.url]
    assert not reads
    assert closes


def test_arc_review_transport_requires_explicit_authorization_callback(monkeypatch, caplog):
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es.evidence_core.arc_semantic_review import SemanticReviewBatch
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://review.invalid/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "private-model")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE", raising=False)
    batch = SemanticReviewBatch("{}",1,1,False,0,(True,),(True,))
    calls = []
    monkeypatch.setattr(transport, "_request_review", lambda *a: calls.append(a))
    budget = ArcRequestBudget()
    with bind_arc_budget((budget,1)):
        transport.observe_semantic_review(batch,index="news_test")
        transport.observe_semantic_review(batch,index="news_test",authorize=lambda _: "true")
    assert not calls
    assert budget.snapshot()[0] == ArcUnits()
    assert caplog.text.count("source_or_endpoint_not_authorized") == 2


@pytest.mark.parametrize("case", ["success","missing_counts","bad_counts","bad_verdict","timeout","rejected","revoked","denied","off"])
def test_arc_a8_measured_transport_counts_actual_attempt_and_provider_tokens(monkeypatch,caplog,case):
    import json
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    monkeypatch.setenv("SRAF_ARC_REVIEW","shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS","approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT","https://review.invalid/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL","PRIVATE_MODEL")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX","news_test")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE",raising=False)
    monkeypatch.setenv("SRAF_ARC_REVIEW_RESOURCE_METRICS","off" if case=="off" else "shadow")
    batch = build_semantic_review_batch("主題：美國",[{"美國"}],[_a8_row(0,"美國私人資料")])
    envelope = {"done":True,"message":{"role":"assistant","content":'[{"ordinal":1,"verdict":"relevant"}]'},
                "prompt_eval_count":123,"eval_count":17}
    if case=="missing_counts":
        del envelope["prompt_eval_count"]
        del envelope["eval_count"]
    elif case=="bad_counts":
        envelope.update(prompt_eval_count=True,eval_count=-1)
    elif case=="bad_verdict":
        envelope["message"]["content"]="PRIVATE_INVALID"
    calls = []
    class Response:
        status_code = 302 if case=="rejected" else 200
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def iter_content(self,chunk_size):
            yield json.dumps(envelope).encode()
    class Session:
        trust_env = True
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def post(self,*args,**kwargs):
            calls.append(1)
            if case=="timeout":
                raise transport.requests.Timeout("PRIVATE_TIMEOUT")
            return Response()
    monkeypatch.setattr(transport.requests,"Session",Session)
    checks = []
    def authorize(_):
        checks.append(1)
        return case!="denied" and (case!="revoked" or len(checks)==1)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget,1)):
        transport.observe_semantic_review(batch,index="news_test",authorize=authorize)
        transport.observe_semantic_review(batch,index="news_test",authorize=authorize)
    rows = [json.loads(r.getMessage().split("SRAF_ARC_REVIEW_RESOURCE=",1)[1])
            for r in caplog.records if r.getMessage().startswith("SRAF_ARC_REVIEW_RESOURCE=")]
    assert len(calls)==int(case!="denied")
    assert budget.snapshot()[0] == ArcUnits(llm_calls=int(case!="denied"))
    if case in ("revoked","denied","off"):
        assert not rows
    else:
        assert len(rows)==1
        m=rows[0]["measurement"]
        assert m["llm_calls"]==1 and m["es_calls"]==0 and m["elapsed_ms"]>=0
        assert m["status"]==("timed_out" if case=="timeout" else "failed" if case in ("rejected","bad_verdict") else "completed")
        if case in ("success","bad_verdict"):
            assert (m["prompt_tokens"],m["completion_tokens"])==(123,17)
        else:
            assert m["prompt_tokens"] is None and m["completion_tokens"] is None
    assert "PRIVATE_" not in caplog.text and "美國" not in caplog.text and "review.invalid" not in caplog.text


@pytest.mark.parametrize("timeout", [True, False])
def test_arc_a8_measured_real_iter_content_timeout_vs_connection_failure(monkeypatch, timeout):
    import requests
    from urllib3.exceptions import ReadTimeoutError, ProtocolError
    from agent.es import arc_semantic_review_transport as transport
    from agent.es.evidence_core.arc_semantic_review import build_semantic_review_batch
    batch = build_semantic_review_batch("主題：美國", [{"美國"}], [_a8_row(0, "美國政策")])
    approved = transport._ApprovedEndpoint(
        "https://review.invalid/api/chat", "test-model", "news_test", True)
    class Raw:
        def stream(self, *args, **kwargs):
            yield b'{"done":'
            if timeout:
                raise ReadTimeoutError(None, "PRIVATE_URL", "PRIVATE_TIMEOUT")
            raise ProtocolError("PRIVATE_CONNECTION")
        def close(self):
            pass
        def release_conn(self):
            pass
    class Session:
        trust_env = True
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, *args, **kwargs):
            response = requests.Response()
            response.status_code = 200
            response.raw = Raw()
            return response
    monkeypatch.setattr(transport.requests, "Session", Session)
    summary, metrics = transport._measured_review(approved, batch)
    assert summary is None
    assert metrics["status"] == ("timed_out" if timeout else "failed")
    assert metrics["llm_calls"] == 1
    assert metrics["elapsed_ms"] >= 0
    assert metrics["prompt_tokens"] is None and metrics["completion_tokens"] is None
    assert "PRIVATE" not in repr(metrics)


def _a9_label(i, source, gold, predicted, anchor=False, strong=False):
    return {"ordinal": i, "source": source, "gold": gold, "predicted": predicted,
            "direct_anchor": anchor, "strong": strong}


def test_arc_a9_semantic_eval_exposes_precision_recall_tradeoff():
    from agent.es.evidence_core.arc_semantic_eval import evaluate_semantic_cases
    cases = [[_a9_label(1, 0, "relevant", "unrelated", True, True),
              _a9_label(2, 1, "relevant", "uncertain", True, True),
              _a9_label(3, 2, "unrelated", "unrelated"),
              _a9_label(4, 2, "uncertain", "unrelated")],
             [_a9_label(1, 0, "relevant", "relevant"),
              _a9_label(2, 0, "unrelated", "uncertain")]]
    result = evaluate_semantic_cases(cases)
    assert result["rows"] == 6 and result["cases"] == 2
    assert result["baseline"]["known_label_precision"]["value"] == 3/5
    cf = result["counterfactual"]
    assert cf["retained"] == 3 and cf["removed"] == 3
    assert cf["known_label_precision"]["value"] == 2/3
    assert cf["relevant_retention"]["value"] == 2/3
    assert cf["false_removal_rate"]["value"] == 1/3
    assert cf["unrelated_removal_rate"]["value"] == 1/2
    assert cf["uncertain_gold_removed"] == 1
    assert cf["anchor_relevant_false_removal"]["value"] == 1/2
    assert cf["strong_relevant_false_removal"]["value"] == 1/2
    assert cf["source_retention"]["value"] == 2/4
    assert cf["relevant_source_loss"]["value"] == 1/3
    assert cf["cases_with_relevant_source_loss"] == 1
    assert result["model_uncertain"] == 2


def test_arc_a9_retained_unrelated_from_source_does_not_prove_relevant_source_coverage():
    from agent.es.evidence_core.arc_semantic_eval import evaluate_semantic_cases
    r = evaluate_semantic_cases([[_a9_label(1, 0, "relevant", "unrelated"),
                                  _a9_label(2, 0, "unrelated", "relevant")]])
    assert r["counterfactual"]["source_retention"]["value"] == 1
    assert r["counterfactual"]["relevant_source_loss"]["value"] == 1


def test_arc_a9_zero_denominator_and_strict_labels():
    from agent.es.evidence_core.arc_semantic_eval import evaluate_semantic_cases
    row = _a9_label(1, 0, "uncertain", "uncertain")
    result = evaluate_semantic_cases([[row]])
    assert result["baseline"]["known_label_precision"] == {
        "numerator":0, "denominator":0, "value":None}
    assert result["counterfactual"]["false_removal_rate"]["value"] is None
    assert result["counterfactual"]["uncertain_gold_removed"] == 0
    for invalid in ([], [[]], [[row, row]], [[{**row, "ordinal": True}]],
                    [[{**row, "source": False}]], [[{**row, "gold": "unknown"}]],
                    [[{**row, "predicted": None}]], [[{**row, "private_text":"secret"}]],
                    [[{**row, "strong": 1}]], [[row]] * 33):
        assert evaluate_semantic_cases(invalid) is None


def _selection_row(i, source, gold, baseline, candidate, *, anchor=False, strong=False):
    return {"ordinal": i, "source": source, "gold": gold,
            "direct_anchor": anchor, "strong": strong,
            "baseline_rank": baseline, "candidate_rank": candidate}


def test_arc_selection_eval_distinguishes_relevant_gain_and_loss():
    from agent.es.evidence_core.arc_selection_eval import evaluate_selection_cases
    rows = [_selection_row(1, 1, "relevant", 1, None, anchor=True, strong=True),
            _selection_row(2, 1, "unrelated", 2, 2),
            _selection_row(3, 2, "relevant", None, 1),
            _selection_row(4, 3, "uncertain", 3, None),
            _selection_row(5, 4, "relevant", None, None)]
    result = evaluate_selection_cases([rows])
    full = result["full_selection"]
    assert full["baseline"]["known_label_precision"]["value"] == 1/2
    assert full["candidate"]["known_label_precision"]["value"] == 1/2
    assert full["candidate"]["labeled_universe_relevant_coverage"]["value"] == 1/3
    assert full["net_relevant_change"] == 0
    assert full["removed"] == {"relevant":1, "uncertain":1, "unrelated":0}
    assert full["added"] == {"relevant":1, "uncertain":0, "unrelated":0}
    assert full["baseline_relevant_loss"]["value"] == 1
    assert full["baseline_relevant_anchor_loss"]["value"] == 1
    assert full["baseline_relevant_strong_loss"]["value"] == 1
    assert full["baseline_relevant_source_loss"]["value"] == 1
    assert full["gained_relevant_sources"] == 1
    assert full["cases_with_relevant_source_loss"] == 1
    assert result["top_20"] == full


def test_arc_selection_eval_top20_separates_reordering_from_full_selection():
    from agent.es.evidence_core.arc_selection_eval import evaluate_selection_cases
    rows = [_selection_row(i, i, "unrelated", i, i) for i in range(1, 20)]
    rows += [_selection_row(20, 20, "unrelated", 20, 21),
             _selection_row(21, 21, "relevant", 21, 20)]
    result = evaluate_selection_cases([rows])
    assert result["full_selection"]["net_relevant_change"] == 0
    assert result["full_selection"]["added"]["relevant"] == 0
    assert result["top_20"]["net_relevant_change"] == 1
    assert result["top_20"]["candidate"]["known_label_precision"]["value"] == 1/20
    assert result["top_20"]["baseline"]["known_label_precision"]["value"] == 0
    assert result["top_20"]["baseline_relevant_loss"]["value"] is None


def test_arc_selection_eval_source_loss_is_per_case_and_requires_relevance():
    from agent.es.evidence_core.arc_selection_eval import evaluate_selection_cases
    first = [_selection_row(1, 1, "relevant", 1, None),
             _selection_row(2, 1, "unrelated", 2, 1)]
    second = [_selection_row(1, 1, "relevant", 1, 1),
              _selection_row(2, 1, "relevant", 2, None)]
    full = evaluate_selection_cases([first, second])["full_selection"]
    assert full["baseline"]["sources"] == full["candidate"]["sources"] == 2
    assert full["baseline_relevant_source_loss"]["value"] == 1/2
    assert full["cases_with_relevant_loss"] == 2
    assert full["cases_with_relevant_source_loss"] == 1


def test_arc_selection_eval_rejects_noncontiguous_and_malformed_ranks():
    from agent.es.evidence_core.arc_selection_eval import evaluate_selection_cases
    row = _selection_row(1, 0, "uncertain", None, None)
    assert evaluate_selection_cases([[row]])["full_selection"]["baseline"]["known_label_precision"]["value"] is None
    for invalid in ([], [[]], [[row,row]], [[{**row, "ordinal":True}]],
                    [[{**row, "source":False}]], [[{**row,"candidate_rank":True}]],
                    [[{**row,"baseline_rank":2}]], [[{**row,"gold":"unknown"}]],
                    [[{**row,"strong":1}]], [[{**row,"text":"PRIVATE"}]],
                    [[{**row,"candidate_rank":1}, {**row,"ordinal":2,"candidate_rank":1}]],
                    [[row]]*33):
        assert evaluate_selection_cases(invalid) is None


def test_arc_eval_cli_reads_private_file_and_outputs_only_aggregate(tmp_path, capsys):
    import json
    from agent.es.evidence_core.arc_eval_cli import main
    private = tmp_path / "PRIVATE_PATH.json"
    for mode, rows in [
        ("semantic", [[_a9_label(1, 0, "relevant", "uncertain")]]),
        ("selection", [[_selection_row(1, 0, "relevant", 1, 1)]])]:
        private.write_text(json.dumps(rows), encoding="utf-8-sig")
        assert main([mode, str(private)]) == 0
        result = capsys.readouterr()
        assert result.err == ""
        obj = json.loads(result.out)
        assert obj["status"] == "EVALUATED_OFFLINE"
        assert obj["result"]["rows"] == 1
        assert "PRIVATE_PATH" not in result.out
        assert "ordinal" not in result.out


def test_arc_eval_cli_fails_closed_on_invalid_or_oversized_input(tmp_path, capsys, monkeypatch):
    import json
    from agent.es.evidence_core import arc_eval_cli as cli
    p = tmp_path / "PRIVATE_PATH.json"
    for raw in (b"", b"PRIVATE_TEXT", b'[[{"ordinal":1,"ordinal":2}]]', b"\xff",
                b"[]", b"[" * 10000):
        p.write_bytes(raw)
        assert cli.main(["selection", str(p)]) == 2
        out = capsys.readouterr()
        assert not out.out
        assert json.loads(out.err) == {"status":"INVALID_OR_UNREADABLE_FIXTURE"}
        assert "PRIVATE" not in out.err
    monkeypatch.setattr(cli, "MAX_INPUT_BYTES", 8)
    p.write_bytes(b" " * 9)
    assert cli.main(["selection", str(p)]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "INVALID_OR_UNREADABLE_FIXTURE"
    for path in (str(tmp_path), str(tmp_path / "PRIVATE_MISSING.json"), "https://private.invalid"):
        assert cli.main(["semantic", path]) == 2
        assert json.loads(capsys.readouterr().err)["status"] == "INVALID_OR_UNREADABLE_FIXTURE"
    assert cli.main(["PRIVATE_MODE", str(p)]) == 2
    assert "PRIVATE_MODE" not in capsys.readouterr().err


def _a9_tighten_replay_case():
    from agent.es.arc_frequency_plan import SCOPE
    groups = [["美國"],["政策"],["出口管制"],["半導體"]]
    rows = [{"text":"美國 政策 出口管制 半導體","source":i,
             "group_hits":4,"weak":False,"gold":"relevant"} for i in range(20)]
    rows += [{"text":"美國 政策 出口管制","source":i,
              "group_hits":3,"weak":False,"gold":"unrelated"} for i in range(20,40)]
    rows += [{"text":"政策 出口管制 半導體","source":i,
              "group_hits":3,"weak":False,"gold":"relevant"} for i in range(40,50)]
    return {"groups":groups,"question":"主題：美國","pressure":{"relation":"eq","total":1000,"returned":50},
            "local_frequency":None,"native_frequency":{
                "schema":"sraf_arc_native_rank_frequency_v1","scope":SCOPE,
                "status":"exact_es_query_counts","eligible_documents":1000,
                "groups":[{"group_ordinal":i,"document_frequency":df}
                          for i,df in enumerate((800,700,500,50),1)]},"rows":rows}


def test_a9_tightening_replay_matches_shadow_and_measures_source_loss():
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    from agent.es.evidence_core.arc_tighten_shadow import observe_tightening, CandidatePressure
    from agent.es.evidence_core.models import EvidenceSnippet
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    case = _a9_tighten_replay_case()
    result = replay_tightening_cases([case])
    rows = case["rows"]
    evidence = [EvidenceSnippet(uuid="",text=r["text"],date_iso="",article_date_iso="",
                source_hit_ordinal=r["source"],group_hits=r["group_hits"],weak_evidence=r["weak"])
                for r in rows]
    with bind_arc_budget((ArcRequestBudget(),1)):
        actual = observe_tightening(evidence,[set(g) for g in case["groups"]],
                    original_question=case["question"],pressure=CandidatePressure(**case["pressure"]),
                    native_frequency=case["native_frequency"])
    assert set(result["strategies"]) == {s["strategy"] for s in actual["strategies"]}
    for s in actual["strategies"]:
        replay = result["strategies"][s["strategy"]]
        assert replay["applicable_cases"] == replay["sample_floor_met_cases"] == 1
        comp = replay["comparison"]["full_selection"]
        assert comp["candidate"]["selected"] == s["retained_prefix_rows"] == 20
        assert comp["candidate"]["sources"] == s["retained_source_hits"] == 20
        assert comp["candidate"]["known_label_precision"]["value"] == 1
        assert comp["baseline_relevant_loss"]["value"] == 1/3
        assert comp["baseline_relevant_source_loss"]["value"] == 1/3
        assert comp["baseline_relevant_anchor_loss"]["value"] == 0
        assert comp["removed"]["unrelated"] == 20
    assert "美國" not in repr(result)


def test_a9_tightening_replay_separates_applicable_cases_and_floor_failures():
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    first, second = _a9_tighten_replay_case(), _a9_tighten_replay_case()
    second["native_frequency"] = None
    for row in second["rows"][:20]:
        row["weak"] = True
    result = replay_tightening_cases([first, second])
    assert result["cases"] == 2
    strategies = result["strategies"]
    assert strategies["all_text_axes"]["applicable_cases"] == 2
    assert strategies["all_text_axes"]["sample_floor_met_cases"] == 1
    assert strategies["anchor_plus_native_discriminative_axis"]["applicable_cases"] == 1
    assert strategies["anchor_plus_native_discriminative_axis"]["sample_floor_met_cases"] == 1


def test_a9_tightening_replay_rejects_unconfirmed_pressure_and_invalid_rows():
    from agent.es.evidence_core.arc_tighten_replay import replay_tightening_cases
    for key, value in [("total",255),("total",True),("returned",0),("relation","unknown")]:
        case = _a9_tighten_replay_case()
        case["pressure"][key] = value
        assert replay_tightening_cases([case]) is None
    for key, value in [("source",50),("group_hits",2),("weak",1),("gold","unknown"),("text","x"*4097)]:
        case = _a9_tighten_replay_case()
        case["rows"][0][key] = value
        assert replay_tightening_cases([case]) is None
    case = _a9_tighten_replay_case()
    case["question"] = "不明確的問題"
    assert replay_tightening_cases([case]) is None
    case = _a9_tighten_replay_case()
    case["rows"] = case["rows"][:39]
    assert replay_tightening_cases([case]) is None


def test_a9_tightening_replay_cli_privacy(tmp_path, capsys):
    import json
    from agent.es.evidence_core.arc_eval_cli import main
    p = tmp_path / "PRIVATE_TIGHTEN.json"
    p.write_text(json.dumps([_a9_tighten_replay_case()],ensure_ascii=False),encoding="utf-8")
    assert main(["tighten-replay",str(p)]) == 0
    out = capsys.readouterr()
    result = json.loads(out.out)["result"]
    assert result["strategies"]["all_text_axes"]["comparison"]["full_selection"]["baseline_relevant_loss"]["value"] == 1/3
    assert "PRIVATE" not in out.out and "美國" not in out.out and not out.err
    p.write_text("[]",encoding="utf-8")
    assert main(["tighten-replay",str(p)]) == 2
    out = capsys.readouterr()
    assert not out.out and json.loads(out.err)["status"] == "INVALID_OR_UNREADABLE_FIXTURE"


def _a9_relax_case():
    hits = [_hit([_citation(t) for t in ["甲軸乙軸丙軸完整事件", "甲軸乙軸相關補充",
                  "甲軸丙軸無關補充", "甲軸乙軸另一相關補充",
                  "乙軸丙軸缺必要主體"]] + [
                  _citation("甲軸乙軸異日資料", "E2")], docid="PRIVATE_DOC")]
    # _hit accepts either all strings or all dictionaries.
    return {"question":"主題：甲軸", "query":"甲軸乙軸丙軸",
            "groups":[["甲軸"],["乙軸"],["丙軸"]],
            "date_from":"2023-08-24","date_to":"2023-08-24",
            "response":{"timed_out":False,
                        "_shards":{"total":1,"successful":1,"failed":0},
                        "hits":{"total":{"relation":"eq","value":1},"hits":hits}}}


def _a9_relax_labeled(case):
    from agent.es.evidence_core.arc_relax_replay import prepare_relax_annotation
    prepared = prepare_relax_annotation(case)
    assert prepared is not None
    return {"case":case,"fixture_digest":prepared["fixture_digest"],
            "labels":[{"ordinal":r["ordinal"],
                       "gold":"unrelated" if "無關" in r["text"] else "relevant"}
                      for r in prepared["rows"]]}


def test_a9_relax_replay_exact_a6_bounded_additions_and_date_guard():
    from agent.es.evidence_core.arc_relax_replay import prepare_relax_annotation, replay_relax_cases
    from agent.es.evidence_core.arc_relax_shadow import observe_low_volume, StrictSliceCounts
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.evidence_core.builder import collect_snippets
    from agent.es.evidence_core.parser import parse_es_hits
    from agent.es.evidence_core.models import EvidenceBuildConfig
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    case = _a9_relax_case()
    template = prepare_relax_annotation(case)
    assert template is not None
    assert len(template["rows"]) == 5
    assert all(r["gold"] is None for r in template["rows"])
    assert all("異日" not in r["text"] for r in template["rows"])
    assert "PRIVATE_DOC" not in repr(template)
    fixture = _a9_relax_labeled(case)
    result = replay_relax_cases([fixture])
    full = result["comparison"]["full_selection"]
    assert result["hypothetical_added"] == 2
    assert full["baseline"]["selected"] == 1
    assert full["candidate"]["selected"] == 3
    assert full["added"]["relevant"] == full["added"]["unrelated"] == 1
    assert full["removed"]["relevant"] == 0
    assert full["candidate"]["known_label_precision"]["value"] == 2/3
    assert "甲軸" not in repr(result) and "PRIVATE_DOC" not in repr(result)
    hits, _ = parse_es_hits(case["response"]["hits"]["hits"],
                             query_for_snippet=case["query"],config=EvidenceBuildConfig())
    counts = StrictSliceCounts()
    strict = collect_snippets(hits,date_from=case["date_from"],date_to=case["date_to"],
                              term_groups=AXES,min_groups_required=None,arc_counts=counts)
    with bind_arc_budget((ArcRequestBudget(),1)):
        obs = observe_low_volume(hits,strict,AXES,counts=counts,
              pressure=CandidatePressure.from_primary(case["response"]),
              original_question=case["question"],date_from=case["date_from"],
              date_to=case["date_to"],allowed_years=None)
    assert obs["hypothetical_add_cap"] == result["hypothetical_added"]
    assert obs["new_candidate_rows"] == 3
    assert obs["date_rejected"] == 1


def test_a9_relax_replay_rejects_changed_fixture_and_missing_labels():
    from copy import deepcopy
    from agent.es.evidence_core.arc_relax_replay import replay_relax_cases
    fixture = _a9_relax_labeled(_a9_relax_case())
    for change in ("text","query","date","digest","missing","duplicate","unknown"):
        other = deepcopy(fixture)
        if change == "text":
            other["case"]["response"]["hits"]["hits"][0]["_source"]["multidim_event_json"][0]["evidence_snippets"][1]["text"] += "改"
        elif change == "query":
            other["case"]["query"] += "改"
        elif change == "date":
            other["case"]["date_to"] = "2023-08-25"
        elif change == "digest":
            other["fixture_digest"] = "0"*64
        elif change == "missing":
            other["labels"].pop()
        elif change == "duplicate":
            other["labels"][1]["ordinal"] = other["labels"][0]["ordinal"]
        else:
            other["labels"][0]["gold"] = None
        assert replay_relax_cases([other]) is None


def test_a9_relax_annotation_rejects_incomplete_and_ambiguous_inputs():
    from agent.es.evidence_core.arc_relax_replay import prepare_relax_annotation
    for change in ("timeout","duplicate","anchor","too_many","too_long"):
        case = _a9_relax_case()
        if change == "timeout":
            case["response"]["timed_out"] = True
        elif change == "anchor":
            case["question"] = "不明確"
        else:
            rows = case["response"]["hits"]["hits"][0]["_source"]["multidim_event_json"][0]["evidence_snippets"]
            if change == "duplicate":
                rows.append(dict(rows[1]))
            elif change == "too_many":
                rows.extend(_citation("甲軸乙軸補充"+str(i)) for i in range(4))
            else:
                rows[1]["text"] = "甲軸乙軸" + "x"*4097
        assert prepare_relax_annotation(case) is None


def test_a9_relax_replay_cli_aggregate_only(tmp_path, capsys):
    import json
    from agent.es.evidence_core.arc_eval_cli import main
    p = tmp_path / "PRIVATE_RELAX.json"
    p.write_text(json.dumps([_a9_relax_labeled(_a9_relax_case())],ensure_ascii=False),
                 encoding="utf-8")
    assert main(["relax-replay",str(p)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["result"]["hypothetical_added"] == 2
    assert "PRIVATE" not in out.out and "甲軸" not in out.out and not out.err


def test_a9_relax_annotation_cli_direct_roundtrip_and_exclusive_output(tmp_path, capsys):
    import json
    import os
    from agent.es.evidence_core.arc_relax_annotation_cli import main as prepare
    from agent.es.evidence_core.arc_eval_cli import main as evaluate
    source = tmp_path / "PRIVATE_CASE.json"
    target = tmp_path / "PRIVATE_LABEL.json"
    source.write_text(json.dumps([_a9_relax_case()],ensure_ascii=False),encoding="utf-8")
    assert prepare([str(source),str(target)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == {"status":"PRIVATE_ANNOTATION_CREATED","cases":1,"rows_to_label":5}
    assert not out.err and "PRIVATE_CASE.json" not in out.out and "PRIVATE_LABEL.json" not in out.out and "甲軸" not in out.out
    if os.name == "posix":
        assert target.stat().st_mode & 0o077 == 0
    initial = target.read_bytes()
    assert prepare([str(source),str(target)]) == 2
    assert target.read_bytes() == initial
    assert json.loads(capsys.readouterr().err)["status"] == "OUTPUT_NOT_CREATED"
    assert evaluate(["relax-replay",str(target)]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "INVALID_OR_UNREADABLE_FIXTURE"
    fixtures = json.loads(initial.decode("utf-8"))
    for row in fixtures[0]["labels"]:
        assert row["gold"] is None
        row["gold"] = "unrelated" if "無關" in row["text"] else "relevant"
    target.write_text(json.dumps(fixtures,ensure_ascii=False),encoding="utf-8")
    assert evaluate(["relax-replay",str(target)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["hypothetical_added"] == 2
    for key, value in (("text","PRIVATE_FORGED"),("source",True),("source",100)):
        from copy import deepcopy
        changed = deepcopy(fixtures)
        changed[0]["labels"][0][key] = value
        target.write_text(json.dumps(changed,ensure_ascii=False),encoding="utf-8")
        assert evaluate(["relax-replay",str(target)]) == 2
        out = capsys.readouterr()
        assert not out.out and "PRIVATE_FORGED" not in out.err


def test_a9_relax_annotation_cli_invalid_input_creates_nothing(tmp_path,capsys,monkeypatch):
    import json
    from agent.es.evidence_core import arc_relax_annotation_cli as cli
    p = tmp_path / "PRIVATE_CASE.json"
    q = tmp_path / "PRIVATE_LABEL.json"
    for raw in (b"[]",b'{"x":1,"x":2}',b"PRIVATE",b"\xff"):
        p.write_bytes(raw)
        assert cli.main([str(p),str(q)]) == 2
        assert not q.exists()
        assert json.loads(capsys.readouterr().err)["status"] == "INVALID_OR_UNREADABLE_FIXTURE"
    p.write_text(json.dumps([_a9_relax_case()],ensure_ascii=False),encoding="utf-8")
    monkeypatch.setattr(cli,"MAX_FILE_BYTES",p.stat().st_size)
    assert cli.main([str(p),str(q)]) == 2
    assert not q.exists()
    assert "PRIVATE" not in capsys.readouterr().err


def _arc_capture_spec():
    case = _a9_relax_case()
    return {**{k: v for k, v in case.items() if k != "response"}, "size": 8}


def test_arc_primary_capture_fixed_scope_and_frozen_annotation_roundtrip(monkeypatch):
    import json
    from agent.es.evidence_core.arc_primary_capture import capture_case
    from agent.es.evidence_core.arc_relax_replay import prepare_relax_annotation
    monkeypatch.setenv("SRAF_STRUCTURED_FIELD_EXPANSION", "off")
    response = _a9_relax_case()["response"]
    response["hits"]["hits"][0]["_index"] = "news_test"
    calls = []
    def request(config, method, path, payload=None, **kw):
        calls.append((method,path,payload))
        if path == "/_security/_authenticate":
            return {"username":"readonly"}
        if path == "/news_test/_mapping":
            return {"news_test":{"mappings":{}}}
        return response
    spec = _arc_capture_spec()
    case, stats = capture_case(spec,request=request,config=(None,None,None,None,"readonly"))
    assert [(a,b) for a,b,_ in calls] == [
        ("GET","/_security/_authenticate"), ("GET","/news_test/_mapping"),
        ("POST","/news_test/_search?allow_partial_search_results=false")]
    body = json.loads(calls[-1][2])
    assert body["size"] == 8 and body["timeout"] == "5s" and body["track_total_hits"] is True
    assert "multidim_event_json.Event.time_iso" in json.dumps(body)
    assert "multidim_event_json.Event_Timeline.time_iso" in json.dumps(body)
    assert "pit" not in body and "search_after" not in body
    assert case["response"] is response and set(case) == set(_a9_relax_case())
    assert stats["returned"] == 1 and stats["es_search_attempts"] == 1
    assert stats["es_preflight_attempts"] == 2 and stats["search_elapsed_ms"] >= 0
    assert prepare_relax_annotation(case) is not None


@pytest.mark.parametrize("problem", ["invalid_spec","wrong_principal","alias","partial","other_index","duplicate","empty"])
def test_arc_primary_capture_refuses_unsupported_scope(monkeypatch, problem):
    from agent.es.evidence_core.arc_primary_capture import capture_case
    monkeypatch.setenv("SRAF_STRUCTURED_FIELD_EXPANSION","off")
    spec = _arc_capture_spec()
    if problem == "invalid_spec":
        spec["size"] = True
    response = _a9_relax_case()["response"]
    response["hits"]["hits"][0]["_index"] = "news_test"
    if problem == "partial":
        response["timed_out"] = True
    elif problem == "other_index":
        response["hits"]["hits"][0]["_index"] = "other"
    elif problem == "duplicate":
        response["hits"]["hits"] *= 2
        response["hits"]["total"]["value"] = 2
    elif problem == "empty":
        response["hits"]["hits"] = []
        response["hits"]["total"]["value"] = 0
    calls = []
    def request(config,method,path,payload=None,**kw):
        calls.append(path)
        if path == "/_security/_authenticate":
            return {"username":"other" if problem == "wrong_principal" else "readonly"}
        if path == "/news_test/_mapping":
            return {"other" if problem == "alias" else "news_test":{"mappings":{}}}
        return response
    with pytest.raises(ValueError):
        capture_case(spec,request=request,config=(None,None,None,None,"readonly"))
    assert len(calls) == (0 if problem == "invalid_spec" else
                          1 if problem == "wrong_principal" else 2 if problem == "alias" else 3)


def test_arc_primary_capture_cli_explicit_opt_in_and_no_overwrite(tmp_path,monkeypatch,capsys):
    import json
    import os
    from agent.es.evidence_core import arc_primary_capture as capture
    p = tmp_path / "PRIVATE_SPEC.json"
    q = tmp_path / "PRIVATE_CASES.json"
    p.write_text(json.dumps(_arc_capture_spec(),ensure_ascii=False),encoding="utf-8")
    calls = []
    def run(spec):
        calls.append(spec)
        return _a9_relax_case(), {"returned":1,"search_elapsed_ms":10,
                                   "es_search_attempts":1,"es_preflight_attempts":2}
    monkeypatch.setattr(capture,"capture_case",run)
    assert capture.main([str(p),str(q)]) == 2
    assert not q.exists() and not calls
    capsys.readouterr()
    assert capture.main(["--run",str(p),str(q)]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["status"] == "PRIVATE_PRIMARY_CAPTURED"
    assert "PRIVATE_SPEC.json" not in out.out and "PRIVATE_CASES.json" not in out.out and "甲軸" not in out.out
    if os.name == "posix":
        assert q.stat().st_mode & 0o077 == 0
    initial = q.read_bytes()
    assert capture.main(["--run",str(p),str(q)]) == 2
    assert q.read_bytes() == initial and len(calls) == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1:9001","https://8.8.8.8:443",
                                  "https://user:password@127.0.0.1:9001",
                                  "https://127.0.0.1:9001/path","https://127.0.0.1"])
def test_arc_primary_capture_denies_unapproved_endpoint(monkeypatch,url):
    from agent.es.evidence_core.arc_primary_capture import _connection_config
    monkeypatch.setenv("SRAF_ARC_CAPTURE_ES_URL",url)
    with pytest.raises(ValueError):
        _connection_config()


def _prepare_a6_pilot_for_test(case):
    from agent.es.evidence_core.arc_relax_shadow import prepare_low_volume_pilot, StrictSliceCounts
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    from agent.es.evidence_core.builder import collect_snippets
    from agent.es.evidence_core.parser import parse_es_hits
    from agent.es.evidence_core.models import EvidenceBuildConfig
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    hits, _ = parse_es_hits(case["response"]["hits"]["hits"],
                             query_for_snippet=case["query"], config=EvidenceBuildConfig())
    groups = [set(g) for g in case["groups"]]
    counts = StrictSliceCounts()
    strict = collect_snippets(hits,date_from=case["date_from"],date_to=case["date_to"],
                              term_groups=groups,min_groups_required=None,arc_counts=counts)
    with bind_arc_budget((ArcRequestBudget(),1)):
        result = prepare_low_volume_pilot(
            hits, strict, groups, counts=counts,
            pressure=CandidatePressure.from_primary(case["response"]),
            original_question=case["question"],date_from=case["date_from"],
            date_to=case["date_to"],allowed_years=None)
    return strict, result


def test_a6_pilot_prepares_weak_linked_candidates_without_mutating_strict():
    from agent.es.evidence_core.arc_relax_shadow import _identity
    case = _a9_relax_case()
    strict, (observation, identities, candidates, status) = _prepare_a6_pilot_for_test(case)
    assert status == "pilot_candidate_prepared"
    assert len(strict) == 1 and strict[0].match_policy == "strict"
    assert strict[0].weak_evidence is False
    assert len(candidates) == observation["hypothetical_add_cap"] == 2
    assert [_identity(e) for e in candidates] == identities
    assert not set(identities).intersection(_identity(e) for e in strict)
    assert all(e.weak_evidence is True and e.group_hits == 2
               and e.match_policy == "adaptive_two_axis" and e.match_scope == "text"
               and e.structured_time_context and e.matched_event_time_candidates
               and e.event_ids == ["E1"] for e in candidates)
    assert candidates[0].synonym_hits == ["乙軸", "甲軸"]
    assert all("異日" not in e.text for e in candidates)
    assert len(_build(case["response"]["hits"]["hits"])[1]) == 1


@pytest.mark.parametrize("relation,total", [("gte",1),("eq",2)])
def test_a6_pilot_declines_unexhausted_primary_but_preserves_counterfactual(relation,total):
    case = _a9_relax_case()
    case["response"]["hits"]["total"] = {"relation":relation,"value":total}
    strict, (obs, identities, candidates, status) = _prepare_a6_pilot_for_test(case)
    assert len(strict)==1 and obs["hypothetical_add_cap"] == len(identities)==2
    assert candidates == () and status=="primary_or_scan_not_exhausted"


def test_a6_pilot_zero_strict_cannot_replace_legacy_fallback():
    case = _a9_relax_case()
    rows = case["response"]["hits"]["hits"][0]["_source"]["multidim_event_json"][0]["evidence_snippets"]
    rows.pop(0)
    strict, (obs, identities, candidates, status) = _prepare_a6_pilot_for_test(case)
    assert not strict and obs["hypothetical_add_cap"]==len(identities)==2
    assert candidates==() and status=="legacy_zero_or_non_low_baseline"
    # The existing full builder has its own zero-strict fallback.
    assert _build(case["response"]["hits"]["hits"])[1]


def test_a9_relax_replay_reports_pilot_subset_separately():
    from agent.es.evidence_core.arc_relax_replay import replay_relax_cases
    eligible = _a9_relax_case()
    unexhausted = _a9_relax_case()
    unexhausted["response"]["hits"]["total"]["value"] = 2
    zero = _a9_relax_case()
    zero["response"]["hits"]["hits"][0]["_source"]["multidim_event_json"][0]["evidence_snippets"].pop(0)
    result = replay_relax_cases([_a9_relax_labeled(case) for case in (eligible,unexhausted,zero)])
    assert result["pilot_status_counts"] == {"pilot_candidate_prepared":1,
        "primary_or_scan_not_exhausted":1,"legacy_zero_or_non_low_baseline":1}
    assert result["hypothetical_added"]==6
    assert result["pilot_comparison"]["full_selection"]["baseline"]["selected"]==1
    assert result["pilot_comparison"]["full_selection"]["candidate"]["selected"]==3
    assert "甲軸" not in repr(result)


def test_a6_pipeline_pilot_actual_builder_preserves_strict_and_weak_serialization(monkeypatch):
    from agent.es.evidence_core.arc_relax_replay import replay_relax_cases
    monkeypatch.setenv("SRAF_ARC_MODE","off")
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE","off")
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE",raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",raising=False)
    case = _a9_relax_case()
    fixture = _a9_relax_labeled(case)
    result = replay_relax_cases([fixture])
    assert result["pipeline_status_counts"] == {"pipeline_parity":1}
    assert result["pipeline_comparison"] == result["pilot_comparison"]
    assert result["pipeline_comparison"]["full_selection"]["candidate"]["selected"]==3
    assert len(_build(case["response"]["hits"]["hits"])[1])==1


@pytest.mark.parametrize("flag,value", [
    ("SRAF_EVIDENCE_RESCUE","1"),
    ("SRAF_TOPIC_MATCH_ADAPTIVE","on"),
    ("SRAF_TOPIC_MATCH_ADAPTIVE","shadow"),
    ("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET","1"),
])
def test_a6_pipeline_pilot_incompatible_legacy_selection_never_certifies_parity(monkeypatch,flag,value):
    from agent.es.evidence_core.arc_relax_replay import replay_relax_cases
    monkeypatch.setenv("SRAF_ARC_MODE","off")
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE","off")
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE",raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",raising=False)
    fixture = _a9_relax_labeled(_a9_relax_case())
    monkeypatch.setenv(flag,value)
    result = replay_relax_cases([fixture])
    assert result["pilot_status_counts"] == {"pilot_candidate_prepared":1}
    assert result["pipeline_comparison"] is None
    assert sum(result["pipeline_status_counts"].values())==1
    assert "pipeline_parity" not in result["pipeline_status_counts"]


def test_a6_pipeline_check_failure_keeps_counterfactual_without_certifying(monkeypatch):
    from agent.es.evidence_core import arc_relax_replay as replay
    fixture = _a9_relax_labeled(_a9_relax_case())
    def fail(*a,**kw):
        raise RuntimeError("PRIVATE_FAILURE")
    monkeypatch.setattr(replay,"build_hits_and_evidence",fail)
    result = replay.replay_relax_cases([fixture])
    assert result["pipeline_status_counts"] == {"pipeline_unavailable":1}
    assert result["pipeline_comparison"] is None
    assert result["pilot_comparison"] is not None
    assert "PRIVATE_FAILURE" not in repr(result)


def test_a6_offline_builder_never_applies_pilot_without_shared_budget(monkeypatch):
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    monkeypatch.setenv("SRAF_ARC_MODE","off")
    monkeypatch.setenv("SRAF_TOPIC_MATCH_ADAPTIVE","off")
    monkeypatch.delenv("SRAF_EVIDENCE_RESCUE",raising=False)
    monkeypatch.delenv("SRAF_EVIDENCE_SHARED_SOURCE_BUDGET",raising=False)
    case=_a9_relax_case()
    status={}
    _, rows, _ = build_hits_and_evidence(
        case["response"]["hits"]["hits"],date_from=case["date_from"],date_to=case["date_to"],
        effective_terms=["甲軸","乙軸","丙軸"],term_groups=AXES,
        query_for_snippet=case["query"],original_question=case["question"],
        include_source_hit_ordinal=True,
        arc_candidate_pressure=CandidatePressure.from_primary(case["response"]),
        _offline_a6_pilot=True,_offline_a6_status=status)
    assert len(rows)==1 and rows[0]["match_policy"]=="strict"
    assert status["status"]=="incompatible_scope_or_rescue"
