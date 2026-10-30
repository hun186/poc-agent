"""DataAgent model generation timing: synthetic only; no network/model calls."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import requests

from agent.data_agent import builder, diagnostics


class SyntheticDataAgentModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def generate(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"role": "assistant", "content": "SENSITIVE-RESPONSE"}


def test_observer_keeps_model_identity_generation_contract_and_redacts(caplog, monkeypatch):
    clock = iter([20.0, 54.0])
    monkeypatch.setattr(diagnostics, "time", SimpleNamespace(perf_counter=lambda: next(clock)))
    obj = SyntheticDataAgentModel()
    assert diagnostics.observe_data_agent_model(obj) is obj
    assert type(obj) is SyntheticDataAgentModel
    with caplog.at_level(logging.INFO, logger=diagnostics.__name__):
        response = obj.generate(
            [{"role": "user", "content": "SENSITIVE-PROMPT"}],
            stop_sequences=["SENSITIVE-STOP"],
            untrusted="SENSITIVE-ARG",
        )
    assert response == {"role": "assistant", "content": "SENSITIVE-RESPONSE"}
    assert obj.calls[0][1]["untrusted"] == "SENSITIVE-ARG"
    assert "stage=data_agent outcome=success category=none elapsed_sec=34.000" in caplog.text
    assert "requests_timeout_sec=unknown" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    for secret in ("SENSITIVE-ARG", "SENSITIVE-STOP", "SENSITIVE-PROMPT", "SENSITIVE-RESPONSE"):
        assert secret not in caplog.text


def test_observer_only_instruments_instance_once(monkeypatch, caplog):
    obj = SyntheticDataAgentModel()
    diagnostics.observe_data_agent_model(obj)
    first = obj.generate
    diagnostics.observe_data_agent_model(obj)
    assert obj.generate is first
    with caplog.at_level(logging.INFO, logger=diagnostics.__name__):
        obj.generate(["hello"])
    assert len([r for r in caplog.records if "stage=data_agent" in r.message]) == 1


def test_exception_is_unchanged_and_model_metadata_never_logged(caplog):
    class Broken:
        def generate(self, *_args, **_kwargs):
            raise requests.exceptions.ReadTimeout("SECRET-TOKEN-at-http://private-host")

    obj = diagnostics.observe_data_agent_model(Broken())
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        with pytest.raises(requests.exceptions.ReadTimeout):
            obj.generate("PRIVATE-PROMPT")
    assert "stage=data_agent outcome=error category=read_timeout" in caplog.text
    for secret in ("SECRET-TOKEN", "private-host", "PRIVATE-PROMPT"):
        assert secret not in caplog.text


def test_wrapped_litellm_timeout_is_categorized_without_exception_text(caplog):
    LiteTimeout = type("Timeout", (Exception,), {"__module__": "litellm.exceptions"})
    class Broken:
        def generate(self, *_args, **_kwargs):
            try:
                raise LiteTimeout("https://token-secret")
            except LiteTimeout as cause:
                raise RuntimeError("SECRET-BODY") from cause

    model = diagnostics.observe_data_agent_model(Broken())
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        with pytest.raises(RuntimeError, match="SECRET-BODY"):
            model.generate("PRIVATE-PROMPT")
    assert "category=provider_timeout" in caplog.text
    for secret in ("SECRET-BODY", "token-secret", "PRIVATE-PROMPT"):
        assert secret not in caplog.text


@pytest.mark.parametrize("name,expected", [
    ("RateLimitError", "provider_rate_limited"),
    ("ServiceUnavailableError", "provider_unavailable"),
    ("APIConnectionError", "provider_connection_error"),
    ("InternalServerError", "provider_error"),
])
def test_known_litellm_failure_class_is_fixed(name, expected):
    Exc = type(name, (Exception,), {"__module__": "litellm.exceptions"})
    assert diagnostics._data_agent_error_category(Exc("SECRET")) == expected


def test_untrusted_exception_type_does_not_leak_name(caplog):
    Untrusted = type("SECRET-ERROR", (Exception,), {"__module__": "randomlib"})
    class Broken:
        def generate(self):
            raise Untrusted("SECRET-MESSAGE")
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        with pytest.raises(Untrusted):
            diagnostics.observe_data_agent_model(Broken()).generate()
    assert "category=provider_error" in caplog.text
    assert "SECRET-ERROR" not in caplog.text
    assert "SECRET-MESSAGE" not in caplog.text


def test_missing_or_readonly_generate_does_not_block_regular_production(caplog):
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        no_generate = object()
        assert diagnostics.observe_data_agent_model(no_generate) is no_generate
        class ReadonlyModel:
            __slots__ = ()
            def generate(self, *_args):
                return "still works"
        obj = ReadonlyModel()
        assert diagnostics.observe_data_agent_model(obj) is obj
        assert obj.generate("x") == "still works"
    assert "category=generate_unavailable" in caplog.text
    assert "category=generate_readonly" in caplog.text


def test_builder_instruments_production_only_and_retains_shared_instance(monkeypatch, caplog):
    monkeypatch.setattr(builder, "LiteLLMModel", SyntheticDataAgentModel)
    monkeypatch.setattr(builder, "_SHARED_MODEL", None)
    with caplog.at_level(logging.INFO, logger=diagnostics.__name__):
        model = builder.build_model()
        assert isinstance(model, SyntheticDataAgentModel)
        assert builder.build_model() is model
        assert model.generate(["example"]) == {"role": "assistant", "content": "SENSITIVE-RESPONSE"}
    assert "stage=data_agent outcome=success" in caplog.text
    assert "SENSITIVE-RESPONSE" not in caplog.text


def test_e2e_semantic_mock_keeps_existing_model_boundary(monkeypatch):
    from agent import external_capabilities as caps
    monkeypatch.setattr(builder, "_SHARED_MODEL", None)
    monkeypatch.setattr(builder, "LiteLLMModel", lambda **kwargs:
                        pytest.fail("offline semantic mock must not instantiate real LLM"))
    monkeypatch.setattr(caps, "requirement_acceptance_active", lambda: True)
    monkeypatch.setattr(caps, "frozen_plan", lambda: SimpleNamespace(llm_backend="semantic_mock"))
    obj = builder.build_model()
    assert type(obj).__name__ == "DeterministicE2ECodeModel"
    assert not getattr(obj.generate, "_sraf_data_agent_observed", False)
