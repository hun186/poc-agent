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
    import json
    def canonical(filters):
        return sorted(json.dumps(f, sort_keys=True) for f in filters)
    assert canonical(extra["body"]["query"]["bool"]["filter"]) == canonical(
        body["query"]["function_score"]["query"]["bool"]["filter"])
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


@pytest.mark.parametrize("high,selected", [(False, False), (True, False), (False, True), (True, True)])
def test_native_frequency_all_supported_filter_combinations(monkeypatch, high, selected):
    from agent.es.arc_frequency_shadow import _primary_scope_verified
    from agent.es.arc_frequency_plan import build_frequency_plan
    from agent.es.query_body import build_main_query_body
    monkeypatch.setenv("SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX", "news_test")
    plan = build_frequency_plan([{"甲"}], date_from="2020-01-01", date_to="2020-12-31",
                                must_high_value=high, must_selected=selected)
    body = build_main_query_body("甲", high, selected, 5, "2020-01-01", "2020-12-31",
                                 6.0, 2.5, False, "importDT", "30d")
    assert _primary_scope_verified("news_test", body, _native_primary(), plan)
    query = body["query"]["function_score"]["query"]["bool"]
    query["filter"].reverse()
    assert _primary_scope_verified("news_test", body, _native_primary(), plan)
    query["filter"].append(query["filter"][0])
    assert not _primary_scope_verified("news_test", body, _native_primary(), plan)
    query["filter"].pop()
    query["must_not"] = [{"term": {"owner": "PRIVATE_OWNER"}}]
    assert not _primary_scope_verified("news_test", body, _native_primary(), plan)


def _bilingual_logs(caplog):
    import json
    prefix = "SRAF_ARC_BILINGUAL="
    return [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]


def test_arc_bilingual_shadow_does_not_change_search_or_evidence(monkeypatch, caplog):
    from agent.es import arc_bilingual_shadow as shadow
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.tools_es.question_scope import bind_original_report_question
    import json

    _prepare(monkeypatch, responder=lambda body, *, index: _response(with_hits=True))
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_BILINGUAL", raising=False)
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    calls = []

    def proposal(payload, **kwargs):
        calls.append((json.loads(payload), kwargs))
        return '[["PRIVATE_ALIAS"]]'

    monkeypatch.setattr(shadow, "call_llm", proposal)
    tool = search_module.ESSearchNews.forward.__wrapped__
    with bind_original_report_question("PRIVATE_ORIGINAL"):
        baseline = tool(object(), query="SECRET_QUERY", size=5)
        assert calls == []
        monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
        budget = ArcRequestBudget()
        with bind_arc_budget((budget, 1)):
            for _ in range(2):
                assert tool(object(), query="SECRET_QUERY", size=5) == baseline
    assert len(calls) == 1
    assert calls[0][0] == {"query": "PRIVATE_ORIGINAL",
                           "groups": [["SECRET_CORE", "SECRET_SYN"]]}
    assert calls[0][1]["timeout"] == 15
    assert calls[0][1]["extra_params"]["options"]["num_predict"] == 1536
    assert budget.snapshot()[0] == ArcUnits(llm_calls=1)
    records = _bilingual_logs(caplog)
    assert records[0]["groups"] == [{"group_ordinal": 1, "original_count": 2,
                                     "candidate_added_count": 1}]
    assert records[1]["status"] == "shared_budget_exhausted"
    assert all(s not in caplog.text for s in ("PRIVATE_ORIGINAL", "PRIVATE_ALIAS",
                                               "SECRET_CORE", "SECRET_SYN"))


@pytest.mark.parametrize("case", ["off", "no_budget", "no_original", "manual",
                                  "capture", "acceptance", "no_provider"])
def test_arc_bilingual_shadow_denies_unsupported_scope(monkeypatch, caplog, case):
    from contextlib import nullcontext
    from agent.es import arc_bilingual_shadow as shadow
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es.ordinary_scope_receipt import OrdinaryScopeCapture, bind_ordinary_scope_capture
    import agent.external_capabilities as capabilities

    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    monkeypatch.setattr(capabilities, "requirement_acceptance_active", lambda: case == "acceptance")
    if case == "off":
        monkeypatch.delenv("SRAF_ARC_BILINGUAL")
    elif case == "no_provider":
        monkeypatch.delenv("TOPIC_LLM_URL")
    calls = []
    monkeypatch.setattr(shadow, "call_llm", lambda *a, **kw: calls.append(1))
    budget = ArcRequestBudget()
    capture = bind_ordinary_scope_capture(OrdinaryScopeCapture()) if case == "capture" else nullcontext()
    with capture, bind_arc_budget(None if case == "no_budget" else (budget, 1)):
        shadow.observe_bilingual_proposal(
            original_question=None if case == "no_original" else "PRIVATE_QUERY",
            groups=[{"PRIVATE_TERM"}], manual=case == "manual")
    assert calls == []
    assert budget.snapshot()[0] == ArcUnits()
    assert len(_bilingual_logs(caplog)) == (0 if case == "off" else 1)
    assert "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("raw,expected", [
    ("PRIVATE_INVALID", "invalid_proposal"),
    (RuntimeError("PRIVATE_BACKEND"), "unavailable"),
    ("[[]]", "observed_candidates"),
])
def test_arc_bilingual_shadow_failure_is_count_only_and_not_refunded(monkeypatch, caplog, raw, expected):
    from agent.es import arc_bilingual_shadow as shadow
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_BILINGUAL", "shadow")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://unused.invalid")
    calls = []

    def provider(*args, **kwargs):
        calls.append(1)
        if isinstance(raw, Exception):
            raise raw
        return raw

    monkeypatch.setattr(shadow, "call_llm", provider)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        for _ in range(2):
            assert shadow.observe_bilingual_proposal(
                original_question="PRIVATE_QUERY", groups=[{"PRIVATE_TERM"}],
                manual=False) is None
    assert calls == [1]
    assert budget.snapshot()[0] == ArcUnits(llm_calls=1)
    records = _bilingual_logs(caplog)
    assert records[0]["status"] == expected
    assert records[1]["status"] == "shared_budget_exhausted"
    assert "PRIVATE_" not in caplog.text


def test_arc_native_rank_receipt_from_verified_transport_only(monkeypatch, caplog):
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    client, es_client = _native_setup(monkeypatch)
    sink = []
    with bind_arc_budget((ArcRequestBudget(), 1)):
        assert es_client.safe_search(_native_body(), index="news_test",
                    arc_frequency={**_native_args(), "receipt_sink": sink}) is client.primary
    assert len(sink) == 1
    receipt = sink[0]
    assert receipt.eligible_documents == 100 and receipt.document_frequencies == (12,)
    assert "PRIVATE_TERM" not in repr(receipt)
    sink.clear()
    client.frequency["timed_out"] = True
    with bind_arc_budget((ArcRequestBudget(), 1)):
        es_client.safe_search(_native_body(), index="news_test",
                    arc_frequency={**_native_args(), "receipt_sink": sink})
    assert sink == []


def test_arc_native_rank_receipt_consumed_only_on_first_refill_build(monkeypatch):
    from agent.es.arc_native_rank_receipt import NativeRankFrequency
    monkeypatch.setenv("SRAF_ARC_ES_FREQUENCY", "shadow")
    monkeypatch.setenv("SRAF_ARC_RANK_NATIVE", "shadow")
    monkeypatch.delenv("SRAF_ARC_BILINGUAL", raising=False)
    receipt = NativeRankFrequency((frozenset({"SECRET_CORE", "SECRET_SYN"}),),
                                  "2020-01-01", "2020-12-31", 100, (12,))
    primary = _native_primary("SECRET_INDEX")
    calls = []

    def search(body, *, index, arc_frequency=None):
        assert arc_frequency is not None
        arc_frequency["receipt_sink"].append(receipt)
        return primary

    _prepare(monkeypatch, responder=search)

    def build(hits, **kw):
        calls.append(kw.get("native_rank_frequency"))
        return [], [], 0

    def refill(**kw):
        builder = kw["build_evidence"]
        hits = primary["hits"]["hits"]
        builder(hits[:])
        builder(hits[:] + hits[:])
        return [], [], 0, {"incomplete_due_to_scan_limit": False}

    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    monkeypatch.setattr(search_module, "refill_date_filtered_evidence", refill)
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="SECRET_QUERY", size=5,
        date_from="2020-01-01", date_to="2020-12-31")
    assert calls == [receipt, None]
    assert "native_rank_frequency" not in repr(result)


def test_arc_a5_pressure_consumed_only_on_first_refill_build(monkeypatch):
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    monkeypatch.setenv("SRAF_ARC_TIGHTEN", "shadow")
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_BILINGUAL", raising=False)
    primary = _native_primary("SECRET_INDEX")
    primary["hits"]["total"] = {"value": 10000, "relation": "gte"}
    calls = []
    _prepare(monkeypatch, responder=lambda body, *, index: primary)

    def build(hits, **kw):
        calls.append(kw.get("arc_candidate_pressure"))
        return [], [], 0

    def refill(**kw):
        builder = kw["build_evidence"]
        hits = primary["hits"]["hits"]
        builder(hits[:])
        builder(hits[:] + hits[:])
        return [], [], 0, {"incomplete_due_to_scan_limit": False}

    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    monkeypatch.setattr(search_module, "refill_date_filtered_evidence", refill)
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="SECRET_QUERY", size=5,
        date_from="2020-01-01", date_to="2020-12-31")
    assert calls == [CandidatePressure("gte", 10000, 1), None]
    assert "arc_candidate_pressure" not in repr(result)


def test_arc_a5_no_date_fallback_does_not_reuse_primary_pressure(monkeypatch):
    monkeypatch.setenv("SRAF_ARC_TIGHTEN", "shadow")
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_BILINGUAL", raising=False)
    calls = []
    responses = iter([_response(with_hits=False), _response(with_hits=True)])
    _prepare(monkeypatch, responder=lambda body, *, index: next(responses))
    def build(hits, **kw):
        calls.append(kw.get("arc_candidate_pressure"))
        return [], [], 0
    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    search_module.ESSearchNews.forward.__wrapped__(object(), query="SECRET_QUERY", size=5)
    assert calls == [None]


def test_arc_a6_exact_empty_primary_logged_without_requery(monkeypatch, caplog):
    import json
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_RELAX", "shadow")
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_BILINGUAL", raising=False)
    response = _native_primary("SECRET_INDEX")
    response["hits"] = {"total": {"value": 0, "relation": "eq"}, "hits": []}
    calls = []
    def search(body, *, index):
        calls.append(body)
        return response
    _prepare(monkeypatch, responder=search)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        result = search_module.ESSearchNews.forward.__wrapped__(
            object(), query="SECRET_QUERY", size=5,
            date_from="2020-01-01", date_to="2020-12-31")
    assert len(calls) == 1 and result["hits"] == []
    assert result["query_meta"]["note"] == "0_hits_with_date_filter"
    prefix = "SRAF_ARC_RELAX_SHADOW="
    rows = [json.loads(r.getMessage().split(prefix, 1)[1])
            for r in caplog.records if r.getMessage().startswith(prefix)]
    assert len(rows) == 1 and rows[0]["status"] == "primary_exact_zero"
    assert budget.snapshot()[0] == ArcUnits()
    assert "SECRET_QUERY" not in caplog.text and "SECRET_INDEX" not in caplog.text


def test_arc_a7_receives_final_result_and_only_first_primary_diagnostics(monkeypatch):
    monkeypatch.setenv("SRAF_ARC_STRATEGY", "shadow")
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_BILINGUAL", raising=False)
    primary = _native_primary("SECRET_INDEX")
    primary["hits"]["total"] = {"value": 100, "relation": "eq"}
    _prepare(monkeypatch, responder=lambda body, *, index: primary)
    calls = []
    sinks = []

    def build(hits, **kw):
        sink = kw.get("arc_strategy_diagnostics")
        sinks.append(sink)
        if sink is not None:
            sink["low"] = {"strict_count": 1}
        return [], [], 0

    def refill(**kw):
        builder = kw["build_evidence"]
        hits = primary["hits"]["hits"]
        builder(hits[:])
        builder(hits[:] + hits[:])
        return [], [{"weak_evidence": False}] * 3, 0, {
            "pages_fetched": 2, "incomplete_due_to_scan_limit": False}

    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    monkeypatch.setattr(search_module, "refill_date_filtered_evidence", refill)
    monkeypatch.setattr(search_module, "observe_strategy", lambda **kw: calls.append(kw))
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="SECRET_QUERY", size=5,
        date_from="2020-01-01", date_to="2020-12-31")
    assert len(calls) == 1 and sinks[1] is None
    assert calls[0]["diagnostics"] == {"low": {"strict_count": 1}}
    assert calls[0]["final_count"] == calls[0]["strong_count"] == 3
    assert calls[0]["refill"]["pages_fetched"] == 2
    assert "arc_strategy_diagnostics" not in repr(result)


def test_arc_a8_scope_binds_real_primary_only(monkeypatch):
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    client, es_client = _native_setup(monkeypatch)
    monkeypatch.setenv("SRAF_ARC_REVIEW_SCOPE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    body = _native_body()
    sink = []
    with bind_arc_budget((ArcRequestBudget(), 1)):
        # FakeClient is not the exact configured Elasticsearch client type.
        assert es_client.safe_search(body, index="news_test",
                                     arc_review_receipts=sink) is client.primary
        assert sink == []
        monkeypatch.setattr(es_client, "Elasticsearch", type(client))
        assert es_client.safe_search(body, index="news_test",
                                     arc_review_receipts=sink) is client.primary
        assert len(sink) == 1
        assert sink[0].body is body and sink[0].response is client.primary
        assert "PRIVATE_DOC" not in repr(sink[0])
        for change in ("partial", "truncated", "wrong_index"):
            primary = _native_primary()
            if change == "partial":
                primary["_shards"]["failed"] = 1
            elif change == "truncated":
                primary["hits"]["total"]["value"] = 5
            else:
                primary["hits"]["hits"][0]["_index"] = "other"
            client.primary = primary
            denied = []
            es_client.safe_search(body, index="news_test", arc_review_receipts=denied)
            assert denied == []


def test_arc_a8_final_scope_excludes_unretained_and_unlinked_rows(monkeypatch, caplog):
    import json
    from agent.es.arc_review_scope import capture_primary_review, make_final_review_input
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.tools_es.date_refill import refill_date_filtered_evidence
    monkeypatch.setenv("SRAF_ARC_REVIEW_SCOPE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    primary = _native_primary()
    primary["hits"]["hits"] = [{"_index":"news_test","_id":str(i)} for i in range(3)]
    primary["hits"]["total"]["value"] = 3
    body = {"size": 3}
    origin = "__sraf_source_hit_ordinal"
    docs = [{"uuid": "PRIVATE_UUID", origin: i} for i in range(3)]
    def row(i, text, **overrides):
        return dict({origin: i, "uuid": "PRIVATE_UUID", "text": text,
                     "match_policy": "strict", "match_scope": "text",
                     "structured_time_context": True,
                     "matched_event_time_candidates": [{"time_iso": "2020-01-01"}]},
                    **overrides)
    rows = [row(0, "PRIVATE_KEEP"), row(0, "PRIVATE_LEGACY", structured_time_context=False),
            row(1, "PRIVATE_OTHER"), row(2, "PRIVATE_DROPPED")]
    budget = ArcRequestBudget()
    sink = []
    with bind_arc_budget((budget, 1)):
        capture_primary_review(index="news_test", body=body, response=primary,
                               real_client=True, sink=sink)
        scope = make_final_review_input(sink[0], question="PRIVATE_QUESTION",
                                        groups=[{"PRIVATE_TERM"}], date_from="2020-01-01",
                                        date_to="2020-12-31", manual=False)
        args = dict(body=body, first_response=primary, requested_size=2,
                    search_next=lambda _: pytest.fail("unexpected ES refill"),
                    build_evidence=lambda _: (docs, rows, 0))
        baseline = refill_date_filtered_evidence(**args)
        observed = refill_date_filtered_evidence(**args, arc_review_scope=scope)
    assert observed == baseline
    assert [r["text"] for r in observed[1]] == [
        "PRIVATE_KEEP", "PRIVATE_LEGACY", "PRIVATE_OTHER"]
    assert all(origin not in r for r in observed[1])
    records = [json.loads(r.getMessage().split("SRAF_ARC_REVIEW_SCOPE=", 1)[1])
               for r in caplog.records if r.getMessage().startswith("SRAF_ARC_REVIEW_SCOPE=")]
    assert records == [{"schema":"sraf_arc_final_review_scope_v1",
                       "status":"bound_local_batch","batch_count":2,
                       "prefix_count":3,"prefix_limited":False,"skipped_rows":1}]
    assert budget.snapshot()[0] == ArcUnits(slices=1,hits=128,rows=64,chars=96000)
    assert "PRIVATE_" not in caplog.text


def test_arc_a8_final_scope_rejects_cross_response_and_more_pages(monkeypatch):
    from agent.es.arc_review_scope import capture_primary_review, make_final_review_input, prepare_final_review
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    monkeypatch.setenv("SRAF_ARC_REVIEW_SCOPE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    primary = _native_primary()
    raw = primary["hits"]["hits"]
    body = {"size": 1}
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        sink = []
        capture_primary_review(index="news_test", body=body, response=primary,
                               real_client=True, sink=sink)
        scope = make_final_review_input(sink[0], question="PRIVATE_QUESTION",
                                        groups=[{"PRIVATE_TERM"}], date_from="2020-01-01",
                                        date_to="2020-12-31", manual=False)
        base = dict(body=body, first_response=primary, raw=raw,
                    selected=[{"__sraf_source_hit_ordinal":0}],
                    selected_evidence=[{"__sraf_source_hit_ordinal":0}],
                    meta={"pages_fetched":1,"incomplete_due_to_scan_limit":False})
        for changes in ({"first_response":dict(primary)}, {"body":dict(body)},
                        {"raw":[dict(raw[0])]},
                        {"meta":{"pages_fetched":2,"incomplete_due_to_scan_limit":False}},
                        {"meta":{"pages_fetched":1,"incomplete_due_to_scan_limit":True}},
                        {"selected":[{"__sraf_source_hit_ordinal":1}]}):
            assert prepare_final_review(scope, **{**base, **changes}) is None
    assert budget.snapshot()[0] == ArcUnits()


def test_arc_priority_defers_optional_llm_until_final_selection(monkeypatch):
    from agent.es.evidence_core.arc_tighten_shadow import CandidatePressure
    monkeypatch.setenv("SRAF_ARC_LLM_PRIORITY", "shadow")
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_REVIEW_SCOPE", raising=False)
    monkeypatch.delenv("SRAF_ARC_STRATEGY", raising=False)
    primary = _native_primary("SECRET_INDEX")
    primary["hits"]["total"] = {"value": 100, "relation": "eq"}
    calls = []
    _prepare(monkeypatch, responder=lambda body, *, index: primary)

    def build(hits, **kw):
        calls.append("build")
        sink = kw.get("arc_strategy_diagnostics")
        assert sink is not None
        sink["low"] = {"strict_count": 1}
        return [], [], 0

    def refill(**kw):
        kw["build_evidence"](primary["hits"]["hits"])
        calls.append("refill_completed")
        return [], [{"weak_evidence": False}] * 3, 0, {
            "pages_fetched": 1, "incomplete_due_to_scan_limit": False}

    def allocate(**kw):
        calls.append("allocate")
        assert kw["pressure"] == CandidatePressure("eq", 100, 1)
        assert kw["diagnostics"] == {"low": {"strict_count": 1}}
        assert kw["final_count"] == kw["strong_count"] == 3

    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    monkeypatch.setattr(search_module, "refill_date_filtered_evidence", refill)
    monkeypatch.setattr(search_module, "observe_allocated_llm", allocate)
    monkeypatch.setattr(search_module, "observe_bilingual_proposal",
                        lambda **kw: pytest.fail("early bilingual call"))
    monkeypatch.setattr(search_module, "observe_strategy",
                        lambda **kw: pytest.fail("separate strategy call"))
    result = search_module.ESSearchNews.forward.__wrapped__(
        object(), query="SECRET_QUERY", size=5,
        date_from="2020-01-01", date_to="2020-12-31")
    assert calls == ["build", "refill_completed", "allocate"]
    assert len(result["evidence_snippets"]) == 3
    assert "arc_strategy_diagnostics" not in repr(result)


def test_arc_priority_default_off_preserves_existing_early_bilingual(monkeypatch):
    monkeypatch.delenv("SRAF_ARC_LLM_PRIORITY", raising=False)
    monkeypatch.delenv("SRAF_ARC_ES_FREQUENCY", raising=False)
    monkeypatch.delenv("SRAF_ARC_REVIEW_SCOPE", raising=False)
    monkeypatch.delenv("SRAF_ARC_STRATEGY", raising=False)
    primary = _native_primary("SECRET_INDEX")
    calls = []
    _prepare(monkeypatch, responder=lambda body, *, index: primary)
    monkeypatch.setattr(search_module, "observe_bilingual_proposal",
                        lambda **kw: calls.append("bilingual"))
    monkeypatch.setattr(search_module, "observe_allocated_llm",
                        lambda **kw: pytest.fail("priority default must be off"))
    def build(hits, **kwargs):
        calls.append("build")
        return [], [], 0
    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    search_module.ESSearchNews.forward.__wrapped__(object(), query="SECRET_QUERY", size=5)
    assert calls == ["bilingual", "build"]


@pytest.mark.parametrize("enabled", [True, False])
def test_ordinary_resource_measurement_report_and_worker_adapter_scope(monkeypatch, caplog, enabled):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from agent import report_agent
    from agent.arc_ordinary_resource_metrics import current_measurement
    from agent.es import es_client
    from agent.llm_utils.ollama_client import LLMClient
    from agent.data_agent.diagnostics import observe_data_agent_model
    from agent.tools_es.common import bind_requirement_acceptance, propagate_requirement_acceptance
    monkeypatch.setenv("SRAF_ARC_ORDINARY_RESOURCE_METRICS", "shadow" if enabled else "off")
    monkeypatch.setattr(es_client,"_requirement_acceptance_index",lambda:None)
    class ES:
        def search(self,**kwargs):
            return {"hits":{"hits":[]}}
    monkeypatch.setattr(es_client,"get_es",lambda:ES())
    class Reply:
        def raise_for_status(self):
            pass
        def json(self):
            return {"done":True,"message":{"content":"PRIVATE_ANSWER"},
                    "response":"PRIVATE_ANSWER","prompt_eval_count":11,"eval_count":3}
    import requests
    monkeypatch.setattr(requests,"post",lambda *a,**kw:Reply())
    llm=LLMClient(base_url="https://private.invalid",model="PRIVATE_MODEL")
    class Model:
        def generate(self,*a,**kw):
            return "PRIVATE_MODEL_RESPONSE"
    model=observe_data_agent_model(Model())
    workers=[]
    class Tool:
        @propagate_requirement_acceptance
        def forward(self):
            es_client.safe_search({"query":{"match_all":{}}},index="PRIVATE_INDEX")
            llm.chat([{"role":"user","content":"PRIVATE_TOOL"}])
            return {}
    def refine(question,**kw):
        llm.generate(question)
        return question
    def retrieve(*a,**kw):
        tool=bind_requirement_acceptance(Tool())
        workers.append(tool)
        model.generate("PRIVATE")
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(tool.forward).result()=={}
            assert pool.submit(current_measurement).result() is None
        return {}
    def synthesize(*a,**kw):
        assert llm.chat([{"role":"user","content":"PRIVATE_SYNTHESIS"}])=="PRIVATE_ANSWER"
        return {"answer":"PRIVATE_ANSWER"}
    monkeypatch.setattr(report_agent,"refine_question_for_data_agent",refine)
    monkeypatch.setattr(report_agent,"run_data_agent",retrieve)
    monkeypatch.setattr(report_agent,"_generate_report_from_payload",synthesize)
    assert report_agent.ask_with_report("PRIVATE_QUESTION")=={"answer":"PRIVATE_ANSWER"}
    assert current_measurement() is None
    # Late invocation on a stale tool must not amend the sealed report.
    workers[0].forward()
    logs=[json.loads(x.getMessage().split("SRAF_ARC_ORDINARY_RESOURCE=",1)[1])
          for x in caplog.records if x.getMessage().startswith("SRAF_ARC_ORDINARY_RESOURCE=")]
    if not enabled:
        assert not logs
        return
    assert len(logs)==1
    record=logs[0]
    assert record["outcome"]=="returned" and record["elapsed_ms"]>=0
    assert record["adapter_attempts"]=={"es_search":1,"es_highlight_retry":0,
        "es_optional_frequency":0,"ollama_chat":2,"ollama_generate":1,"data_agent_generate":1}
    assert record["ollama_reported_usage"]=={
        "prompt_eval_count":{"known_attempts":3,"observed_sum":33},
        "eval_count":{"known_attempts":3,"observed_sum":9}}
    assert record["complete_transport_totals"] is False
    assert "PRIVATE" not in repr(record)


def test_ordinary_resource_measurement_failed_and_unknown_usage(monkeypatch,caplog):
    import json
    import requests
    from agent.arc_ordinary_resource_metrics import measure_ordinary_report,current_measurement
    from agent.llm_utils.ollama_client import LLMClient
    monkeypatch.setenv("SRAF_ARC_ORDINARY_RESOURCE_METRICS","shadow")
    class Reply:
        def raise_for_status(self):
            pass
        def json(self):
            return {"done":True,"response":"PRIVATE","prompt_eval_count":True,"eval_count":-1}
    calls=[]
    def post(*a,**kw):
        calls.append(1)
        if len(calls)==2:
            raise requests.Timeout("PRIVATE_TIMEOUT")
        return Reply()
    monkeypatch.setattr(requests,"post",post)
    llm=LLMClient(base_url="https://private.invalid")
    @measure_ordinary_report
    def report():
        assert llm.generate("PRIVATE")=="PRIVATE"
        llm.generate("PRIVATE")
    with pytest.raises(requests.Timeout):
        report()
    assert current_measurement() is None
    row=next(json.loads(x.getMessage().split("SRAF_ARC_ORDINARY_RESOURCE=",1)[1])
          for x in caplog.records if x.getMessage().startswith("SRAF_ARC_ORDINARY_RESOURCE="))
    assert row["outcome"]=="raised"
    assert row["adapter_attempts"]["ollama_generate"]==2
    assert all(v=={"known_attempts":0,"observed_sum":None} for v in row["ollama_reported_usage"].values())
    assert "PRIVATE" not in repr(row)


@pytest.mark.parametrize("scenario", ["allow", "deny", "revoke", "expired", "absent", "off", "no_ambiguity", "small"])
def test_arc_a8_explicit_ordinary_policy_at_actual_final_refill(monkeypatch, caplog, scenario):
    import json
    import time
    from agent.es.arc_review_scope import capture_primary_review, make_final_review_input
    from agent.es.arc_request_budget import ArcRequestBudget, ArcUnits, bind_arc_budget
    from agent.es import arc_semantic_review_transport as transport
    from agent.tools_es.date_refill import refill_date_filtered_evidence

    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_SCOPE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW", "off" if scenario == "off" else "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://private.invalid/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "PRIVATE_MODEL")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE", raising=False)
    monkeypatch.setenv("SRAF_ARC_REVIEW_RESOURCE_METRICS", "off")
    primary = _native_primary()
    primary["hits"]["hits"] = [{"_index": "news_test", "_id": "PRIVATE_ID_" + str(i)}
                                for i in range(5)]
    primary["hits"]["total"]["value"] = 5
    body = {"size": 5}
    origin = "__sraf_source_hit_ordinal"
    docs = [{"uuid": "PRIVATE_UUID", origin: i} for i in range(5)]
    rows = [{origin: i % 4, "uuid": "PRIVATE_UUID", "text": "PRIVATE_ROW_" + str(i),
             "match_policy": "strict",
             "match_scope": "mixed" if i == 0 and scenario != "no_ambiguity" else "text",
             "structured_time_context": True,
             "matched_event_time_candidates": [{"time_iso": "2020-01-01"}]}
            for i in range(39 if scenario == "small" else 40)]
    rows.append({**rows[0], origin: 4, "text": "PRIVATE_UNRETAINED"})
    checks, calls = [], []

    def policy(**kwargs):
        checks.append(kwargs)
        assert kwargs == dict(question="PRIVATE_QUESTION", groups=(frozenset({"PRIVATE_TERM"}),),
                              date_from="2020-01-01", date_to="2020-12-31", index="news_test",
                              source_ids=tuple("PRIVATE_ID_" + str(i) for i in range(4)),
                              endpoint="https://private.invalid/api/chat", model="PRIVATE_MODEL",
                              verify=True)
        return scenario != "deny" and not (scenario == "revoke" and len(checks) == 2)

    def request(approved, batch):
        calls.append(batch.count)
        payload = json.loads(batch.payload)
        assert batch.count == 4 and len(payload["passages"]) == 4
        assert all("PRIVATE_ROW_" in p["text"] for p in payload["passages"])
        assert "PRIVATE_UNRETAINED" not in batch.payload and "PRIVATE_ID_" not in batch.payload
        raw = json.dumps([{"ordinal": i, "verdict": "unrelated"}
                          for i in range(1, batch.count + 1)])
        return transport.summarize_semantic_review(raw, batch)

    monkeypatch.setattr(transport, "_request_review", request)
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)):
        sink = []
        capture_primary_review(index="news_test", body=body, response=primary,
                               real_client=True, sink=sink)
        scope = make_final_review_input(sink[0], question="PRIVATE_QUESTION",
                                        groups=[{"PRIVATE_TERM"}], date_from="2020-01-01",
                                        date_to="2020-12-31", manual=False)
        args = dict(body=body, first_response=primary, requested_size=4,
                    search_next=lambda _: pytest.fail("unexpected ES refill"),
                    build_evidence=lambda _: (docs, rows, 0))
        baseline = refill_date_filtered_evidence(**args)
        observed = refill_date_filtered_evidence(
            **args, arc_review_scope=scope,
            _arc_review_policy=None if scenario == "absent" else policy,
            _arc_review_deadline_monotonic=time.monotonic() + (10 if scenario == "expired" else 300),
        )
    assert observed == baseline
    allowed = scenario in ("allow", "revoke")
    assert calls == ([4] if allowed else [])
    assert len(checks) == (2 if allowed else 1 if scenario == "deny" else 0)
    assert budget.snapshot()[0] == ArcUnits(slices=1, hits=128, rows=64, chars=96000,
                                          llm_calls=int(allowed))
    assert ("observed_verdicts" in caplog.text) == (scenario == "allow")
    if scenario == "revoke":
        assert "authorization_or_deadline_changed" in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("scenario", ["allow", "deny", "absent", "wrong_question", "closed", "revoke"])
def test_arc_ordinary_review_execution_real_tool_thread(monkeypatch, caplog, scenario):
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor
    from agent.es.arc_ordinary_review_execution import (
        ordinary_review_execution, current_review_execution,
    )
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from agent.es.arc_review_scope import capture_primary_review
    from agent.es import arc_semantic_review_transport as transport
    from agent.tools_es.common import bind_requirement_acceptance
    from agent.tools_es.question_scope import bind_original_report_question

    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_SCOPE", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW", "shadow")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://review.invalid/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "PRIVATE_MODEL")
    for key in ("BILINGUAL", "STRATEGY", "LLM_PRIORITY", "REVIEW_RESOURCE_METRICS",
                "GROUP_FREQUENCY", "RANK_NATIVE", "TIGHTEN", "RELAX"):
        monkeypatch.setenv("SRAF_ARC_" + key, "off")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE", raising=False)
    monkeypatch.setattr(search_module, "native_frequency_enabled", lambda: False)
    primary = _native_primary()
    primary["hits"]["hits"] = [{"_index": "news_test", "_id": "PRIVATE_ID_" + str(i)}
                                for i in range(4)]
    primary["hits"]["total"]["value"] = 4
    origin = "__sraf_source_hit_ordinal"
    docs = [{"uuid": "PRIVATE_UUID", origin: i} for i in range(4)]
    rows = [{origin: i % 4, "uuid": "PRIVATE_UUID", "text": "PRIVATE_ROW_" + str(i),
             "match_policy": "strict", "match_scope": "mixed" if i == 0 else "text",
             "structured_time_context": True,
             "matched_event_time_candidates": [{"time_iso": "2020-01-01"}]}
            for i in range(40)]
    def responder(body, *, index, arc_review_receipts=None, **kwargs):
        if arc_review_receipts is not None:
            capture_primary_review(index=index, body=body, response=primary,
                                   real_client=True, sink=arc_review_receipts)
        return primary
    _prepare(monkeypatch, responder=responder)
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "news_test")
    monkeypatch.setattr(search_module, "build_hits_and_evidence", lambda *a, **kw: (docs, rows, 0))
    calls, checks = [], []
    def policy(**kwargs):
        checks.append(kwargs)
        assert kwargs["question"] == "PRIVATE_QUESTION"
        assert kwargs["source_ids"] == tuple("PRIVATE_ID_" + str(i) for i in range(4))
        return scenario != "deny" and not (scenario == "revoke" and len(checks) == 2)
    def request(approved, batch):
        calls.append(batch.count)
        return transport.summarize_semantic_review(json.dumps([
            {"ordinal": i, "verdict": "unrelated"} for i in range(1, batch.count + 1)
        ]), batch)
    monkeypatch.setattr(transport, "_request_review", request)
    kwargs = dict(query="SECRET_QUERY", size=4, date_from="2020-01-01", date_to="2020-12-31")
    with bind_arc_budget((ArcRequestBudget(), 1)), bind_original_report_question("PRIVATE_QUESTION"):
        baseline = bind_requirement_acceptance(search_module.ESSearchNews()).forward(**kwargs)
    with bind_arc_budget((ArcRequestBudget(), 1)), bind_original_report_question("PRIVATE_QUESTION"):
        with ordinary_review_execution(
            question="OTHER" if scenario == "wrong_question" else "PRIVATE_QUESTION",
            policy=None if scenario == "absent" else policy,
            deadline=time.monotonic() + 300,
        ):
            tool = bind_requirement_acceptance(search_module.ESSearchNews())
            if scenario != "closed":
                with ThreadPoolExecutor(max_workers=1) as pool:
                    observed = pool.submit(tool.forward, **kwargs).result()
                    assert pool.submit(current_review_execution).result() is None
        if scenario == "closed":
            with ThreadPoolExecutor(max_workers=1) as pool:
                observed = pool.submit(tool.forward, **kwargs).result()
        assert current_review_execution() is None
    assert observed == baseline
    assert calls == ([4] if scenario in ("allow", "revoke") else [])
    assert len(checks) == (2 if scenario in ("allow", "revoke") else 1 if scenario == "deny" else 0)
    assert "PRIVATE_" not in caplog.text


def test_arc_review_execution_lifetime_denies_during_policy_and_nested_scope():
    import time
    from agent.es.arc_ordinary_review_execution import (
        ordinary_review_execution, current_review_execution, bind_review_execution,
    )
    with ordinary_review_execution(question="q", policy=lambda **kw: scope.close() or True,
                                   deadline=time.monotonic() + 60):
        scope = current_review_execution()
        assert scope.refill_kwargs("wrong") == {}
        with bind_review_execution(None):
            assert current_review_execution() is None
        assert current_review_execution() is scope
        assert scope.authorize(question="q") is False
        assert scope.refill_kwargs("q") == {}
    assert current_review_execution() is None


@pytest.mark.parametrize("scenario", ["allow", "deny", "revoke", "failed", "absent", "expired", "unambiguous"])
def test_arc_priority_coordinates_a8_with_real_a7_observer(monkeypatch, caplog, scenario):
    import json
    import time
    from agent.es.arc_ordinary_review_execution import ordinary_review_execution
    from agent.es.arc_request_budget import ArcRequestBudget, bind_arc_budget
    from agent.es.arc_review_scope import capture_primary_review
    from agent.es import arc_semantic_review_transport as transport, arc_strategy_shadow as a7
    from agent.es import arc_bilingual_shadow as a2
    from agent.tools_es.common import bind_requirement_acceptance
    from agent.tools_es.question_scope import bind_original_report_question

    monkeypatch.setenv("SRAF_ARC_MODE", "shadow")
    for key in ("REVIEW_SCOPE", "REVIEW", "LLM_PRIORITY", "BILINGUAL", "STRATEGY"):
        monkeypatch.setenv("SRAF_ARC_" + key, "shadow")
    for key in ("REVIEW_RESOURCE_METRICS", "GROUP_FREQUENCY", "RANK_NATIVE", "TIGHTEN", "RELAX"):
        monkeypatch.setenv("SRAF_ARC_" + key, "off")
    monkeypatch.setenv("SRAF_ARC_REVIEW_EGRESS", "approved")
    monkeypatch.setenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "news_test")
    monkeypatch.setenv("SRAF_ARC_REVIEW_ENDPOINT", "https://review.invalid/api/chat")
    monkeypatch.setenv("SRAF_ARC_REVIEW_MODEL", "PRIVATE_MODEL")
    monkeypatch.setenv("TOPIC_LLM_URL", "http://topic.invalid")
    monkeypatch.delenv("SRAF_ARC_REVIEW_CA_FILE", raising=False)
    monkeypatch.setattr(search_module, "native_frequency_enabled", lambda: False)
    primary = _native_primary()
    primary["hits"]["hits"] = [{"_index": "news_test", "_id": "PRIVATE_ID_" + str(i)}
                                for i in range(12)]
    primary["hits"]["total"]["value"] = 12
    origin = "__sraf_source_hit_ordinal"
    docs = [{"uuid": "PRIVATE_UUID", origin: i} for i in range(12)]
    rows = [{origin: i % 12, "uuid": "PRIVATE_UUID", "text": "PRIVATE_ROW_" + str(i),
             "match_policy": "strict",
             "match_scope": "mixed" if i == 0 and scenario != "unambiguous" else "text",
             "structured_time_context": True,
             "matched_event_time_candidates": [{"time_iso": "2020-01-01"}]}
            for i in range(40)]

    def responder(body, *, index, arc_review_receipts=None, **kwargs):
        if arc_review_receipts is not None:
            capture_primary_review(index=index, body=body, response=primary,
                                   real_client=True, sink=arc_review_receipts)
        return primary

    _prepare(monkeypatch, responder=responder)
    monkeypatch.setattr(search_module, "resolve_index", lambda _: "news_test")
    def build(*args, **kwargs):
        kwargs["arc_strategy_diagnostics"]["high"] = {
            "schema": "sraf_arc_tighten_shadow_v1", "scope": "strict_parser_prefix_only",
            "status": "observed_tightening", "prefix_limited": False,
            "prefix_count": 40, "strict_count": 40, "strategies": [
                {"strategy": "all_text_axes", "retained_prefix_rows": 25,
                 "retained_source_hits": 8, "sample_floor_met": True},
                {"strategy": "anchor_plus_local_discriminative_axis", "retained_prefix_rows": 30,
                 "retained_source_hits": 10, "sample_floor_met": True}]}
        return docs, rows, 0
    monkeypatch.setattr(search_module, "build_hits_and_evidence", build)
    calls, checks = [], []
    def policy(**kwargs):
        checks.append(1)
        return scenario != "deny" and not (scenario == "revoke" and len(checks) == 2)
    def request(approved, batch):
        calls.append("review")
        if scenario == "failed":
            raise RuntimeError("PRIVATE_FAILURE")
        return transport.summarize_semantic_review(json.dumps([
            {"ordinal": i, "verdict": "unrelated"} for i in range(1, batch.count + 1)
        ]), batch)
    def strategy(*args, **kwargs):
        calls.append("strategy")
        return '{"choice":"keep_original"}'
    monkeypatch.setattr(transport, "_request_review", request)
    monkeypatch.setattr(a7, "call_llm", strategy)
    monkeypatch.setattr(a2, "call_llm", lambda *a, **kw: pytest.fail("unexpected A2"))
    kwargs = dict(query="SECRET_QUERY", size=12, date_from="2020-01-01", date_to="2020-12-31")
    budget = ArcRequestBudget()
    with bind_arc_budget((budget, 1)), bind_original_report_question("PRIVATE_QUESTION"):
        with ordinary_review_execution(
            question="PRIVATE_QUESTION", policy=None if scenario == "absent" else policy,
            deadline=time.monotonic() + (10 if scenario == "expired" else 300),
        ):
            observed = bind_requirement_acceptance(search_module.ESSearchNews()).forward(**kwargs)
    review_selected = scenario in ("allow", "deny", "revoke", "failed")
    expected = [] if scenario == "deny" else ["review"] if review_selected else ["strategy"]
    assert calls == expected
    assert budget.snapshot()[0].llm_calls == len(expected)
    assert len(checks) == (2 if scenario in ("allow", "revoke") else 1 if scenario in ("deny", "failed") else 0)
    assert ('"choice":"semantic_review"' in caplog.text) == review_selected
    assert len(observed["evidence_snippets"]) == 40
    assert "PRIVATE_" not in caplog.text
    assert "review_selection" not in repr(observed)
