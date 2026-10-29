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


def test_regular_es_index_helpers_do_not_acquire_e2e_plan_lock(monkeypatch):
    from agent.es import es_client
    from agent import external_capabilities

    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    monkeypatch.setattr(
        external_capabilities, "frozen_plan",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("E2E lock acquired")),
    )
    monkeypatch.setattr(es_client, "_USING_MOCK_ES", False)
    monkeypatch.setattr(es_client, "_ES", object())
    # A direct production hint is sufficient to verify index isolation.
    assert es_client.resolve_index("production-index") == "production-index"
    assert es_client.using_mock_es() is False


def test_acceptance_es_index_fails_closed_before_preflight(monkeypatch):
    from agent.es import es_client

    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "live")
    with requirement_acceptance_scope():
        with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
            es_client.resolve_index("production-index")
        with pytest.raises(CapabilityError, match="external_capability_plan_unresolved"):
            es_client.using_mock_es()


def test_selector_connection_failure_has_redacted_transport_fallback():
    from requests.exceptions import ConnectionError as RequestsConnectionError

    def offline(*_args, **_kwargs):
        try:
            raise RequestsConnectionError("private-url bearer=SECRET")
        except RequestsConnectionError as exc:
            raise RuntimeError("llm_runtime_failure") from exc

    result = pack_ev_for_llm(
        [{"ref_no": "來源1", "note": "source fact"}], "摘要",
        mode="hybrid", call_llm_fn=offline,
    )
    assert result["meta"]["llm_error"] == "transport_unavailable"
    assert result["meta"]["fallback_strategy"] == "rules"
    assert result["ev_slim"][0]["note"] == "source fact"
    assert "SECRET" not in str(result)


def test_operator_preflight_has_bounded_long_read_budget():
    from operator_e2e.requirement_e2e_evidence import (
        E2E_PREFLIGHT_TIMEOUT_SECONDS, RemoteDeploymentEvidenceProvider,
    )

    class FakeApi:
        observed = None

        def get(self, path, *, timeout):
            self.observed = (path, timeout)
            return {
                "schema_version": "requirement_e2e_runtime_evidence_v1",
                "workers": {
                    "schedule": {"alive": True, "identity_verified": True},
                    "handoff": {"alive": True, "identity_verified": True},
                },
                "artifact_root_fingerprint": "synthetic-only-not-acceptance",
            }

    api = FakeApi()
    result = RemoteDeploymentEvidenceProvider(api).preflight("release")
    assert result["schema_version"] == "requirement_e2e_runtime_evidence_v1"
    assert api.observed == (
        "/v1/operator-e2e/runtime-evidence?verification=release",
        E2E_PREFLIGHT_TIMEOUT_SECONDS,
    )
    assert 30 < E2E_PREFLIGHT_TIMEOUT_SECONDS <= 600
