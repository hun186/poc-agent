"""Cross-layer completeness regressions for bounded date-scoped ES searches.

Every external dependency is stubbed: no network, LLM, SQL or ES calls.
"""
from contextlib import nullcontext
import json

from agent.data_agent.runtime import (
    _get_query_meta_from_payload,
    _propagate_search_completeness,
)


def _limited_payload(evidence=None):
    return {
        "question": "2025年救援事件",
        "query_meta": {
            "core_terms": ["救援"],
            "date_from": "2025-06-17",
            "date_to": "2025-06-17",
            "result_incomplete": False,  # LLM reconstructed without tool truth
        },
        "raw_search_result": {
            "query_meta": {
                "result_incomplete": True,
                "note": "date_candidate_scan_limit_reached",
                "date_candidate_refill": {
                    "candidate_scan_limit": 256,
                    "candidates_scanned": 256,
                    "search_exhausted": False,
                },
            },
        },
        "evidence_snippets": evidence or [],
        "time_range": {
            "date_from": "2025-06-17", "date_to": "2025-06-17",
        },
        "stats": {"doc_count": 0, "snippet_count": 0, "active_days": 0,
                  "day_counts": {}, "month_counts": {}, "quarter_counts": {}},
    }


def test_raw_es_incomplete_status_overrides_optimistic_agent_query_meta():
    payload = _limited_payload()
    meta = _get_query_meta_from_payload(payload)
    assert meta["core_terms"] == ["救援"]
    assert meta["result_incomplete"] is True
    assert meta["date_candidate_refill"]["candidates_scanned"] == 256
    _propagate_search_completeness(payload)
    assert payload["result_incomplete"] is True
    assert payload["query_meta"]["result_incomplete"] is True
    assert payload["search_status"]["incomplete"] is True


def test_data_agent_runtime_normalizes_search_completeness_before_trace(monkeypatch):
    import agent.data_agent.runtime as runtime
    payload = _limited_payload()

    class StubAgent:
        def run(self, _question):
            return {"payload": payload}

    monkeypatch.setattr(runtime, "build_agent", lambda mode: StubAgent())
    trace = {}
    result = runtime.run_data_agent(
        "2025年救援事件", mode="report", trace=trace,
        question_raw="原始問題",
    )
    assert result["result_incomplete"] is True
    assert result["query_meta"]["date_candidate_refill"]["candidate_scan_limit"] == 256
    assert trace["data_agent"]["runs"][-1]["query_meta"]["result_incomplete"] is True


def _stub_report_dependencies(monkeypatch, payload, *, llm_result="初步整理"):
    import agent.report_agent as report_module
    called = []
    monkeypatch.setattr(
        report_module, "refine_question_for_data_agent",
        lambda q, **kwargs: q,
    )
    monkeypatch.setattr(report_module, "run_data_agent", lambda *args, **kw: payload)
    monkeypatch.setattr(report_module, "log_duration", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(report_module, "log_total", lambda *a, **kw: None)

    def fake_llm(prompt, **kw):
        called.append(json.loads(prompt))
        return llm_result

    monkeypatch.setattr(report_module, "call_llm", fake_llm)
    monkeypatch.setattr(
        report_module, "pack_ev_for_llm",
        lambda ev, *args, **kw: {
            "ev_slim": ev, "meta": {
                "mode": "rules", "allow_fields": ["ref_no", "note"],
                "fields_count": 2, "llm_used": False, "fallback_used": False,
            },
        },
    )
    return report_module, called


def test_incomplete_empty_es_scan_aborts_zero_result_report_before_llm(monkeypatch):
    payload = _limited_payload()
    mod, calls = _stub_report_dependencies(monkeypatch, payload)
    result = mod.ask_with_report("2025年救援事件")
    assert calls == []  # no report LLM hallucinating an exhaustive zero
    assert result["result_incomplete"] is True
    assert result["search_status"]["incomplete"] is True
    assert result["query_meta"]["date_candidate_refill"]["candidate_scan_limit"] == 256
    assert "不代表沒有新聞" in result["answer"]
    assert "不產生正式零結果" in result["answer"]
    assert result["citations"] == []


def test_partial_scan_warns_llm_and_deterministically_prefixes_report(monkeypatch):
    payload = _limited_payload(evidence=[{
        "uuid": "doc-1",
        "text": "救援行動已啟動",
        "date_iso": "2025-06-17",
        "article_date_iso": "2026-01-01",
        "article_title": "原始新聞",
    }])
    mod, calls = _stub_report_dependencies(monkeypatch, payload)
    result = mod.ask_with_report("2025年救援事件")
    assert len(calls) == 1
    assert calls[0]["search_status"]["incomplete"] is True
    assert calls[0]["search_status"]["date_candidate_refill"]["candidates_scanned"] == 256
    assert result["result_incomplete"] is True
    assert result["answer"].startswith("⚠️ 日期檢索結果不完整")
    assert "初步整理" in result["answer"]
    assert "不具完整性" in result["reasoning"]


def test_complete_report_keeps_old_answer_contract(monkeypatch):
    payload = _limited_payload(evidence=[{
        "uuid": "doc-1", "text": "已確認的救援", "date_iso": "2025-06-17",
    }])
    payload["raw_search_result"]["query_meta"] = {}
    mod, calls = _stub_report_dependencies(monkeypatch, payload)
    result = mod.ask_with_report("2025年救援事件")
    assert len(calls) == 1
    assert "search_status" not in calls[0]
    assert result["answer"] == "初步整理"
    assert "result_incomplete" not in result
