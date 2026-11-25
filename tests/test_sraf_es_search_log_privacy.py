"""#413: regression for stdout/profiler secrecy of the ES search tool.

Only synthetic Elasticsearch responses and stubbed term extraction. These
assertions protect process logs, not the authorized tool return contract.
"""
from __future__ import annotations

import pytest

import agent.tools_es.search_news as search_module


PRIVATE = (
    "SECRET_QUERY", "SECRET_INDEX", "SECRET_DOC_ID",
    "SECRET_CORE", "SECRET_SYN", "SECRET_EVIDENCE",
    "SECRET_SHARDS", "SECRET_BACKEND_ERROR",
)


def _prepare(monkeypatch, *, responder):
    monkeypatch.setenv("ES_TOOLS_DEBUG", "1")
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "SECRET_INDEX")
    monkeypatch.setattr(
        search_module, "compute_effective_terms",
        lambda q: (
            ["SECRET_CORE"], {"SECRET_CORE": ["SECRET_SYN"]},
            False, [], ["SECRET_CORE", "SECRET_SYN"],
            [{"SECRET_CORE", "SECRET_SYN"}],
        ),
    )
    monkeypatch.setattr(search_module, "_safe_es_search", responder)
    monkeypatch.setattr(
        search_module, "build_hits_and_evidence",
        lambda *args, **kw: (
            [{"uuid": "SECRET_DOC_ID"}],
            [{"text": "SECRET_EVIDENCE", "match_policy": "strict"}],
            0,
        ),
    )


def _response(*, with_hits: bool):
    return {
        "hits": {"hits": [
            {"_index": "SECRET_INDEX", "_id": "SECRET_DOC_ID"}
        ] if with_hits else []},
        "_shards": {"failures": ["SECRET_SHARDS"]},
    }


def _assert_redacted(capsys):
    output = capsys.readouterr()
    combined = output.out + output.err
    for secret in PRIVATE:
        assert secret not in combined
    return combined


def test_es_query_and_debug_logs_redact_private_contents(monkeypatch, capsys):
    _prepare(monkeypatch, responder=lambda body, *, index: _response(with_hits=True))
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="SECRET_QUERY", size=5, index_hint="SECRET_INDEX",
    )
    # Authorized tool data may contain private values; logging may not.
    assert result["query_meta"]["query"] == "SECRET_QUERY"
    assert result["hits"][0]["uuid"] == "SECRET_DOC_ID"
    assert result["evidence_snippets"][0]["text"] == "SECRET_EVIDENCE"
    logged = _assert_redacted(capsys)
    assert "snippets_after_filter=1" in logged
    assert "effective_term_count=2" in logged


def test_es_fallback_logs_stay_content_free(monkeypatch, capsys):
    attempts = []

    def fake_es(body, *, index):
        attempts.append(body)
        return _response(with_hits=len(attempts) == 2)

    _prepare(monkeypatch, responder=fake_es)
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="SECRET_QUERY", size=5,
    )
    assert len(attempts) == 2
    assert result["hits"][0]["uuid"] == "SECRET_DOC_ID"
    _assert_redacted(capsys)


@pytest.mark.parametrize("fail_at", [1, 2])
def test_search_error_propagates_without_echoing_raw_backend_error(
    monkeypatch, capsys, fail_at,
):
    attempts = 0

    def fake_es(body, *, index):
        nonlocal attempts
        attempts += 1
        if attempts == fail_at:
            raise RuntimeError("SECRET_BACKEND_ERROR")
        return _response(with_hits=False)

    _prepare(monkeypatch, responder=fake_es)
    # Exercise BadRequestError logging path with a small test double. The
    # original exception must still be propagated, not converted to success.
    monkeypatch.setattr(search_module, "BadRequestError", RuntimeError)
    with pytest.raises(RuntimeError, match="SECRET_BACKEND_ERROR"):
        search_module.ESSearchNews.forward.__wrapped__(
            object(), query="SECRET_QUERY", size=5,
        )
    assert attempts == fail_at
    logged = _assert_redacted(capsys)
    assert "details suppressed" in logged


def test_tool_meta_debug_redacts_but_preserves_authorized_values(monkeypatch, capsys):
    from agent.tools_es.common import build_query_meta

    monkeypatch.setenv("ES_TOOLS_DEBUG", "1")
    meta = build_query_meta(
        raw_query="SECRET_QUERY", es_query="SECRET_QUERY",
        core_terms=["SECRET_CORE"], syn_terms=["SECRET_SYN"],
        effective_terms=["SECRET_CORE"],
        manual_terms_in_q=[], is_manual_entity_query=False,
        term_groups=[{"SECRET_CORE"}], date_from=None, date_to=None,
    )
    assert meta["query"] == "SECRET_QUERY"
    assert meta["core_terms"] == ["SECRET_CORE"]
    assert "content redacted" in _assert_redacted(capsys)



def test_es_tool_passes_only_bound_original_question_to_shadow_builder(
    monkeypatch, capsys,
):
    """One tool instance's original question survives the worker boundary.

    The CodeAgent rewritten query, or a stale prior-tool context, is not an
    authority for a required subject. This is a non-network plumbing test.
    """
    from concurrent.futures import ThreadPoolExecutor

    from agent.tools_es.common import bind_requirement_acceptance
    from agent.tools_es.question_scope import bind_original_report_question

    _prepare(monkeypatch, responder=lambda body, *, index: _response(with_hits=True))
    observed = []

    def capture(_hits, **kwargs):
        observed.append((kwargs.get("original_question"), kwargs["query_for_snippet"]))
        return ([{"uuid": "SECRET_DOC_ID"}], [], 0)

    monkeypatch.setattr(search_module, "build_hits_and_evidence", capture)
    original = "主題：加薩\nSECRET_ORIGINAL_QUESTION"
    with bind_original_report_question(original):
        report_tool = bind_requirement_acceptance(search_module.ESSearchNews())
    with bind_original_report_question(None):
        bare_tool = bind_requirement_acceptance(search_module.ESSearchNews())

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(report_tool.forward, query="SECRET_QUERY", size=5).result()
        executor.submit(bare_tool.forward, query="SECRET_QUERY", size=5).result()

    assert observed == [(original, "SECRET_QUERY"), (None, "SECRET_QUERY")]
    logged = capsys.readouterr()
    assert "SECRET_ORIGINAL_QUESTION" not in logged.out + logged.err
    assert "主題：加薩" not in logged.out + logged.err


def _native_primary(index="news_test"):
    return {
        "timed_out": False,
        "_shards": {"total": 2, "successful": 2, "failed": 0},
        "hits": {"total": {"value": 1, "relation": "eq"},
                 "hits": [{"_index": index, "_id": "PRIVATE_DOC"}]},
    }


def _native_response():
    return {
        "timed_out": False,
        "_shards": {"total": 2, "successful": 2, "failed": 0},
        "hits": {"total": {"value": 100, "relation": "eq"}, "hits": []},
        "aggregations": {"group_frequency": {"buckets": {
            "1": {"doc_count": 12}}}},
    }


def _native_args():
    return dict(groups=[{"PRIVATE_TERM"}], date_from="2020-01-01",
                date_to="2020-12-31", must_high_value=True, must_selected=False)


def _native_body():
    from agent.es.query_body import build_main_query_body
    return build_main_query_body("PRIVATE_QUERY", True, False, 5,
                                "2020-01-01", "2020-12-31",
                                6.0, 2.5, False, "importDT", "30d")


def _native_setup(monkeypatch):
    from agent.es import arc_frequency_shadow as shadow, es_client
    monkeypatch.setenv("SRAF_ARC_ES_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX", "news_test")
    class FakeClient:
        def __init__(self):
            self.calls = []
            self.primary = _native_primary()
            self.frequency = _native_response()
        def options(self, **kwargs):
            self.calls.append(("options", kwargs))
            return self
        def search(self, **kwargs):
            self.calls.append(("search", kwargs))
            if kwargs["body"]["size"] == 0:
                if isinstance(self.frequency, Exception):
                    raise self.frequency
                return self.frequency
            return self.primary
    client = FakeClient()
    monkeypatch.setattr(shadow, "Elasticsearch", FakeClient)
    monkeypatch.setattr(es_client, "get_es", lambda: client)
    monkeypatch.setattr(es_client, "_requirement_acceptance_index", lambda: None)
    return client, es_client


def _native_logs(caplog):
    import json
    prefix = "SRAF_ARC_ES_FREQUENCY="
    return [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]


def test_native_frequency_transport_preserves_primary_and_limits_calls(monkeypatch, caplog):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    client, es_client = _native_setup(monkeypatch)
    budget = ArcRequestBudget()
    body = _native_body()
    with bind_arc_budget((budget, 1)):
        for _ in range(2):
            assert es_client.safe_search(body, index="news_test", arc_frequency=_native_args()) is client.primary
    assert [kind for kind, _ in client.calls] == ["search", "options", "search", "search"]
    assert client.calls[1][1] == dict(request_timeout=3, max_retries=0, retry_on_timeout=False)
    extra = client.calls[2][1]
    assert extra["index"] == "news_test"
    assert extra["allow_partial_search_results"] is False
    assert extra["ignore_unavailable"] is False and extra["allow_no_indices"] is False
    assert extra["expand_wildcards"] == "none"
    assert extra["body"]["_source"] is False and extra["body"]["size"] == 0
    assert extra["body"]["query"]["bool"]["filter"] == body["query"]["function_score"]["query"]["bool"]["filter"]
    assert budget.snapshot()[0] == ArcUnits(es_calls=1)
    records = _native_logs(caplog)
    assert records[0]["observation"]["groups"][0]["document_frequency"] == 12
    assert records[1]["status"] == "shared_budget_exhausted"
    assert all(s not in caplog.text for s in ("PRIVATE_", "news_test", "2020-01-01"))


@pytest.mark.parametrize("case", ["off", "no_budget", "wrong_index", "alias", "empty",
                                  "partial", "extra_filter", "capture", "acceptance"])
def test_native_frequency_denies_unverified_scope(monkeypatch, caplog, case):
    from contextlib import nullcontext
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es.ordinary_scope_receipt import OrdinaryScopeCapture, bind_ordinary_scope_capture
    from agent.es import arc_frequency_shadow
    import agent.external_capabilities as capabilities
    client, _ = _native_setup(monkeypatch)
    budget = ArcRequestBudget()
    index, body = "news_test", _native_body()
    if case == "off":
        monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY")
    elif case == "wrong_index":
        index = "other_index"
    elif case == "alias":
        client.primary = _native_primary("another_concrete_index")
    elif case == "empty":
        client.primary["hits"]["hits"] = []
    elif case == "partial":
        client.primary["_shards"].update(successful=1, failed=1)
    elif case == "extra_filter":
        body["query"]["function_score"]["query"]["bool"]["filter"].append({"term": {"owner": "PRIVATE_OWNER"}})
    elif case == "acceptance":
        monkeypatch.setattr(capabilities, "requirement_acceptance_active", lambda: True)
    capture = bind_ordinary_scope_capture(OrdinaryScopeCapture()) if case == "capture" else nullcontext()
    with capture, bind_arc_budget(None if case == "no_budget" else (budget, 1)):
        arc_frequency_shadow.observe_native_frequency(
            client, index=index, ordinary_body=body, ordinary_response=client.primary, **_native_args())
    assert client.calls == []
    assert budget.snapshot()[0] == ArcUnits()
    assert len(_native_logs(caplog)) == (0 if case == "off" else 1)
    assert "PRIVATE_OWNER" not in caplog.text


def test_native_frequency_failure_does_not_retry_or_modify_primary(monkeypatch, caplog):
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    client, es_client = _native_setup(monkeypatch)
    client.frequency = RuntimeError("PRIVATE_BACKEND")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        assert es_client.safe_search(_native_body(), index="news_test", arc_frequency=_native_args()) is client.primary
    assert [kind for kind, _ in client.calls] == ["search", "options", "search"]
    assert budget.snapshot()[0] == ArcUnits(es_calls=1)
    assert _native_logs(caplog) == [{"schema": "sraf_arc_es_frequency_shadow_v1", "status": "unavailable"}]
    assert "PRIVATE_BACKEND" not in caplog.text
