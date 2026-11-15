"""No-network regression for request-local ORIGINAL question provenance (#406).

These tests exercise the real DataAgent runtime call boundary with a small
fake CodeAgent. The fake only observes scope; it is not a report/ES mock success.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.data_agent import runtime
from agent.tools_es.question_scope import (
    bind_original_report_question, get_original_report_question,
)


def test_question_scope_nested_cleanup_and_exception():
    assert get_original_report_question() is None
    with bind_original_report_question("原始問題：加薩"):
        assert get_original_report_question() == "原始問題：加薩"
        with bind_original_report_question("另一個問題"):
            assert get_original_report_question() == "另一個問題"
        assert get_original_report_question() == "原始問題：加薩"
        with pytest.raises(RuntimeError, match="failed"):
            with bind_original_report_question("臨時問題"):
                assert get_original_report_question() == "臨時問題"
                raise RuntimeError("failed")
        assert get_original_report_question() == "原始問題：加薩"
    assert get_original_report_question() is None


@pytest.mark.parametrize("raw", [None, "", "X" * 8193, 42, [], {}])
def test_missing_oversized_or_invalid_original_does_not_trust_partial(raw):
    with bind_original_report_question(raw):
        assert get_original_report_question() is None
    assert get_original_report_question() is None


def test_concurrent_request_local_questions_cannot_bleed():
    def worker(question: str):
        with bind_original_report_question(question):
            return get_original_report_question()

    originals = [f"原始問題{i}：不同主題" for i in range(80)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert list(pool.map(worker, originals)) == originals
    assert get_original_report_question() is None


def test_report_data_agent_scopes_actual_question_not_rewritten_tool_query(monkeypatch):
    seen = []

    class ObservingCodeAgent:
        def run(self, rewritten: str):
            seen.append((rewritten, get_original_report_question()))
            return {"payload": {"query_meta": {}, "evidence_snippets": []}}

    monkeypatch.setattr(runtime, "build_agent", lambda mode: ObservingCodeAgent())
    original = "原始問題：請分析2025年加薩停火與平民保護"
    rewritten = "核心關鍵詞組如下：聯合國、停火談判、平民保護"
    out = runtime.run_data_agent(
        rewritten, mode="report", question_raw=original, trace={},
    )
    assert seen == [(rewritten, original)]
    assert out["query_meta"]["question_raw"] == original
    assert get_original_report_question() is None


def test_report_with_missing_original_and_style_mode_fail_closed(monkeypatch):
    observed = []

    class Observer:
        def run(self, query):
            observed.append(get_original_report_question())
            return {"payload": {"query_meta": {}}}

    monkeypatch.setattr(runtime, "build_agent", lambda mode: Observer())
    with bind_original_report_question("外層不可借用"):
        runtime.run_data_agent(
            "資料代理人改寫詞", mode="report", question_raw=None,
            trace={},
        )
        runtime.run_data_agent(
            "風格資料", mode="style", question_raw="樣式問題",
            trace={},
        )
        assert get_original_report_question() == "外層不可借用"
    assert observed == [None, None]


def test_data_agent_exception_resets_scoped_original(monkeypatch):
    class BrokenAgent:
        def run(self, _query):
            assert get_original_report_question() == "只能作用於本次請求"
            raise RuntimeError("synthetic agent failure")

    monkeypatch.setattr(runtime, "build_agent", lambda mode: BrokenAgent())
    with pytest.raises(RuntimeError, match="synthetic agent failure"):
        runtime.run_data_agent(
            "改寫後查詢", mode="report",
            question_raw="只能作用於本次請求", trace={},
        )
    assert get_original_report_question() is None
