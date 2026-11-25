"""#406: original report question survives tool.worker threads without bleed.

Offline tests drive the real run_data_agent boundary and common tool decorator
with small observing CodeAgent/tool test doubles; they do not claim real
LLM, Elasticsearch or smolagents scheduler acceptance.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.data_agent import runtime
from agent.tools_es.common import bind_requirement_acceptance, propagate_requirement_acceptance
from agent.tools_es.question_scope import (
    bind_original_report_question, get_original_report_question,
)


class _ProbeTool:
    @propagate_requirement_acceptance
    def forward(self, *, fail: bool = False):
        value = get_original_report_question()
        if fail:
            raise RuntimeError("synthetic tool failure")
        return value


def _report_agent_factory(observed):
    def make_agent(mode):
        # The relevant assertion is at this exact construction boundary,
        # BEFORE CodeAgent.run dispatches the tool on another thread.
        observed.append(("construction", mode, get_original_report_question()))
        tool = bind_requirement_acceptance(_ProbeTool())

        class FakeCodeAgent:
            def run(self, rewritten):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    original_from_tool_thread = pool.submit(tool.forward).result()
                    plain_after_call = pool.submit(get_original_report_question).result()
                observed.append(("worker", rewritten, original_from_tool_thread))
                assert plain_after_call is None
                return {"payload": {"query_meta": {
                    "observed_in_worker": original_from_tool_thread,
                }}}

        return FakeCodeAgent()
    return make_agent


def test_real_report_runtime_binds_before_tool_creation_and_crosses_worker(monkeypatch):
    observed = []
    monkeypatch.setattr(runtime, "build_agent", _report_agent_factory(observed))
    raw = "主題：加薩\n請分析停火進程"
    result = runtime.run_data_agent(
        "核心關鍵詞組如下：聯合國、人道援助", mode="report",
        question_raw=raw, trace={},
    )
    assert observed == [
        ("construction", "report", raw),
        ("worker", "核心關鍵詞組如下：聯合國、人道援助", raw),
    ]
    assert result["query_meta"]["observed_in_worker"] == raw
    assert get_original_report_question() is None


def test_missing_original_and_style_do_not_inherit_outer_report_context(monkeypatch):
    observed = []
    monkeypatch.setattr(runtime, "build_agent", _report_agent_factory(observed))
    with bind_original_report_question("不可洩漏的其他請求"):
        report = runtime.run_data_agent(
            "純 LLM 重寫搜尋詞", mode="report", question_raw=None, trace={},
        )
        style = runtime.run_data_agent(
            "風格語料", mode="style", question_raw="樣式問題", trace={},
        )
        assert get_original_report_question() == "不可洩漏的其他請求"
    assert observed == [
        ("construction", "report", None),
        ("worker", "純 LLM 重寫搜尋詞", None),
        ("construction", "style", None),
        ("worker", "風格語料", None),
    ]
    assert report["query_meta"]["observed_in_worker"] is None
    assert style["query_meta"]["observed_in_worker"] is None


def test_sequential_tool_instances_on_one_worker_do_not_retain_context():
    with bind_original_report_question("主題：加薩"):
        a = bind_requirement_acceptance(_ProbeTool())
    with bind_original_report_question("主題：蘇丹"):
        b = bind_requirement_acceptance(_ProbeTool())
    with ThreadPoolExecutor(max_workers=1) as pool:
        seen = [
            pool.submit(a.forward).result(),
            pool.submit(get_original_report_question).result(),
            pool.submit(b.forward).result(),
            pool.submit(get_original_report_question).result(),
        ]
    assert seen == ["主題：加薩", None, "主題：蘇丹", None]
    assert get_original_report_question() is None


def test_tool_exception_restores_worker_scope():
    with bind_original_report_question("主題：加薩"):
        tool = bind_requirement_acceptance(_ProbeTool())
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="synthetic tool failure"):
            pool.submit(tool.forward, fail=True).result()
        assert pool.submit(get_original_report_question).result() is None


def test_concurrent_agents_bind_distinct_original_questions(monkeypatch):
    import threading
    observed = []
    lock = threading.Lock()

    def make_agent(mode):
        tool = bind_requirement_acceptance(_ProbeTool())

        class Agent:
            def run(self, rewritten):
                with ThreadPoolExecutor(max_workers=1) as inner:
                    value = inner.submit(tool.forward).result()
                with lock:
                    observed.append(value)
                return {"payload": {"query_meta": {"value": value}}}
        return Agent()

    monkeypatch.setattr(runtime, "build_agent", make_agent)

    def each(n):
        raw = f"主題：原始事項{n}"
        value = runtime.run_data_agent(
            f"重寫詞{n}", mode="report", question_raw=raw, trace={},
        )
        return value["query_meta"]["value"]

    with ThreadPoolExecutor(max_workers=8) as outer:
        actual = list(outer.map(each, range(30)))
    assert actual == [f"主題：原始事項{n}" for n in range(30)]
    assert set(observed) == set(actual)
    assert get_original_report_question() is None


def test_arc_budget_is_shared_across_worker_tools_and_sealed(monkeypatch):
    from agent.es.arc_request_budget import ArcUnits, current_arc_budget
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    captured = []
    results = []

    class BudgetTool:
        @propagate_requirement_acceptance
        def forward(self):
            budget, ordinal = current_arc_budget()
            return budget.reserve(ordinal, ArcUnits(slices=1))

    def make_agent(mode):
        captured.append(current_arc_budget())
        tools = [bind_requirement_acceptance(BudgetTool()) for _ in range(6)]

        class Agent:
            def run(self, rewritten):
                with ThreadPoolExecutor(max_workers=3) as pool:
                    results.extend(pool.map(lambda tool: tool.forward(), tools))
                    assert pool.submit(current_arc_budget).result() is None
                return {"payload": {}}

        return Agent()

    monkeypatch.setattr(runtime, "build_agent", make_agent)
    runtime.run_data_agent("測試", mode="report")
    assert sum(results) == 4
    budget, ordinal = captured[0]
    assert ordinal == 1
    assert budget.snapshot()[0] == ArcUnits(slices=4)
    assert not budget.reserve(ordinal, ArcUnits(hits=1))
    assert current_arc_budget() is None


def test_arc_budget_isolated_and_restored_after_runtime_exception(monkeypatch):
    from agent.es.arc_request_budget import (
        ArcRequestBudget, ArcUnits, bind_arc_budget, current_arc_budget,
    )
    monkeypatch.setenv("SRAF_ARC_GROUP_FREQUENCY", "shadow")
    parent = ArcRequestBudget()
    captured = []

    def make_agent(mode):
        captured.append(current_arc_budget())

        class Agent:
            def run(self, rewritten):
                raise RuntimeError("synthetic run failure")

        return Agent()

    monkeypatch.setattr(runtime, "build_agent", make_agent)
    with bind_arc_budget((parent, 2)):
        for mode in ("report", "style", "report"):
            with pytest.raises(RuntimeError, match="synthetic run failure"):
                runtime.run_data_agent("測試", mode=mode)
            assert current_arc_budget() == (parent, 2)
    assert captured[1] is None
    assert captured[0][0] is not captured[2][0]
    for scope in (captured[0], captured[2]):
        assert not scope[0].reserve(1, ArcUnits(slices=1))
    assert parent.snapshot()[0] == ArcUnits()
    assert current_arc_budget() is None


def test_arc_bilingual_mode_alone_allocates_report_budget(monkeypatch):
    from agent.es.arc_request_budget import ArcUnits, current_arc_budget
    monkeypatch.delenv("SRAF_ARC_GROUP_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    scopes = []

    def make_agent(mode):
        scopes.append(current_arc_budget())

        class Agent:
            def run(self, rewritten):
                return {"payload": {}}

        return Agent()

    monkeypatch.setattr(runtime, "build_agent", make_agent)
    runtime.run_data_agent("測試", mode="report")
    runtime.run_data_agent("測試", mode="style")
    assert scopes[0] is not None and scopes[0][1] == 1
    assert scopes[1] is None
    assert not scopes[0][0].reserve(1, ArcUnits(llm_calls=1))
    assert current_arc_budget() is None
