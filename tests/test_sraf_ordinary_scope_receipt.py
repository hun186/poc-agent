"""Real tool/SDK boundary capture with synthetic ES responses and no network."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from elasticsearch import Elasticsearch

from agent.es import es_client
from agent.es.ordinary_scope_receipt import (
    OrdinaryScopeCapture, bind_ordinary_scope_capture, current_ordinary_scope_capture,
)
from agent.tools_es.common import bind_requirement_acceptance
from agent.tools_es import search_news
from api.services import turn_execution


@pytest.fixture
def transport(monkeypatch):
    client = Elasticsearch("http://127.0.0.1:9200")
    calls = []
    def search(self, **kwargs):
        calls.append(kwargs)
        return {"hits": {"hits": []}}
    monkeypatch.setattr(Elasticsearch, "search", search)
    monkeypatch.setattr(es_client, "get_es", lambda: client)
    monkeypatch.setattr(search_news, "resolve_index", lambda _: "news_test")
    monkeypatch.setattr(search_news, "compute_effective_terms",
                        lambda _: (["聯合國"], {}, False, [], ["聯合國"], [{"聯合國"}]))
    yield client, calls
    client.close()


def invoke(tool, **kwargs):
    return tool.forward(query="聯合國", date_from="2023-08-01", date_to="2023-08-31",
                        **kwargs)


def test_real_tool_thread_and_actual_transport_scope(transport):
    _, calls = transport
    capture = OrdinaryScopeCapture()
    with bind_ordinary_scope_capture(capture):
        tool = bind_requirement_acceptance(search_news.ESSearchNews())
    assert current_ordinary_scope_capture() is None
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(invoke, tool).result(timeout=5)
        assert executor.submit(current_ordinary_scope_capture).result(timeout=5) is None
    receipt = capture.seal()
    assert receipt is not None
    assert receipt.indexes == ("news_test",)
    assert (receipt.date_from, receipt.date_to) == ("2023-08-01", "2023-08-31")
    assert receipt.core_terms == ("聯合國",)
    assert len(calls) == 1
    assert "ordinary_scope" not in result
    assert "news_test" not in repr(receipt)
    assert capture.seal() is None


@pytest.mark.parametrize("mode", ["multiple", "selected", "mock", "different_index", "no_transport"])
def test_ambiguous_or_unverified_scope_has_no_receipt(transport, monkeypatch, mode):
    client, calls = transport
    if mode == "mock":
        monkeypatch.setattr(es_client, "get_es", lambda: SimpleNamespace(
            search=lambda **kw: {"hits": {"hits": []}}))
    if mode == "different_index":
        monkeypatch.setattr(es_client, "_requirement_acceptance_index", lambda: "other_index")
    if mode == "no_transport":
        monkeypatch.setattr(search_news, "_safe_es_search", lambda *a, **k: {"hits": {"hits": []}})
    capture = OrdinaryScopeCapture()
    with bind_ordinary_scope_capture(capture):
        tool = bind_requirement_acceptance(search_news.ESSearchNews())
    invoke(tool, must_selected=(mode == "selected"))
    if mode == "multiple":
        invoke(tool)
    assert capture.seal() is None


def test_turn_receipt_is_private_and_opt_in(transport, monkeypatch):
    saved = []
    monkeypatch.setattr(turn_execution, "get_sessions", lambda: {})
    monkeypatch.setattr(turn_execution, "get_last_structured", lambda: {})
    monkeypatch.setattr(turn_execution, "get_memory", lambda: {})
    monkeypatch.setattr(turn_execution, "save_structured_snapshot",
                        lambda *args: saved.append(args[-1]))
    def route(**kwargs):
        tool = bind_requirement_acceptance(search_news.ESSearchNews())
        invoke(tool)
        return {"mode": "SRA_REPORT", "answer": "synthetic",
                "query_meta": {"date_from": "1900-01-01"}}
    monkeypatch.setattr(turn_execution, "answer_with_routing", route)
    payload = SimpleNamespace(messages=[SimpleNamespace(role="user", content="synthetic")])
    turn = turn_execution.execute_agent_turn(payload=payload, session_id="synthetic",
                                             request_id="synthetic", trace={},
                                             capture_ordinary_scope=True)
    assert turn.ordinary_scope.date_from == "2023-08-01"
    assert turn.output["query_meta"]["date_from"] == "1900-01-01"
    assert "ordinary_scope" not in turn.output and "ordinary_scope" not in turn.trace
    assert saved[-1] is turn.output
    assert current_ordinary_scope_capture() is None
    assert turn_execution.execute_agent_turn(
        payload=payload, session_id="synthetic", request_id="synthetic", trace={},
    ).ordinary_scope is None
    payload.messages.insert(0, SimpleNamespace(role="user", content="previous"))
    assert turn_execution.execute_agent_turn(
        payload=payload, session_id="synthetic", request_id="synthetic", trace={},
        capture_ordinary_scope=True,
    ).ordinary_scope is None
