"""Offline regressions: normal jobs are independent from E2E probes."""
from __future__ import annotations

import pytest
from requests.exceptions import ReadTimeout

from agent.external_capabilities import (
    BackendPlan, CapabilityError, frozen_plan, install_plan,
    requirement_acceptance_scope, reset_plan_for_tests,
)
from agent.utils.evidence_pack import pack_ev_for_llm


@pytest.fixture(autouse=True)
def _isolate_plan():
    reset_plan_for_tests()
    yield
    reset_plan_for_tests()


def test_normal_llm_client_never_starts_live_probe(monkeypatch):
    from agent.llm_utils import ollama_client
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    monkeypatch.setattr(
        "agent.external_capabilities.resolve_environment_plan",
        lambda _: (_ for _ in ()).throw(AssertionError("unintended E2E probe")),
    )
    ollama_client.reset_default_client_for_tests()
    assert isinstance(ollama_client.get_default_client(), ollama_client.LLMClient)
    with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
        frozen_plan()
    ollama_client.reset_default_client_for_tests()


def test_normal_data_agent_and_es_are_independent_of_live_acceptance(monkeypatch):
    from agent.data_agent import builder
    from agent.es import es_client

    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    monkeypatch.setattr(
        "agent.external_capabilities.resolve_environment_plan",
        lambda _: (_ for _ in ()).throw(AssertionError("unintended E2E probe")),
    )
    dummy_model, dummy_es = object(), object()
    monkeypatch.setattr(builder, "_SHARED_MODEL", dummy_model)
    monkeypatch.setattr(es_client, "_ES", dummy_es)
    assert builder.build_model() is dummy_model
    assert es_client.get_es() is dummy_es


def test_acceptance_never_uses_an_unprepared_plan(monkeypatch):
    from agent.llm_utils import ollama_client

    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    with requirement_acceptance_scope():
        with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
            ollama_client.get_default_client()
    install_plan(BackendPlan("live", "live", "live", "pass", "pass"))
    with requirement_acceptance_scope():
        assert isinstance(ollama_client.get_default_client(), ollama_client.LLMClient)


def test_worker_start_does_not_probe(tmp_path, monkeypatch):
    from sra_api.services.report_job_worker import ReportJobWorker

    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    monkeypatch.setattr(
        "agent.external_capabilities.resolve_environment_plan",
        lambda _: (_ for _ in ()).throw(AssertionError("unintended E2E probe")),
    )
    worker = ReportJobWorker(object(), tmp_path / "reports")
    worker.stop_event.set()
    worker.start()
    worker.stop()
    assert worker.root.exists()


def test_selector_timeout_has_redacted_rule_fallback():
    def busy(*_args, **_kwargs):
        try:
            raise ReadTimeout("Bearer SECRET at private-endpoint")
        except ReadTimeout as exc:
            raise RuntimeError("llm_runtime_failure") from exc

    result = pack_ev_for_llm(
        [{"ref_no": "來源1", "note": "fact", "d": "2026-10-29"}],
        "請依時間線分析", mode="hybrid", call_llm_fn=busy,
    )
    meta = result["meta"]
    assert meta["llm_error"] == "timeout"
    assert meta["llm_attempted"] and meta["fallback_used"]
    assert meta["fallback_strategy"] == "rules"
    assert result["ev_slim"][0]["note"] == "fact"
    assert result["ev_slim"][0]["ref_no"] == "來源1"
    assert result["ev_slim"][0]["d"] == "2026-10-29"
    assert "SECRET" not in str(result)


def test_selector_bad_json_is_visible_fallback():
    result = pack_ev_for_llm(
        [{"ref_no": "來源1", "note": "fact"}], "摘要",
        mode="llm", call_llm_fn=lambda *_a, **_k: "not JSON",
    )
    assert result["meta"]["llm_error"] == "invalid_response"
    assert result["meta"]["fallback_used"]
    assert result["ev_slim"][0]["note"] == "fact"


def test_selector_valid_hybrid_adds_fields():
    result = pack_ev_for_llm(
        [{"ref_no": "來源1", "note": "fact", "id": "doc1"}], "摘要",
        mode="hybrid", call_llm_fn=lambda *_a, **_k: '{"fields":["ref_no","note","id"]}',
    )
    assert result["meta"]["llm_used"]
    assert not result["meta"]["fallback_used"]
    assert result["ev_slim"][0]["id"] == "doc1"
