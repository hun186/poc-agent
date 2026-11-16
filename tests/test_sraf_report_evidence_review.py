"""No-network regression for pre-report Evidence relevance LLM review."""
from __future__ import annotations
import copy
import json
from io import BytesIO

from docx import Document

from agent.utils.report_evidence_review import (
    MAX_BATCH_CHARS, _parse_decisions, review_report_evidence,
)
from api.core.presenters.evidence_usage import (
    evidence_usage_rows, safe_evidence_usage, safe_review,
)
from api.services.export_word_service import ExportWordService


def _rows(n=10):
    return [
        {"ref_no": i, "note": f"原文證據-{i}", "title": f"標題-{i}",
         "d": "2023-08-24", "tp": "day", "id": f"SENSITIVE-ID-{i}"}
        for i in range(1, n + 1)
    ]


def _response(prompt, *, reject=()):
    req = json.loads(prompt)
    return json.dumps({"decisions": [
        {"ref_no": item["ref_no"], "relevant": item["ref_no"] not in reject,
         "confidence": "high"} for item in req["ev"]
    ]})


def test_off_is_exact_no_call(monkeypatch):
    rows = _rows()
    baseline = copy.deepcopy(rows)
    result, metrics = review_report_evidence(
        "原始問題", rows, mode="off", model="fake",
        call_llm_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError()),
    )
    assert result == baseline == rows
    assert metrics["status"] == "disabled"
    assert metrics["calls"] == 0
    assert metrics["removed"] == 0


def test_review_default_is_off_until_real_quality_acceptance(monkeypatch):
    monkeypatch.delenv("SRAF_REPORT_EVIDENCE_REVIEW", raising=False)
    result, report = review_report_evidence(
        "問題", _rows(1), model="fake",
        call_llm_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError()),
    )
    assert len(result) == 1 and report["status"] == "disabled"


def test_bounded_batches_original_question_no_rewrite():
    original = _rows(10)
    before = copy.deepcopy(original)
    seen = []

    def llm(prompt, **kw):
        req = json.loads(prompt)
        assert req["q0"] == "原始提問"
        assert all("id" not in e for e in req["ev"])
        assert kw["stage"] == "evidence_review"
        seen.append([e["ref_no"] for e in req["ev"]])
        return _response(prompt, reject={2, 6})

    kept, meta = review_report_evidence(
        "原始提問", original, mode="on", batch_items=3,
        model="fake", call_llm_fn=llm)
    assert seen == [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
    assert [e["ref_no"] for e in kept] == [1, 3, 4, 5, 7, 8, 9, 10]
    assert meta["batches"] == meta["calls"] == 4
    assert meta["before"] == 10 and meta["after"] == 8
    assert meta["proposed_removed"] == meta["removed"] == 2
    assert original == before
    assert all(kept_item is original[kept_item["ref_no"] - 1] for kept_item in kept)
    # No new source text/citations/dates can be supplied through model response.
    assert "SENSITIVE-ID-" not in json.dumps(meta)


def test_high_rejection_rolls_back_all_and_flags_anomaly():
    baseline = _rows(10)
    kept, meta = review_report_evidence(
        "原問句", baseline, mode="on", model="fake",
        call_llm_fn=lambda p, **kw: _response(p, reject={1, 2, 3}))
    assert kept == baseline and meta["removed"] == 0
    assert meta["proposed_removed"] == 3
    assert meta["status"] == "fallback"
    assert meta["reason"] == "excessive_rejection" and meta["anomaly"] is True


def test_shadow_records_proposal_without_excluding():
    rows = _rows(10)
    kept, meta = review_report_evidence(
        "問題", rows, mode="shadow", model="fake",
        call_llm_fn=lambda p, **kw: _response(p, reject={1}))
    assert kept == rows and meta["status"] == "shadow"
    assert meta["proposed_removed"] == 1 and meta["removed"] == 0


def test_invalid_output_or_model_failure_preserves_all():
    for fn in (
        lambda p, **kw: "報告",
        lambda p, **kw: json.dumps({"decisions": [
            {"ref_no": 999, "relevant": False, "confidence": "high"}]}),
        lambda p, **kw: (_ for _ in ()).throw(TimeoutError("private")),
    ):
        kept, meta = review_report_evidence(
            "原問句", _rows(1), mode="on", model="fake",
            call_llm_fn=fn)
        assert len(kept) == 1
        assert meta["status"] == "fallback" and meta["removed"] == 0
        assert meta["anomaly"] is True
        assert "private" not in json.dumps(meta)
    assert _parse_decisions('{"decisions":[{"ref_no":true,"relevant":false,'
                            '"confidence":"high"}]}', [1]) is None
    assert _parse_decisions('{"decisions":[{"ref_no":1,"relevant":"false",'
                            '"confidence":"high"}]}', [1]) is None


def test_deeply_nested_llm_json_falls_back_without_aborting_report():
    invalid = "[" * 1100 + "0" + "]" * 1100
    rows = _rows(2)
    kept, meta = review_report_evidence(
        "問題", rows, mode="on", model="fake",
        call_llm_fn=lambda prompt, **kw: invalid,
    )
    assert kept == rows
    assert meta["status"] == "fallback"
    assert meta["reason"] == "invalid_response"
    assert meta["removed"] == 0 and meta["anomaly"]


def test_input_over_budget_must_not_make_partial_calls():
    calls = []
    def llm(*a, **kw):
        calls.append(1)
        raise AssertionError("unexpected")
    for rows, mode, cap in [
        (_rows(501), "on", 24000),
        (_rows(10), "on", 2000),
    ]:
        if len(rows) == 10:
            for row in rows:
                row["note"] = "長" * 4000
        kept, meta = review_report_evidence(
            "原始問題", rows, mode=mode, model="fake",
            batch_chars=cap, call_llm_fn=llm)
        assert kept == rows and meta["status"] == "fallback"
        assert meta["calls"] == 0
    assert calls == []


def test_dynamic_char_batching_does_not_truncate_evidence():
    rows = _rows(6)
    for row in rows:
        row["note"] = "文字" * 500
    seen = []
    def llm(p, **kw):
        assert len(p) <= 2800
        seen.append(json.loads(p)["ev"])
        return _response(p)
    kept, meta = review_report_evidence(
        "問題", rows, mode="on", model="fake", batch_items=125,
        batch_chars=2800, max_calls=4, call_llm_fn=llm)
    assert len(kept) == 6
    assert len(seen) >= 3
    assert sum(len(chunk) for chunk in seen) == 6
    assert meta["input_chars"] <= 4 * 2800


def test_review_metrics_word_presentation_no_raw_model_text():
    _, review = review_report_evidence(
        "PRIVATE-QUESTION", _rows(10), mode="on", model="fake",
        call_llm_fn=lambda p, **kw: _response(p, reject={1}))
    usage = {
        "schema": "sraf_report_evidence_usage_v1",
        "selection_mode": "strong_first",
        "llm_skipped_incomplete": False,
        "incoming": 10, "strong": 10, "weak": 0,
        "picked": 10, "compressed": 10, "llm_input": 9,
        "incoming_identified_sources": 10,
        "picked_identified_sources": 10,
        "llm_input_identified_sources": 9,
        "max_for_llm": 120, "prompt_chars": 50,
        "truncated_notes": 0, "truncated_titles": 0,
        "review": {**review, "source_id": "SENSITIVE-ID-1"},
    }
    safe = safe_evidence_usage(usage)
    assert safe_review(review)
    assert "source_id" not in json.dumps(safe)
    rows = evidence_usage_rows(usage)
    assert any(k == "LLM 覆核前後" and "10 → 9" in v for k, v in rows)
    out = {
        "mode": "SRA_REPORT", "question": "測試", "answer": "答案",
        "citations": [], "evidence_usage": usage,
    }
    data, _ = ExportWordService().build_docx_bytes(out)
    rendered = "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    assert "LLM 覆核前後" in rendered
    assert "10 → 9 段" in rendered
    assert "PRIVATE-QUESTION" not in rendered
    assert "SENSITIVE-ID" not in rendered


def test_real_agent_review_filters_llm_input_and_citations(monkeypatch):
    from test_sraf_report_evidence_trace import _snippet, _stub_report
    monkeypatch.setenv("SRAF_REPORT_EVIDENCE_REVIEW", "on")
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "10")
    report, calls = _stub_report(monkeypatch, [_snippet(i) for i in range(1, 11)])
    def llm(p, **kw):
        if kw.get("stage") == "evidence_review":
            return _response(p, reject={1, 2})
        calls.append(json.loads(p))
        return "Synthetic report"
    monkeypatch.setattr(report, "call_llm", llm)
    result = report.ask_with_report("原始提問")
    usage = result["evidence_usage"]
    assert usage["review"]["status"] == "applied"
    assert usage["review"]["before"] == 10 and usage["review"]["after"] == 8
    assert usage["compressed"] == 10 and usage["llm_input"] == 8
    assert len(calls) == 1 and len(calls[0]["ev"]) == 8
    assert set(row["ref_no"] for row in calls[0]["ev"]) == set(range(3, 11))
    assert result["answer"] == "Synthetic report"
    assert len(result["citations"]) == 8


def test_default_120_limit_is_not_500():
    # A quantity cap is not a token-context guarantee.
    assert MAX_BATCH_CHARS == 24000
