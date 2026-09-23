from __future__ import annotations

import pytest

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.mock_es_client import (
    MAPPING, MOCK_DOCS, REQUIREMENT_E2E_INDEX, MockElasticsearch,
)
from agent.es.query_body import build_main_query_body
from agent.external_capabilities import (
    BackendPlan, CapabilityError, Probe, install_plan, mapping_compatibility,
    parse_mode, probe_llm, reset_plan_for_tests, resolve_plan,
)


@pytest.fixture(autouse=True)
def _reset_plan():
    reset_plan_for_tests()
    yield
    reset_plan_for_tests()


@pytest.mark.parametrize("value", ["live", "auto", "offline", " LIVE "])
def test_external_mode_parsing(value):
    assert parse_mode(value) in {"live", "auto", "offline"}


def test_invalid_mode_is_rejected():
    with pytest.raises(CapabilityError, match="external_mode_invalid"):
        parse_mode("fallback")


@pytest.mark.parametrize(
    ("llm", "es", "classification"),
    [(True, True, "FULL_LIVE"), (True, False, "HYBRID"),
     (False, True, "HYBRID"), (False, False, "OFFLINE")],
)
def test_auto_resolution_and_classification(llm, es, classification):
    plan = resolve_plan("auto", Probe(llm, "pass" if llm else "transport_unavailable"),
                        Probe(es, "pass" if es else "dataset_incompatible"))
    assert plan.classification == classification


def test_live_never_falls_back():
    with pytest.raises(CapabilityError, match="llm_transport_unavailable"):
        resolve_plan("live", Probe(False, "transport_unavailable"), Probe(True, "pass"))
    with pytest.raises(CapabilityError, match="elasticsearch_mapping_incompatible"):
        resolve_plan("live", Probe(True, "pass"), Probe(False, "mapping_incompatible"))


def test_offline_is_explicit_and_frozen():
    plan = resolve_plan("offline", Probe(True, "pass"), Probe(True, "pass"))
    assert plan.classification == "OFFLINE"
    assert plan.llm_backend == plan.elasticsearch_backend == "semantic_mock"
    install_plan(plan)
    with pytest.raises(CapabilityError, match="external_capability_plan_frozen"):
        install_plan(BackendPlan("auto", "live", "live", "pass", "pass"))


def test_empty_live_llm_response_is_unavailable():
    class EmptyClient:
        def chat(self, *args, **kwargs):
            return "  "
    assert probe_llm(EmptyClient()) == Probe(False, "empty_response")


def test_offline_adapters_are_installed_at_external_boundaries(monkeypatch):
    plan = resolve_plan("offline", Probe(False, "offline_not_probed"),
                        Probe(False, "offline_not_probed"))
    install_plan(plan)
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "offline")
    from agent.data_agent import builder
    from agent.es import es_client
    from agent.llm_utils import ollama_client
    builder._SHARED_MODEL = None
    es_client._ES = None
    ollama_client._default_client = None
    assert type(builder.build_model()).__name__ == "DeterministicE2ECodeModel"
    assert type(ollama_client.get_default_client()).__name__ == "DeterministicE2ELLMClient"
    assert type(es_client.get_es()).__name__ == "MockElasticsearch"


def test_offline_code_agent_orchestration_still_executes_retrieval(monkeypatch):
    plan = resolve_plan("offline", Probe(False, "offline_not_probed"),
                        Probe(False, "offline_not_probed"))
    install_plan(plan)
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "offline")
    monkeypatch.setenv("ES_INDEX", REQUIREMENT_E2E_INDEX)
    from agent.data_agent import builder
    from agent.es import es_client
    builder._SHARED_MODEL = None
    es_client._ES = None
    result = builder.build_agent("report").run(
        "Produce an evidence-based situation report for the first stable Requirement E2E topic.",
        max_steps=3,
    )
    assert "requirement-e2e-001" in str(result)


def test_mapping_check_is_a_runtime_subset_not_ping():
    assert mapping_compatibility(MAPPING[REQUIREMENT_E2E_INDEX], REQUIREMENT_E2E_INDEX).usable
    broken = {REQUIREMENT_E2E_INDEX: {"mappings": {"properties": {"uuid": {"type": "keyword"}}}}}
    probe = mapping_compatibility(broken, REQUIREMENT_E2E_INDEX)
    assert (probe.usable, probe.category) == (False, "mapping_incompatible")


def test_semantic_fixture_integrity_and_native_event_shape():
    for source in MOCK_DOCS[REQUIREMENT_E2E_INDEX].values():
        content = source["rawInfo"]["content"]
        for block in source["multidim_event_json"]:
            assert isinstance(block["Event"], list)
            assert not any(key.startswith("Event.") for key in block)
            event_ids = [event["event_id"] for event in block["Event"]]
            assert len(event_ids) == len(set(event_ids))
            snippets = block["evidence_snippets"]
            assert all(item["text"] in content for item in snippets)
            supported = {event_id for item in snippets for event_id in item["event_ids"]}
            assert supported == set(event_ids)
            for name in ("Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets"):
                assert all(set(item["event_ids"]) <= set(event_ids) for item in block[name])


def test_production_query_and_real_evidence_parser_consume_mock_hits():
    body = build_main_query_body(
        "Requirement E2E stable topic", False, True, 10, None, None,
        6.0, 2.5, False, "importDT", "30d",
        effective_terms=["Requirement E2E"], core_terms=["Requirement E2E"],
        syn_terms=[], all_terms=["Requirement E2E"],
    )
    response = MockElasticsearch().search(index=REQUIREMENT_E2E_INDEX, body=body)
    hits = response["hits"]["hits"]
    assert len(hits) == 3 and all("evi" in hit["inner_hits"] for hit in hits)
    parsed, evidence, _ = build_hits_and_evidence(
        hits, date_from=None, date_to=None,
        effective_terms=["Requirement E2E"], term_groups=[{"Requirement E2E"}],
        query_for_snippet="Requirement E2E",
    )
    assert len(parsed) == 3
    assert len(evidence) == 3
    assert all(item["event_ids"] == ["E1"] for item in evidence)
