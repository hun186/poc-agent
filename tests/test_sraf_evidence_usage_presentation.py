"""Real report→shared presenter→Markdown/Word count-only integration (synthetic input)."""
from __future__ import annotations

import json
from io import BytesIO
from contextlib import nullcontext

from docx import Document
from starlette.requests import Request

from api.core.presenters.evidence_usage import evidence_usage_rows, safe_evidence_usage
from api.core.presenters.extractors import extract_presentation
from api.services.export_word_service import ExportWordService
from api.services.markdown_renderer import render_markdown


def _usage():
    return {
        "schema": "sraf_report_evidence_usage_v1",
        "selection_mode": "source_diverse",
        "llm_skipped_incomplete": False,
        "llm_skipped_no_evidence": False,
        "incoming": 5, "strong": 4, "weak": 1,
        "picked": 3, "compressed": 3, "llm_input": 2,
        "incoming_identified_sources": 3,
        "picked_identified_sources": 2,
        "llm_input_identified_sources": 2,
        "max_for_llm": 120, "prompt_chars": 1193,
        "truncated_notes": 0, "truncated_titles": 0,
    }


def _output(usage):
    return {
        "mode": "SRA_REPORT", "question": "合成測試問題",
        "answer": "合成測試答案", "citations": [],
        "data_agent": {
            "runs": [{
                "mode": "SRA_REPORT", "question_raw": "合成測試問題",
                "stats": {"doc_count": 3, "snippet_count": 5},
            }],
        },
        "evidence_usage": usage,
    }


def _render_both(output):
    req = Request({
        "type": "http", "method": "GET",
        "scheme": "http", "path": "/v1/chat/completions",
        "server": ("testserver", 80), "headers": [],
    })
    markdown = render_markdown(output, req)
    data, _ = ExportWordService().build_docx_bytes(output)
    paragraphs = [p.text for p in Document(BytesIO(data)).paragraphs]
    return markdown, paragraphs


def test_word_and_openwebui_share_exact_same_evidence_rows():
    output = _output(_usage())
    md, doc = _render_both(output)
    assert "資料整備紀錄（Data Agent）" in md
    assert "資料整備紀錄（Data Agent）" in doc
    assert "Evidence 篩選與使用紀錄" in md
    assert "Evidence 篩選與使用紀錄" in doc
    rows = evidence_usage_rows(_usage())
    assert len(rows) >= 8
    for label, value in rows:
        assert f"{label}：{value}" in md
        assert f"{label}：{value}" in doc
    assert "Prompt 長度：1193 字元（非 Token 數）" in doc
    assert "已識別來源保留率：66.7%（僅已識別來源）" in md


def test_malformed_or_private_metrics_sanitized_before_rendering():
    dirty = {**_usage(), "source_uuid": "PRIVATE-DOC-ID",
             "raw_evidence": "PRIVATE-SNIPPET"}
    cleaned = safe_evidence_usage(dirty)
    assert set(cleaned) == set(_usage())
    assert "PRIVATE" not in json.dumps(cleaned)
    for value in (None, {"schema": "wrong"}, {**_usage(), "picked": "3"},
                  {**_usage(), "llm_input": 99},
                  {**_usage(), "prompt_chars": True}):
        assert safe_evidence_usage(value) == {}
        assert evidence_usage_rows(value) == []


def test_missing_stats_preserves_legacy_word_and_markdown():
    md, doc = _render_both(_output(None))
    assert "Evidence 篩選與使用紀錄" not in md
    assert "Evidence 篩選與使用紀錄" not in doc
    assert "AI 代理人回答" in doc


def test_real_report_path_emits_same_counts_as_private_trace(
        monkeypatch, caplog):
    from test_sraf_report_evidence_trace import _stub_report, _snippet, _logs
    import logging

    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("SRAF_REPORT_DIVERSE_EVIDENCE", "1")
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "2")
    report, calls = _stub_report(monkeypatch, [
        _snippet(1, text="a-one"), _snippet(1, text="a-two"),
        _snippet(2, text="b-one"),
    ])
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        out = report.ask_with_report("synthetic")
    usage = out["evidence_usage"]
    record = _logs(caplog)[0]["counters"]
    assert usage["selection_mode"] == "source_diverse"
    for key in ("incoming", "picked", "compressed", "llm_input",
                "incoming_identified_sources", "picked_identified_sources",
                "llm_input_identified_sources", "prompt_chars"):
        assert usage[key] == record[key]
    assert len(calls[0]["ev"]) == usage["llm_input"] == 2
    assert usage["llm_input_identified_sources"] == 2


def test_incomplete_zero_evidence_reports_skipped_without_llm(monkeypatch):
    from test_sraf_report_evidence_trace import _stub_report
    report, calls = _stub_report(monkeypatch, [], incomplete=True)
    out = report.ask_with_report("synthetic")
    assert not calls
    assert out["evidence_usage"]["llm_skipped_incomplete"] is True
    assert "報告 LLM" in dict(evidence_usage_rows(out["evidence_usage"]))



def _topic_summary(mode="shadow", *, selected=0):
    return {
        "schema": "sraf_topic_adaptive_report_v1",
        "scope": "data_agent_tool_slices_not_global_recall",
        "mode": mode, "truncated": False, "slices": 1, "strict": 1, "proposed": 2,
        "selected": selected, "no_anchor": 0, "not_low": 0,
        "attempted": 1, "uninspected": 0,
    }


def test_topic_match_adaptive_log_is_plain_language_in_word_and_markdown():
    from api.core.presenters.evidence_usage import safe_topic_adaptive
    for mode, selected in (("shadow", 0), ("on", 2)):
        usage = {**_usage(), "topic_adaptive": _topic_summary(mode, selected=selected)}
        dirty = {**usage, "topic_adaptive": {**usage["topic_adaptive"],
            "question": "PRIVATE-QUESTION", "uuid": "PRIVATE-UUID",
            "content": "PRIVATE-EVIDENCE"}}
        clean = safe_evidence_usage(dirty)
        assert safe_topic_adaptive(dirty["topic_adaptive"])
        assert "PRIVATE" not in json.dumps(clean)
        md, doc = _render_both(_output(usage))
        text = "\n".join(doc)
        for label, value in evidence_usage_rows(usage):
            assert f"{label}：{value}" in md
            assert f"{label}：{value}" in text
        assert "主題檢索智慧放寬" in text
        assert "估計" not in text  # Distinguish bounded proposal from precision.
        assert "PRIVATE" not in (md + text)


def test_invalid_topic_adaptive_metrics_never_reach_docx():
    from api.core.presenters.evidence_usage import safe_topic_adaptive
    base = _topic_summary()
    for invalid in (
        {**base, "mode": "PRIVATE"},
        {**base, "selected": 1},
        {**base, "proposed": True},
        {**base, "slices": 33},
        {**base, "strict": "1"},
        {**base, "scope": "wrong"},
    ):
        assert safe_topic_adaptive(invalid) == {}
        usage = {**_usage(), "topic_adaptive": invalid}
        md, doc = _render_both(_output(usage))
        assert "主題檢索智慧放寬" not in md
        assert "主題檢索智慧放寬" not in "\n".join(doc)


def test_request_local_topic_audit_survives_tool_thread_but_not_next_request():
    from concurrent.futures import ThreadPoolExecutor
    from agent.es.evidence_core.topic_audit import (
        bind_sink, current_sink, record, summary,
    )
    from agent.tools_es.common import (
        bind_requirement_acceptance, propagate_requirement_acceptance,
    )

    class SyntheticTool:
        @propagate_requirement_acceptance
        def forward(self):
            record(
                mode="shadow", status="shadow", strict=1,
                counts={k: v for k, v in (
                    ("inspected", 4), ("date_eligible", 3),
                    ("two_text_axes", 2), ("direct_subject", 1),
                    ("same_event_context", 1),
                    ("blocked_meta_only", 0), ("blocked_unanchored", 0),
                    ("uninspected_by_cap", 0), ("proposed", 2),
                    ("selected", 0),
                )},
            )
            return current_sink() is not None

    first, second = [], []
    with bind_sink(first):
        one = bind_requirement_acceptance(SyntheticTool())
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(one.forward).result() is True
    with bind_sink(second):
        two = bind_requirement_acceptance(SyntheticTool())
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(two.forward).result() is True
    assert current_sink() is None
    assert summary(first, mode="shadow")["proposed"] == 2
    assert summary(second, mode="shadow")["proposed"] == 2
    assert len(first) == len(second) == 1



def test_topic_audit_after_32_slices_is_labeled_incomplete():
    from agent.es.evidence_core.topic_audit import bind_sink, record, summary
    from api.core.presenters.evidence_usage import topic_adaptive_rows
    counts = {key: 0 for key in (
        "inspected", "date_eligible", "two_text_axes", "direct_subject",
        "same_event_context", "blocked_meta_only", "blocked_unanchored",
        "uninspected_by_cap", "proposed", "selected",
    )}
    sink = []
    with bind_sink(sink):
        for i in range(33):
            record(mode="shadow", status="shadow", strict=1,
                   counts={**counts, "proposed": 1 if i == 32 else 0})
    result = summary(sink, mode="shadow")
    assert result["slices"] == 32
    assert result["truncated"] is True
    assert result["proposed"] == 0
    text = str(topic_adaptive_rows(result))
    assert "檢索歷程不完整" in text
    assert "前 32 批" in text

def test_zero_evidence_guard_is_visible_in_word_and_markdown_without_private_fields():
    empty = {**_usage(), **{
        "incoming": 0, "strong": 0, "weak": 0, "picked": 0,
        "compressed": 0, "llm_input": 0,
        "incoming_identified_sources": 0, "picked_identified_sources": 0,
        "llm_input_identified_sources": 0, "max_for_llm": 0,
        "prompt_chars": 0, "llm_skipped_no_evidence": True,
        "private_question": "PRIVATE-ZERO-EVIDENCE-QUESTION",
    }}
    safe = safe_evidence_usage(empty)
    assert safe["llm_skipped_no_evidence"] is True
    assert "private_question" not in safe
    assert "未執行（缺少可核對的有效 Evidence" in dict(evidence_usage_rows(empty))["報告 LLM"]
    md, doc = _render_both(_output(empty))
    assert "未執行（缺少可核對的有效 Evidence" in md
    assert "未執行（缺少可核對的有效 Evidence" in "\n".join(doc)
    assert "PRIVATE-ZERO-EVIDENCE-QUESTION" not in (md + "\n".join(doc))
    assert safe_evidence_usage({**empty, "llm_skipped_no_evidence": "true"}) == {}
    assert safe_evidence_usage({**empty, "incoming": 1, "strong": 1}) == {}

def test_llm_phantom_source_label_and_short_note_warning_reaches_word(monkeypatch):
    from test_sraf_report_evidence_trace import _stub_report, _snippet
    report, calls = _stub_report(monkeypatch, [
        _snippet(1, text="會面某位代表。"),
    ])
    monkeypatch.setattr(report, "call_llm",
                        lambda prompt, **kw: "來源999聲稱已完成所有驗收。")
    out = report.ask_with_report("合成短片段報告")
    assert "無法對應本次有效 Evidence 的來源編號" in out["answer"]
    assert "Evidence 片段較少或文字過短" in out["answer"]
    assert out["answer"].endswith("來源999聲稱已完成所有驗收。")
    assert len(calls) == 0  # replaced call_llm, never an additional model call
    usage = out["evidence_usage"]
    assert usage["citation_labels"]["status"] == "unmapped"
    assert usage["citation_labels"]["unmapped_labels"] == 1
    assert usage["evidence_information"]["status"] == "limited_text"
    clean_once = safe_evidence_usage(usage)
    assert clean_once["citation_labels"]["status"] == "unmapped"
    assert clean_once["evidence_information"]["status"] == "limited_text"
    assert safe_evidence_usage(clean_once) == clean_once

    md, paragraphs = _render_both({**_output(out["evidence_usage"]), "answer": out["answer"]})
    text = "\n".join(paragraphs)
    assert "來源編號一致性" in md and "來源編號一致性" in text
    assert "Evidence 資訊量提醒" in md and "Evidence 資訊量提醒" in text
    assert "無法對應本次有效 Evidence" in md
    assert "來源999" in md


def test_detailed_source_mapped_evidence_keeps_plain_answer(monkeypatch):
    from test_sraf_report_evidence_trace import _stub_report, _snippet
    report, calls = _stub_report(monkeypatch, [
        _snippet(i, text=("事件背景及現場處置資訊。" * 18))
        for i in range(1, 5)
    ])
    monkeypatch.setattr(report, "call_llm",
                        lambda prompt, **kw: "來源1及來源2顯示尚待追蹤。")
    out = report.ask_with_report("合成多來源報告")
    assert out["answer"] == "來源1及來源2顯示尚待追蹤。"
    assert out["evidence_usage"]["citation_labels"]["status"] == "labels_match"
    assert out["evidence_usage"]["evidence_information"]["status"] == "measured_only"
    assert len(calls) == 0


def test_malformed_optional_integrity_metrics_do_not_reach_report_word():
    usage = {**_usage(),
        "citation_labels": {
            "schema": "sraf_report_citation_labels_v1", "status": "unmapped",
            "labels_seen": True, "unique_labels": 1,
            "unmapped_labels": 1, "allowed_reference_count": 1,
            "source_id": "PRIVATE-SOURCE-ID",
        },
        "evidence_information": {
            "schema": "sraf_report_evidence_information_v1",
            "status": "limited_text", "rows": 1,
            "total_visible_chars": 10, "short_notes": 2,
            "date_only_notes": 0, "note": "PRIVATE-EVIDENCE",
        }}
    safe = safe_evidence_usage(usage)
    assert "citation_labels" not in safe
    assert "evidence_information" not in safe
    md, paragraphs = _render_both(_output(usage))
    assert "PRIVATE-SOURCE-ID" not in md + "\n".join(paragraphs)
    assert "PRIVATE-EVIDENCE" not in md + "\n".join(paragraphs)
