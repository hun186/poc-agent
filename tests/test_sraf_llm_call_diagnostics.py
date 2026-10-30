"""Purely synthetic model-call diagnostics; never contacts any LLM endpoint."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import requests

from agent.llm_utils import ollama_client as subject


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.delenv("DEBUG_CALL_LLM", raising=False)
    received = []

    class Client:
        def chat(self, messages, **kwargs):
            received.append((messages, kwargs))
            return "synthetic-answer"

    monkeypatch.setattr(subject, "get_default_client", lambda: Client())
    return received


def test_normal_production_call_logs_only_safe_stage_and_elapsed(fake_client, caplog, capsys):
    secret = "SECRET-PROMPT-never-log"
    with caplog.at_level(logging.INFO, logger=subject.__name__):
        out = subject.call_llm(secret, system_prompt="SYSTEM-SECRET",
                               model="model-private", timeout=12.5, stage="router")
    assert out == "synthetic-answer"
    assert fake_client[0][0][-1]["content"] == secret
    assert fake_client[0][1]["extra_params"]["model"] == "model-private"
    assert fake_client[0][1]["timeout"] == 12.5
    assert "[llm_call] stage=router outcome=success category=none" in caplog.text
    assert "requests_timeout_sec=12.5" in caplog.text
    assert "elapsed_sec=" in caplog.text
    assert capsys.readouterr().out == ""
    for value in (secret, "SYSTEM-SECRET", "model-private", "http://", "Bearer"):
        assert value not in caplog.text


def test_unknown_caller_stage_is_not_logged_verbatim(fake_client, caplog):
    with caplog.at_level(logging.INFO, logger=subject.__name__):
        subject.call_llm("quiet", stage="SECRET-untrusted-stage")
    assert "stage=unspecified" in caplog.text
    assert "SECRET-untrusted-stage" not in caplog.text


@pytest.mark.parametrize("exception,category", [
    (requests.exceptions.ConnectTimeout("URL-SECRET"), "connect_timeout"),
    (requests.exceptions.ReadTimeout("URL-SECRET"), "read_timeout"),
    (requests.exceptions.Timeout("URL-SECRET"), "transport_timeout"),
    (requests.exceptions.ConnectionError("URL-SECRET"), "connection_error"),
    (requests.exceptions.RequestException("URL-SECRET"), "request_error"),
    (ValueError("SECRET-JSON"), "invalid_response"),
    (RuntimeError("SECRET-INTERNAL"), "unexpected_error"),
])
def test_errors_are_stably_categorized_and_never_expose_exceptions(
        monkeypatch, caplog, capsys, exception, category):
    monkeypatch.delenv("DEBUG_CALL_LLM", raising=False)

    class Broken:
        def chat(self, messages, **kwargs):
            raise exception

    monkeypatch.setattr(subject, "get_default_client", lambda: Broken())
    with caplog.at_level(logging.WARNING, logger=subject.__name__):
        with pytest.raises(RuntimeError, match="^llm_runtime_failure$"):
            subject.call_llm("SECRET-REQUEST", stage="query_refiner", timeout=5.0)
    assert f"stage=query_refiner outcome=error category={category}" in caplog.text
    assert "requests_timeout_sec=5.0" in caplog.text
    assert capsys.readouterr().out == ""
    for value in ("URL-SECRET", "SECRET-JSON", "SECRET-INTERNAL", "SECRET-REQUEST"):
        assert value not in caplog.text


@pytest.mark.parametrize("status,category", [
    (429, "http_429"), (503, "http_503"), (500, "http_5xx"),
    (422, "http_4xx"), (302, "http_error"),
])
def test_http_failure_code_is_not_mislabeled_as_proven_queue(status, category):
    response = requests.Response()
    response.status_code = status
    exception = requests.exceptions.HTTPError(
        "Ollama HTTP URL-Bearer-SECRET", response=response)
    assert subject._llm_failure_category(exception) == category
    assert "queue" not in category


@pytest.mark.parametrize("setting,expected", [
    (None, "default"), (0.0, "default"), (-2.0, "default"),
    (float("nan"), "default"), (float("inf"), "default"),
    (12.3456, "12.346"),
])
def test_timeout_label_is_bounded_numeric_or_default(setting, expected):
    assert subject._timeout_label(setting) == expected


def test_slower_call_is_warning_with_no_user_text(monkeypatch, fake_client, caplog):
    clock = iter([100.0, 131.0])
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(clock)))
    with caplog.at_level(logging.INFO, logger=subject.__name__):
        subject.call_llm("SENSITIVE-TEXT", stage="report")
    assert "stage=report outcome=success" in caplog.text
    assert "elapsed_sec=31.000" in caplog.text
    assert any(r.levelno == logging.WARNING and "stage=report" in r.message
               for r in caplog.records)
    assert "SENSITIVE-TEXT" not in caplog.text


def test_e2e_live_failure_keeps_existing_runtime_contract(monkeypatch, caplog):
    from agent import external_capabilities as caps

    class Broken:
        def chat(self, *args, **kwargs):
            raise requests.exceptions.ReadTimeout("SECRET-PROVIDER-URL")

    monkeypatch.setattr(subject, "get_default_client", lambda: Broken())
    monkeypatch.setattr(caps, "requirement_acceptance_active", lambda: True)
    monkeypatch.setattr(caps, "frozen_plan", lambda: SimpleNamespace(llm_backend="live"))
    with caplog.at_level(logging.WARNING, logger=subject.__name__):
        with pytest.raises(RuntimeError, match="^e2e_live_llm_runtime_failure$"):
            subject.call_llm("TEXT", stage="report")
    assert "category=read_timeout" in caplog.text
    assert "SECRET-PROVIDER-URL" not in caplog.text


def test_generate_remains_compatible_with_existing_nonstreaming_payload(monkeypatch):
    received = {}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"response": "legacy-output"}
    def fake_post(url, **kwargs):
        received.update(kwargs)
        return Response()
    monkeypatch.setattr(subject.requests, "post", fake_post)
    client = subject.LLMClient(base_url="http://example.invalid", model="small")
    assert client.generate("prompt", timeout=22.0) == "legacy-output"
    assert received["timeout"] == 22.0
    assert received["json"]["stream"] is False


def test_debug_opt_in_never_previews_prompt_or_system_text(
        monkeypatch, fake_client, caplog, capsys):
    monkeypatch.setenv("DEBUG_CALL_LLM", "1")
    with caplog.at_level(logging.INFO, logger=subject.__name__):
        subject.call_llm("PRIVATE-QUESTION", system_prompt="PRIVATE-SYSTEM",
                         stage="router")
    assert "request_size system_chars=14 user_chars=16" in caplog.text
    assert "PRIVATE-QUESTION" not in caplog.text
    assert "PRIVATE-SYSTEM" not in caplog.text
    assert capsys.readouterr().out == ""


def test_nonstring_stage_fails_safe_without_breaking_call(fake_client, caplog):
    with caplog.at_level(logging.INFO, logger=subject.__name__):
        assert subject.call_llm("text", stage=["secret"]) == "synthetic-answer"
    assert "stage=unspecified" in caplog.text
    assert "secret" not in caplog.text
