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
