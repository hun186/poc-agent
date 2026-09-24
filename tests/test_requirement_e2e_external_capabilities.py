from __future__ import annotations

import json
import copy
import inspect
from types import SimpleNamespace

import pytest
import requests

from agent.es.evidence_core.builder import build_hits_and_evidence
from agent.es.mock_es_client import (
    MAPPING, MOCK_DOCS, REQUIREMENT_E2E_INDEX, REQUIREMENT_MULTIDIM_MAPPING,
    MockElasticsearch, validate_requirement_fixture,
)
from agent.es.query_body import build_main_query_body
from agent.external_capabilities import (
    BackendPlan, CapabilityError, Probe, _probe_data_agent_model, install_plan,
    mapping_compatibility, parse_mode, probe_elasticsearch, probe_llm,
    probe_llm_boundaries, reset_plan_for_tests, resolve_environment_plan,
    resolve_plan,
)


@pytest.fixture(autouse=True)
def _reset_plan():
    from agent.llm_utils.ollama_client import reset_default_client_for_tests
    reset_plan_for_tests()
    reset_default_client_for_tests()
    yield
    reset_plan_for_tests()
    reset_default_client_for_tests()


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


def test_required_llm_boundaries_all_must_pass():
    probe = probe_llm_boundaries({"router": lambda: "ok", "data_agent": lambda: ""})
    assert not probe.usable and probe.category == "empty_response"
    assert dict(probe.details) == {"router": "pass", "data_agent": "empty_response"}


def test_data_agent_probe_uses_smolagents_text_content_block(monkeypatch):
    from agent.data_agent.types import ENV

    captured = {}

    class Model:
        def __init__(self, **kwargs):
            captured["constructor"] = kwargs

        def generate(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(content="READY.")

    monkeypatch.setattr("smolagents.LiteLLMModel", Model)

    assert _probe_data_agent_model() == "READY."
    assert captured["messages"] == [{
        "role": "user",
        "content": [{"type": "text", "text": "Reply with READY."}],
    }]
    expected_model_id = (ENV.data_agent_model_id if "/" in ENV.data_agent_model_id
                         else f"ollama_chat/{ENV.data_agent_model_id}")
    assert captured["constructor"] == {
        "model_id": expected_model_id,
        "api_base": ENV.model_base_url,
        "temperature": ENV.model_temperature,
    }


def test_environment_plan_invokes_all_llm_boundaries(monkeypatch):
    invoked = []

    class Model:
        def __init__(self, **kwargs):
            pass

        def generate(self, messages):
            invoked.append("data_agent")
            return SimpleNamespace(content="READY.")

    def direct_chat(self, messages, timeout):
        invoked.append("direct")
        return "READY."

    def unavailable_es():
        raise ConnectionError("unavailable")

    monkeypatch.setattr("smolagents.LiteLLMModel", Model)
    monkeypatch.setattr("agent.llm_utils.ollama_client.LLMClient.chat", direct_chat)
    monkeypatch.setattr("agent.es.es_client._build_es", unavailable_es)

    plan = resolve_environment_plan("auto")

    assert plan.llm_backend == "live"
    assert plan.elasticsearch_backend == "semantic_mock"
    assert "data_agent" in invoked
    assert invoked.count("direct") >= 2


def test_llm_boundary_type_error_is_not_transport_failure():
    probe = probe_llm_boundaries({"data_agent": lambda: (_ for _ in ()).throw(
        TypeError("local message contract failure")
    )})

    assert probe == Probe(False, "boundary_error", (("data_agent", "boundary_error"),))


@pytest.mark.parametrize("error", [
    ConnectionError("connection refused"),
    requests.exceptions.ConnectionError("connection refused"),
    requests.exceptions.Timeout("timed out"),
])
def test_llm_boundary_transport_errors_remain_transport_unavailable(error):
    probe = probe_llm_boundaries({
        "data_agent": lambda: (_ for _ in ()).throw(error),
    })

    assert probe == Probe(
        False, "transport_unavailable", (("data_agent", "transport_unavailable"),),
    )


@pytest.mark.parametrize(("module", "name"), [
    ("openai", "APIConnectionError"),
    ("openai._exceptions", "APITimeoutError"),
    ("litellm.exceptions", "APIConnectionError"),
    ("litellm.exceptions", "APITimeoutError"),
])
def test_optional_client_transport_metadata_is_recognized(module, name):
    exception_type = type(name, (Exception,), {"__module__": module})
    probe = probe_llm_boundaries({
        "data_agent": lambda: (_ for _ in ()).throw(exception_type()),
    })

    assert probe.category == "transport_unavailable"


def test_transport_name_from_unrelated_module_is_boundary_error():
    exception_type = type(
        "APIConnectionError", (Exception,), {"__module__": "unrelated.client"},
    )
    probe = probe_llm_boundaries({
        "data_agent": lambda: (_ for _ in ()).throw(exception_type()),
    })

    assert probe.category == "boundary_error"


def test_wrapped_transport_cause_is_recognized():
    def invoke():
        try:
            raise requests.exceptions.ConnectionError("connection refused")
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError("model invocation failed") from exc

    assert probe_llm_boundaries({"data_agent": invoke}).category == "transport_unavailable"


def test_unrelated_runtime_error_is_boundary_error():
    probe = probe_llm_boundaries({
        "data_agent": lambda: (_ for _ in ()).throw(RuntimeError("invalid runtime state")),
    })

    assert probe.category == "boundary_error"


def test_malformed_exception_chain_cycle_stays_bounded():
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first

    probe = probe_llm_boundaries({
        "data_agent": lambda: (_ for _ in ()).throw(first),
    })

    assert probe.category == "boundary_error"


@pytest.mark.parametrize(("ping", "exists", "mapping", "dataset", "category"), [
    (False, True, True, True, "transport_unavailable"),
    (True, False, True, True, "index_missing"),
    (True, True, False, True, "mapping_incompatible"),
    (True, True, True, False, "dataset_incompatible"),
    (True, True, True, True, "pass"),
])
def test_live_es_probe_categories(ping, exists, mapping, dataset, category):
    class Indices:
        def exists(self, index): return exists
        def get_mapping(self, index):
            return MAPPING[REQUIREMENT_E2E_INDEX] if mapping else {index: {"mappings": {"properties": {}}}}
    client = SimpleNamespace(ping=lambda: ping, indices=Indices())
    probe = probe_elasticsearch(client, [REQUIREMENT_E2E_INDEX], lambda _: dataset)
    assert probe.category == category
    assert probe.usable is (category == "pass")


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


def _query_body(query, *, selected=False, high_value=False, date_from=None, date_to=None):
    terms = query.split()
    return build_main_query_body(
        query, high_value, selected, 10, date_from, date_to,
        6.0, 2.5, False, "importDT", "30d",
        effective_terms=terms, core_terms=[], syn_terms=[], all_terms=terms,
    )


def test_offline_code_agent_derives_actual_requirement_query(monkeypatch):
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
        "請持續蒐集臺灣海峽及周邊海空域軍事、海警與灰色地帶活動。",
        max_steps=3,
    )
    assert "requirement-taiwan-strait-002" in str(result)
    assert "requirement-gaza-001" not in str(result)


def test_mapping_check_is_a_runtime_subset_not_ping():
    assert mapping_compatibility(MAPPING[REQUIREMENT_E2E_INDEX], REQUIREMENT_E2E_INDEX).usable
    broken = {REQUIREMENT_E2E_INDEX: {"mappings": {"properties": {"uuid": {"type": "keyword"}}}}}
    probe = mapping_compatibility(broken, REQUIREMENT_E2E_INDEX)
    assert (probe.usable, probe.category) == (False, "mapping_incompatible")


def test_mapping_check_respects_configured_reference_text(monkeypatch):
    monkeypatch.setenv("SRA_REFERENCE_TEXT_FIELD", "cleaned.reference")
    mapping = copy.deepcopy(MAPPING[REQUIREMENT_E2E_INDEX])
    assert not mapping_compatibility(mapping, REQUIREMENT_E2E_INDEX).usable
    mapping["mappings"]["properties"]["cleaned"] = {
        "properties": {"reference": {"type": "text"}},
    }
    assert mapping_compatibility(mapping, REQUIREMENT_E2E_INDEX).usable


def test_semantic_fixture_integrity_and_native_event_shape():
    assert REQUIREMENT_MULTIDIM_MAPPING["dynamic"] == "strict"
    assert REQUIREMENT_MULTIDIM_MAPPING["properties"]["article_date_iso"] == {
        "type": "date", "format": "yyyy-MM-dd",
    }
    for source in MOCK_DOCS[REQUIREMENT_E2E_INDEX].values():
        validate_requirement_fixture(source)
        content = source["rawInfo"]["content"]
        for block in source["multidim_event_json"]:
            assert len(block["article_date_iso"]) == 10
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


def test_strict_fixture_validator_rejects_unknown_fields_and_datetime_article_date():
    source = copy.deepcopy(MOCK_DOCS[REQUIREMENT_E2E_INDEX]["requirement-gaza-001"])
    source["multidim_event_json"][0]["debug_marker"] = True
    with pytest.raises(ValueError, match="strict_mapping"):
        validate_requirement_fixture(source)
    source = copy.deepcopy(MOCK_DOCS[REQUIREMENT_E2E_INDEX]["requirement-gaza-001"])
    source["multidim_event_json"][0]["article_date_iso"] = "2025-10-08T00:00:00Z"
    with pytest.raises(ValueError, match="article_date"):
        validate_requirement_fixture(source)


@pytest.mark.parametrize(("query", "expected"), [
    ("加薩 停火 人道援助", "requirement-gaza-001"),
    ("臺灣海峽 灰色地帶 海警", "requirement-taiwan-strait-002"),
    ("美中戰略競爭 印太", "requirement-us-china-003"),
])
def test_semantic_backend_discriminates_business_themes(query, expected):
    response = MockElasticsearch().search(index=REQUIREMENT_E2E_INDEX, body=_query_body(query))
    assert [hit["_id"] for hit in response["hits"]["hits"]] == [expected]


def test_unrelated_query_does_not_return_fixtures():
    response = MockElasticsearch().search(
        index=REQUIREMENT_E2E_INDEX, body=_query_body("完全無關量子香蕉"),
    )
    assert response["hits"]["hits"] == []


@pytest.mark.parametrize(("field", "must_flag"), [
    ("selectedMessage", "selected"), ("highValue", "high_value"),
])
def test_semantic_backend_enforces_root_filters(field, must_flag):
    client = MockElasticsearch()
    source = client.docs[REQUIREMENT_E2E_INDEX]["requirement-gaza-001"]
    if field == "selectedMessage":
        source[field] = False
    else:
        source["ai"]["classLabels"][field] = False
    kwargs = {must_flag: True}
    response = client.search(index=REQUIREMENT_E2E_INDEX,
                             body=_query_body("加薩 停火", **kwargs))
    assert response["hits"]["hits"] == []


def test_semantic_backend_enforces_nested_timeline_date_filter():
    assert MockElasticsearch().search(
        index=REQUIREMENT_E2E_INDEX,
        body=_query_body("加薩 停火", date_from="2025-01-01", date_to="2025-12-31"),
    )["hits"]["total"]["value"] == 1
    assert MockElasticsearch().search(
        index=REQUIREMENT_E2E_INDEX,
        body=_query_body("加薩 停火", date_from="2026-01-01", date_to="2026-12-31"),
    )["hits"]["total"]["value"] == 0


def test_production_query_and_real_evidence_parser_consume_mock_hits():
    body = _query_body("加薩 停火 人道援助", selected=True, high_value=True)
    response = MockElasticsearch().search(index=REQUIREMENT_E2E_INDEX, body=body)
    hits = response["hits"]["hits"]
    assert len(hits) == 1 and "evi" in hits[0]["inner_hits"]
    parsed, evidence, _ = build_hits_and_evidence(
        hits, date_from=None, date_to=None,
        effective_terms=["加薩", "停火"], term_groups=[{"加薩"}, {"停火"}],
        query_for_snippet="加薩 停火",
    )
    assert len(parsed) == 1
    assert len(evidence) == 1
    assert all(item["event_ids"] == ["E1"] for item in evidence)


def test_unsupported_semantic_query_fails_visibly():
    with pytest.raises(ValueError, match="semantic_mock_unsupported_query"):
        MockElasticsearch().search(index=REQUIREMENT_E2E_INDEX,
                                   body={"query": {"query_string": {"query": "加薩"}}})


@pytest.mark.parametrize(("question", "expected_topic"), [
    ("請分析加薩停火、人質談判與人道援助。", "news_general"),
    ("請分析臺灣海峽灰色地帶活動。", "mil_intel"),
    ("請分析美中戰略競爭與美軍印太部署。", "mil_intel"),
])
def test_deterministic_router_recognizes_actual_prompt(question, expected_topic):
    from agent.llm_utils.ollama_client import DeterministicE2ELLMClient
    from agent.routing import TASK_ROUTER_SYSTEM
    from config.index_loader import INDEX_CONFIG
    client = DeterministicE2ELLMClient()
    routed = json.loads(client.chat([
        {"role": "system", "content": TASK_ROUTER_SYSTEM},
        {"role": "user", "content": question},
    ]))
    assert routed["mode"] == "SRA_REPORT"
    assert routed["topic"] == expected_topic
    assert routed["topic"] in INDEX_CONFIG["topic_index_map"]


def test_deterministic_refiner_recognizes_actual_prompt_with_time_context():
    from agent.llm_utils.ollama_client import DeterministicE2ELLMClient
    from agent.refiners.query_refiner import REFINER_SYSTEM_PROMPT
    question = "請持續蒐集去年加薩停火、人質談判及人道援助。"
    system = REFINER_SYSTEM_PROMPT + "\n\n【本次時間換算基準】reference_time=2026-09-23T00:00:00+00:00"
    client = DeterministicE2ELLMClient()
    refined = json.loads(client.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": f"請精煉下列使用者問句，只輸出 JSON。\n\n【使用者問句】\n{question}\n"},
    ]))
    assert refined == {"refined_question": question}


def test_deterministic_field_selector_raw_contract_uses_actual_prompt():
    from agent.llm_utils.ollama_client import DeterministicE2ELLMClient
    from agent.utils.evidence_pack import ALL_EV_FIELDS, LLM_FIELD_SELECTOR_SYSTEM
    raw = DeterministicE2ELLMClient().chat([
        {"role": "system", "content": LLM_FIELD_SELECTOR_SYSTEM},
        {"role": "user", "content": json.dumps({"q": "加薩時間線", "candidates": sorted(ALL_EV_FIELDS)}, ensure_ascii=False)},
    ])
    fields = json.loads(raw)["fields"]
    assert {"ref_no", "note"} <= set(fields)
    assert set(fields) <= ALL_EV_FIELDS


def test_deterministic_report_consumes_actual_production_payload():
    from agent.llm_utils.ollama_client import DeterministicE2ELLMClient
    from agent.report_prompt import REPORT_SYSTEM_PROMPT
    payload = {"q": "加薩情勢", "q0": "請分析加薩", "t": [None, None],
               "agg": {"docs": 1}, "ev": [{"ref_no": 7,
               "title": "供應標題", "note": "供應證據中的唯一事實。"}]}
    client = DeterministicE2ELLMClient()
    report = client.chat([
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    assert "供應證據中的唯一事實" in report
    assert "供應標題" in report and "參考 7" in report
    assert "未加入外部事實" in report
    empty_report = client.chat([
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({**payload, "ev": []}, ensure_ascii=False)},
    ])
    assert "供應證據中的唯一事實" not in empty_report
    assert all(term not in empty_report for term in ("加薩停火", "臺灣海峽", "美中戰略"))


def test_deterministic_query_term_contracts_use_production_callers(monkeypatch):
    from agent.es import query_terms
    from agent.llm_utils.ollama_client import DeterministicE2ELLMClient
    client = DeterministicE2ELLMClient()
    monkeypatch.setenv("TOPIC_LLM_URL", "semantic-mock-enabled")
    monkeypatch.setattr(query_terms, "call_llm", lambda prompt, *, system_prompt, **kwargs:
                        client.chat([{"role": "system", "content": system_prompt},
                                     {"role": "user", "content": prompt}]))
    terms = query_terms.extract_topic_terms_llm("分析臺灣海峽灰色地帶活動")
    assert {"臺灣海峽", "灰色地帶"} <= set(terms)
    assert query_terms.expand_synonyms_grouped_llm("分析臺灣海峽", terms) == {}


def test_unknown_deterministic_direct_llm_contract_fails_closed():
    from agent.llm_utils.ollama_client import DeterministicE2ELLMClient
    with pytest.raises(RuntimeError, match="unsupported_e2e_llm_contract"):
        DeterministicE2ELLMClient().chat([
            {"role": "system", "content": "未審查的新系統契約"},
            {"role": "user", "content": '{"ev":[]}'},
        ])


def test_production_llm_generate_regression(monkeypatch):
    from agent.llm_utils.ollama_client import LLMClient
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": "generated"}
    monkeypatch.setattr("agent.llm_utils.ollama_client.requests.post",
                        lambda url, **kwargs: captured.update(url=url, **kwargs) or Response())
    client = LLMClient(base_url="http://model", model="production-model", timeout=7)
    assert client.generate("prompt") == "generated"
    assert captured["url"] == "http://model/api/generate"
    assert captured["json"]["model"] == "production-model"


def test_production_llm_chat_regression(monkeypatch):
    from agent.llm_utils.ollama_client import LLMClient
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"message": {"role": "assistant", "content": "chat-result"}}
    monkeypatch.setattr("agent.llm_utils.ollama_client.requests.post",
                        lambda url, **kwargs: captured.update(url=url, **kwargs) or Response())
    client = LLMClient(base_url="http://model", model="production-model")
    assert client.chat([{"role": "user", "content": "hello"}]) == "chat-result"
    assert captured["url"] == "http://model/api/chat"


@pytest.mark.parametrize(("mode", "backend", "expected"), [
    (None, None, "LLMClient"),
    ("live", "live", "LLMClient"),
    ("offline", "semantic_mock", "DeterministicE2ELLMClient"),
])
def test_default_client_activation_boundary(monkeypatch, mode, backend, expected):
    from agent.llm_utils import ollama_client
    monkeypatch.delenv("REQUIREMENT_E2E_EXTERNAL_MODE", raising=False)
    ollama_client.reset_default_client_for_tests()
    if mode:
        monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", mode)
        install_plan(BackendPlan(mode, backend, "live", "pass", "pass"))
    assert type(ollama_client.get_default_client()).__name__ == expected


def test_default_client_reset_prevents_cross_test_backend_leak(monkeypatch):
    from agent.llm_utils import ollama_client
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "offline")
    install_plan(BackendPlan("offline", "semantic_mock", "semantic_mock",
                             "offline_not_probed", "offline_not_probed"))
    assert isinstance(ollama_client.get_default_client(), ollama_client.DeterministicE2ELLMClient)
    ollama_client.reset_default_client_for_tests()
    reset_plan_for_tests()
    monkeypatch.delenv("REQUIREMENT_E2E_EXTERNAL_MODE")
    assert type(ollama_client.get_default_client()).__name__ == "LLMClient"


def test_harness_asserts_mode_without_mutating_runtime_environment():
    from operator_e2e import test_requirement_schedule_e2e as harness
    source = inspect.getsource(harness.main)
    assert 'os.environ["REQUIREMENT_E2E_EXTERNAL_MODE"]' not in source
    assert "external_capability_mode_mismatch" in inspect.getsource(harness.Harness.run)


def test_manual_run_api_prohibition_remains():
    from operator_e2e.test_requirement_schedule_e2e import Api
    assert "manual run forbidden" in inspect.getsource(Api.request_raw)


def test_execute_agent_turn_offline_runs_real_report_path(monkeypatch):
    plan = resolve_plan("offline", Probe(False, "offline_not_probed"),
                        Probe(False, "offline_not_probed"))
    install_plan(plan)
    monkeypatch.setenv("REQUIREMENT_E2E_EXTERNAL_MODE", "offline")
    monkeypatch.setenv("ES_INDEX", REQUIREMENT_E2E_INDEX)
    monkeypatch.setenv("SESSION_STORE_ENABLED", "0")
    from agent import agent as agent_module
    from agent.data_agent import builder
    from agent.es import es_client
    from agent.llm_utils import ollama_client
    from api.services.sessions import ChatMessage
    from sra_api.services import turn_execution
    builder._SHARED_MODEL = None
    es_client._ES = None
    ollama_client._default_client = None
    monkeypatch.setattr(agent_module, "SESSION_STORE_ENABLED", False)
    monkeypatch.setattr(turn_execution, "get_sessions", lambda: {})
    monkeypatch.setattr(turn_execution, "get_last_structured", lambda: {})
    monkeypatch.setattr(turn_execution, "get_memory", lambda: {})
    monkeypatch.setattr(turn_execution, "save_structured_snapshot", lambda *args: None)
    payload = SimpleNamespace(model="offline", stream=False, messages=[ChatMessage(
        role="user", content="請分析臺灣海峽軍事、海警與灰色地帶活動並提出情勢報告。",
    )])
    result = turn_execution.execute_agent_turn(
        payload=payload, request=None, session_id="offline-capability-test",
        request_id="offline-turn-1", trace={"integration": True},
    )
    assert result.output["mode"] == "SRA_REPORT"
    assert result.output["used_uuids"] == ["requirement-taiwan-strait-002"]
    assert result.output["citations"]
    assert "臺灣海峽" in result.output["answer"]
    assert result.trace["routing"]["mode"] == "SRA_REPORT"
    assert result.trace["data_agent"]["runs"]
