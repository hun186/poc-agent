"""#397: report-stage Evidence counts, real call boundary, and log privacy.

All external data-agent/LLM dependencies are synthetic; production logic runs.
"""
from __future__ import annotations

from contextlib import nullcontext
import json
import logging

from agent.utils.report_evidence_trace import emit_report_evidence_trace


def _logs(caplog):
    return [
        json.loads(r.message.partition("SRAF_REPORT_EVIDENCE_TRACE=")[2])
        for r in caplog.records if r.name == "sraf.report_evidence_trace"
        and r.message.startswith("SRAF_REPORT_EVIDENCE_TRACE=")
    ]


def _stub_report(monkeypatch, snippets, *, incomplete=False):
    import agent.report_agent as report
    calls = []
    payload = {
        "evidence_snippets": snippets,
        "question": "SENSITIVE-RAW-QUESTION",
        "time_range": {"date_from": "2023-08-24", "date_to": "2023-08-24"},
        "stats": {"doc_count": len(snippets), "snippet_count": len(snippets),
                  "active_days": 0, "day_counts": {}, "month_counts": {},
                  "quarter_counts": {}},
        "query_meta": {},
        "raw_search_result": {"query_meta": {
            "result_incomplete": incomplete,
            **({"note": "date_candidate_scan_limit_reached"} if incomplete else {}),
        }},
    }
    monkeypatch.setattr(report, "refine_question_for_data_agent",
                        lambda q, **kw: q)
    monkeypatch.setattr(report, "run_data_agent", lambda *a, **kw: payload)
    monkeypatch.setattr(report, "log_duration", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(report, "log_total", lambda *a, **kw: None)
    monkeypatch.setattr(
        report, "pack_ev_for_llm",
        lambda ev, *a, **kw: {
            "ev_slim": ev,
            "meta": {
                "mode": "rules", "allow_fields": ["ref_no", "note"],
                "fields_count": 2, "llm_used": False, "fallback_used": False,
            },
        },
    )

    def fake_llm(prompt, **kw):
        calls.append(json.loads(prompt))
        return "合成測試報告"

    monkeypatch.setattr(report, "call_llm", fake_llm)
    return report, calls


def _snippet(i, *, text=None, weak=False):
    return {
        "uuid": f"SENSITIVE-UUID-{i}",
        "text": text or f"SENSITIVE-EVIDENCE-{i}",
        "article_title": f"SENSITIVE-TITLE-{i}",
        "date_iso": "2023-08-24",
        "weak_evidence": weak,
    }


def test_reporting_trace_off_keeps_result_and_suppresses_raw_evidence_stdout(
        monkeypatch, caplog, capsys):
    monkeypatch.delenv("SRAF_EVIDENCE_TRACE", raising=False)
    mod, calls = _stub_report(monkeypatch, [_snippet(0)])
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        result = mod.ask_with_report("SENSITIVE-RAW-QUESTION")
    assert result["answer"] == "合成測試報告"
    assert len(calls) == 1
    assert not _logs(caplog)
    stdout = capsys.readouterr().out
    assert "SENSITIVE-EVIDENCE-0" not in stdout
    assert "SENSITIVE-TITLE-0" not in stdout
    assert "SENSITIVE-UUID-0" not in stdout


def test_reporting_trace_is_exact_pre_llm_counts_and_no_text(
        monkeypatch, caplog, capsys):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "2")
    snippets = [_snippet(1), _snippet(2), _snippet(3, weak=True)]
    mod, calls = _stub_report(monkeypatch, snippets)
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        result = mod.ask_with_report("SENSITIVE-RAW-QUESTION")
    assert len(calls) == 1
    assert len(calls[0]["ev"]) == 2
    assert result["answer"] == "合成測試報告"
    entry, = _logs(caplog)
    assert entry["scope"] == "single_report_pre_llm_not_final_report_or_token_count"
    c = entry["counters"]
    assert c["incoming"] == 3
    assert c["strong"] == 2
    assert c["weak"] == 1
    assert c["picked"] == c["compressed"] == c["llm_input"] == 2
    assert c["strong_or_weak_unselected"] == 1
    assert c["max_for_llm"] == 2
    assert c["prompt_chars"] > 0
    assert not entry["report_llm_skipped_incomplete_search"]
    safe_record = json.dumps(entry, ensure_ascii=False)
    for secret in ("SENSITIVE-", "2023-08-24", "SENSITIVE-RAW-QUESTION"):
        assert secret not in safe_record
    stdout = capsys.readouterr().out
    assert "SENSITIVE-TITLE" not in stdout
    assert "SENSITIVE-EVIDENCE" not in stdout


def test_compression_loss_and_note_limit_are_observed_without_token_claim(
        monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "120")
    monkeypatch.setenv("REPORT_EV_NOTE_CHAR_LIMIT", "4")
    snippets = [
        _snippet(1, text="SENSITIVE-LONG-NOTE"),
        _snippet(1, text="SENSITIVE-LONG-NOTE"),  # same uuid/time/text -> dedup
    ]
    mod, calls = _stub_report(monkeypatch, snippets)
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        mod.ask_with_report("SENSITIVE-RAW-QUESTION")
    c = _logs(caplog)[0]["counters"]
    assert c["picked"] == 2
    assert c["compressed"] == c["llm_input"] == 1
    assert c["removed_during_compression"] == 1
    assert c["truncated_notes"] == 1
    assert "token" not in c
    assert len(calls[0]["ev"]) == 1
    assert calls[0]["ev"][0]["note"].startswith("SENS")


def test_bounded_120_max_count_is_truthful(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    monkeypatch.setenv("REPORT_MAX_EVIDENCE_SNIPS", "120")
    mod, calls = _stub_report(monkeypatch, [_snippet(i) for i in range(125)])
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        mod.ask_with_report("SENSITIVE-RAW-QUESTION")
    c = _logs(caplog)[0]["counters"]
    assert c["incoming"] == 125
    assert c["picked"] == c["compressed"] == c["llm_input"] == 120
    assert c["strong_or_weak_unselected"] == 5
    assert len(calls[0]["ev"]) == 120


def test_incomplete_empty_scan_logs_llm_skipped_without_llm_call(
        monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    mod, calls = _stub_report(monkeypatch, [], incomplete=True)
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        result = mod.ask_with_report("SENSITIVE-RAW-QUESTION")
    assert calls == []
    assert result["result_incomplete"]
    entry, = _logs(caplog)
    assert entry["report_llm_skipped_incomplete_search"]
    assert entry["counters"]["llm_input"] == 0
    assert entry["counters"]["prompt_chars"] == 0


def test_tracer_never_accepts_source_text_or_prompt_in_schema(monkeypatch, caplog):
    monkeypatch.setenv("SRAF_EVIDENCE_TRACE", "1")
    with caplog.at_level(logging.WARNING, logger="sraf.report_evidence_trace"):
        emit_report_evidence_trace(
            incoming=1, strong=1, weak=0, picked=1, compressed=1,
            llm_input=1, max_for_llm=120, prompt_chars=184,
        )
    obj, = _logs(caplog)
    assert set(obj) == {
        "schema", "scope", "trace_id", "report_llm_skipped_incomplete_search",
        "counters",
    }
    assert set(obj["counters"]) == {
        "incoming", "strong", "weak", "picked", "compressed", "llm_input",
        "max_for_llm", "prompt_chars", "truncated_notes", "truncated_titles",
        "strong_or_weak_unselected", "removed_during_compression",
        "removed_after_field_selection",
    }
