"""Frozen external-backend policy for Requirement operator acceptance.

This module is intentionally inactive unless ``REQUIREMENT_E2E_EXTERNAL_MODE``
is set.  Normal application deployments therefore retain their existing LLM
and Elasticsearch selection behaviour.
"""
from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from requests import exceptions as requests_exceptions

from agent.es.reference_text import get_reference_text_field


MODES = frozenset({"live", "auto", "offline"})
REQUIREMENT_E2E_MODEL_PREFIX = "requirement-e2e:"
_REQUIREMENT_ACCEPTANCE_ACTIVE: ContextVar[bool] = ContextVar(
    "requirement_acceptance_active", default=False,
)
REQUIRED_NESTED_PATHS = (
    "multidim_event_json", "multidim_event_json.Event",
    "multidim_event_json.Event_Timeline", "multidim_event_json.Person",
    "multidim_event_json.Involved_Parties",
    "multidim_event_json.evidence_snippets",
)
REQUIRED_LEAVES = (
    "uuid", "communication.subject", "communication.subject.keyword",
    "selectedMessage", "ai.classLabels.highValue", "importDT",
    "multidim_event_json.article_title.raw",
    "multidim_event_json.Event.event_id",
    "multidim_event_json.Event_Timeline.time_iso",
    "multidim_event_json.evidence_snippets.text",
)


class CapabilityError(RuntimeError):
    """A stable, non-secret capability failure category."""


@dataclass(frozen=True)
class Probe:
    usable: bool
    category: str
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BackendPlan:
    requested_mode: str
    llm_backend: str
    elasticsearch_backend: str
    llm_probe: str
    elasticsearch_probe: str
    llm_probe_details: tuple[tuple[str, str], ...] = ()

    @property
    def classification(self) -> str:
        live = (self.llm_backend == "live") + (self.elasticsearch_backend == "live")
        return ("FULL_LIVE", "HYBRID", "OFFLINE")[2 - live]

    def evidence(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode,
            "classification": self.classification,
            "capabilities": {
                "llm": {"backend": self.llm_backend, "probe": self.llm_probe,
                        "boundaries": dict(self.llm_probe_details)},
                "elasticsearch": {
                    "backend": self.elasticsearch_backend,
                    "probe": self.elasticsearch_probe,
                },
            },
        }


def parse_mode(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    mode = value.strip().lower()
    if mode not in MODES:
        raise CapabilityError("external_mode_invalid")
    return mode


def requirement_e2e_es_index() -> str:
    """Return the dedicated real-ES Requirement acceptance index."""
    from agent.es.mock_es_client import REQUIREMENT_E2E_INDEX

    value = (os.getenv("REQUIREMENT_E2E_ES_INDEX") or REQUIREMENT_E2E_INDEX).strip()
    if not re.fullmatch(r"requirement_e2e_[a-z0-9._-]{1,238}", value):
        raise CapabilityError("elasticsearch_acceptance_index_invalid")
    return value


def mark_requirement_e2e_model(model: str) -> str:
    """Encode an explicit, durable acceptance marker into the existing model field."""
    base = str(model or "").strip()
    marked = REQUIREMENT_E2E_MODEL_PREFIX + base
    if not base or len(marked) > 240:
        raise CapabilityError("external_e2e_model_invalid")
    return marked


def split_requirement_e2e_model(model: str) -> tuple[bool, str]:
    value = str(model or "").strip()
    if not value.startswith(REQUIREMENT_E2E_MODEL_PREFIX):
        return False, value
    base = value[len(REQUIREMENT_E2E_MODEL_PREFIX):].strip()
    if not base:
        raise CapabilityError("external_e2e_model_invalid")
    return True, base


@contextmanager
def requirement_acceptance_scope():
    """Scope acceptance-only routing to one explicitly marked Report Job."""
    token = _REQUIREMENT_ACCEPTANCE_ACTIVE.set(True)
    try:
        yield
    finally:
        _REQUIREMENT_ACCEPTANCE_ACTIVE.reset(token)


def requirement_acceptance_active() -> bool:
    return _REQUIREMENT_ACCEPTANCE_ACTIVE.get()


def resolve_plan(mode: str, llm: Probe, elasticsearch: Probe) -> BackendPlan:
    mode = parse_mode(mode) or "auto"
    if mode == "live" and not llm.usable:
        raise CapabilityError(f"llm_{llm.category}")
    if mode == "live" and not elasticsearch.usable:
        raise CapabilityError(f"elasticsearch_{elasticsearch.category}")
    force_mock = mode == "offline"
    return BackendPlan(
        requested_mode=mode,
        llm_backend="semantic_mock" if force_mock or not llm.usable else "live",
        elasticsearch_backend="semantic_mock" if force_mock or not elasticsearch.usable else "live",
        llm_probe="offline_not_probed" if force_mock else llm.category,
        elasticsearch_probe="offline_not_probed" if force_mock else elasticsearch.category,
        llm_probe_details=llm.details,
    )


def _field(mapping: Mapping[str, Any], dotted: str) -> Mapping[str, Any] | None:
    node: Mapping[str, Any] = mapping.get("properties", mapping)
    for part in dotted.split("."):
        value = node.get(part)
        if not isinstance(value, Mapping):
            return None
        if "properties" in value:
            node = value["properties"]
        elif "fields" in value:
            node = value["fields"]
        else:
            node = value
    return value


def mapping_compatibility(mapping_response: Mapping[str, Any], index: str) -> Probe:
    entry = mapping_response.get(index)
    if entry is None and "mappings" in mapping_response:
        entry = mapping_response
    if not isinstance(entry, Mapping) and len(mapping_response) == 1:
        entry = next(iter(mapping_response.values()))
    mapping = entry.get("mappings", {}) if isinstance(entry, Mapping) else {}
    for path in REQUIRED_NESTED_PATHS:
        field = _field(mapping, path)
        if not field or field.get("type") != "nested":
            return Probe(False, "mapping_incompatible")
    leaves = (*REQUIRED_LEAVES, get_reference_text_field())
    if any(_field(mapping, path) is None for path in leaves):
        return Probe(False, "mapping_incompatible")
    return Probe(True, "pass")


def probe_llm(client: Any) -> Probe:
    try:
        value = client.chat([{"role": "user", "content": "Reply with READY."}], timeout=10)
    except Exception:
        return Probe(False, "transport_unavailable")
    return Probe(bool(isinstance(value, str) and value.strip()),
                 "pass" if isinstance(value, str) and value.strip() else "empty_response")


def _llm_boundary_exception_category(exc: Exception) -> str:
    transport_errors = (
        ConnectionError,
        TimeoutError,
        requests_exceptions.ConnectionError,
        requests_exceptions.Timeout,
    )
    optional_transport_names = frozenset({
        "APIConnectionError", "APITimeoutError", "ConnectionError", "Timeout",
    })
    optional_transport_modules = frozenset({"openai", "litellm"})

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        if isinstance(current, transport_errors):
            return "transport_unavailable"

        for cls in type(current).__mro__:
            module_root = cls.__module__.split(".", 1)[0]
            if module_root in optional_transport_modules and cls.__name__ in optional_transport_names:
                return "transport_unavailable"

        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)

    return "boundary_error"


def probe_llm_boundaries(boundaries: Mapping[str, Callable[[], str]]) -> Probe:
    results = []
    for name, invoke in boundaries.items():
        try:
            value = invoke()
            category = "pass" if isinstance(value, str) and value.strip() else "empty_response"
        except Exception as exc:
            category = _llm_boundary_exception_category(exc)
        results.append((name, category))
    failed = next((category for _, category in results if category != "pass"), None)
    return Probe(failed is None, "pass" if failed is None else failed, tuple(results))


def probe_elasticsearch(client: Any, indexes: str | Sequence[str],
                        acceptance_search: Callable[[Any], bool]) -> Probe:
    try:
        if not client.ping():
            return Probe(False, "transport_unavailable")
        targets = [indexes] if isinstance(indexes, str) else list(indexes)
        for index in targets:
            if not client.indices.exists(index=index):
                return Probe(False, "index_missing")
            compatible = mapping_compatibility(client.indices.get_mapping(index=index), index)
            if not compatible.usable:
                return compatible
        if not acceptance_search(client):
            return Probe(False, "dataset_incompatible")
        return Probe(True, "pass")
    except PermissionError:
        return Probe(False, "access_failure")
    except Exception as exc:
        meta = getattr(exc, "meta", None)
        status = (getattr(exc, "status_code", None) or getattr(exc, "status", None)
                  or getattr(meta, "status", None))
        return Probe(False, "access_failure" if status in {401, 403} else "transport_unavailable")



def _elasticsearch_exception_probe(exc: Exception, *, setup: bool = False) -> Probe:
    meta = getattr(exc, "meta", None)
    status = (getattr(exc, "status_code", None) or getattr(exc, "status", None)
              or getattr(meta, "status", None))
    if status in {401, 403}:
        return Probe(False, "access_failure")
    if setup and status is not None:
        return Probe(False, "fixture_setup_failed")
    return Probe(False, "transport_unavailable")


def prepare_requirement_elasticsearch(
    client: Any, index: str, protected_indexes: Sequence[str],
) -> Probe:
    """Create/validate/seed the dedicated live Requirement acceptance index.

    Existing incompatible or polluted indexes fail closed.  The function never
    deletes, recreates, or mutates production topic indexes.
    """
    from agent.es.mock_es_client import (
        MOCK_DOCS, REQUIREMENT_E2E_INDEX, REQUIREMENT_E2E_MAPPING,
        validate_requirement_fixture,
    )

    if index in set(protected_indexes):
        return Probe(False, "acceptance_index_conflict")
    try:
        if not client.ping():
            return Probe(False, "transport_unavailable")
        if not client.indices.exists(index=index):
            client.indices.create(
                index=index,
                mappings=REQUIREMENT_E2E_MAPPING["mappings"],
            )
        compatible = mapping_compatibility(client.indices.get_mapping(index=index), index)
        if not compatible.usable:
            return compatible

        fixtures = MOCK_DOCS[REQUIREMENT_E2E_INDEX]
        for doc_id, source in fixtures.items():
            validate_requirement_fixture(source)
            client.index(
                index=index,
                id=doc_id,
                document=source,
                refresh="wait_for",
            )

        count_response = client.count(index=index)
        count_body = getattr(count_response, "body", count_response)
        if int((count_body or {}).get("count", -1)) != len(fixtures):
            return Probe(False, "fixture_dataset_drift")
        return Probe(True, "pass")
    except PermissionError:
        return Probe(False, "access_failure")
    except Exception as exc:
        return _elasticsearch_exception_probe(exc, setup=True)

_LOCK = threading.Lock()
_PLAN: BackendPlan | None = None


def frozen_plan(resolver: Callable[[str], BackendPlan] | None = None) -> BackendPlan | None:
    """Resolve once per process; a later runtime error never changes backend."""
    global _PLAN
    mode = parse_mode(os.getenv("REQUIREMENT_E2E_EXTERNAL_MODE"))
    if mode is None:
        return None
    with _LOCK:
        if _PLAN is None:
            if resolver is None:
                raise CapabilityError("external_capability_plan_unresolved")
            _PLAN = resolver(mode)
        elif _PLAN.requested_mode != mode:
            raise CapabilityError("external_capability_plan_frozen")
        return _PLAN


def install_plan(plan: BackendPlan) -> BackendPlan:
    global _PLAN
    with _LOCK:
        if _PLAN is not None and _PLAN != plan:
            raise CapabilityError("external_capability_plan_frozen")
        _PLAN = plan
        return plan


def resolve_environment_plan(mode: str) -> BackendPlan:
    """Probe both real boundaries before selecting either E2E backend."""
    from agent.es.es_client import _build_es
    from agent.es.query_body import build_main_query_body
    from agent.llm_utils.ollama_client import LLMClient
    from agent.data_agent.types import ENV
    from agent.report_config import REPORT_MODEL_ID
    from agent.routing import ROUTER_MODEL_ID
    from agent.refiners.query_refiner import REFINER_MODEL_ID, REFINER_REPORT_ENABLED
    from config.index_loader import INDEX_CONFIG

    if mode == "offline":
        return resolve_plan(mode, Probe(False, "offline_not_probed"),
                            Probe(False, "offline_not_probed"))
    direct_models = {"router": ROUTER_MODEL_ID, "report": REPORT_MODEL_ID}
    if REFINER_REPORT_ENABLED:
        direct_models["query_refiner"] = REFINER_MODEL_ID
    if os.getenv("REPORT_EV_FIELD_SELECTOR_MODE", "rules").strip().lower() == "llm":
        direct_models["field_selector"] = os.getenv("REPORT_FIELD_SELECTOR_MODEL_ID") or REPORT_MODEL_ID
    boundaries = {
        name: (lambda model=model: LLMClient(model=model).chat(
            [{"role": "user", "content": "Reply with READY."}], timeout=10))
        for name, model in direct_models.items()
    }
    def data_agent_call() -> str:
        from smolagents import LiteLLMModel
        model_id = (ENV.data_agent_model_id if "/" in ENV.data_agent_model_id
                    else f"ollama_chat/{ENV.data_agent_model_id}")
        model = LiteLLMModel(model_id=model_id, api_base=ENV.model_base_url,
                             temperature=ENV.model_temperature)
        response = model.generate([{
            "role": "user",
            "content": [{"type": "text", "text": "Reply with READY."}],
        }])
        return str(response.content or "")
    boundaries["data_agent"] = data_agent_call
    llm = probe_llm_boundaries(boundaries)
    topic_map = INDEX_CONFIG.get("topic_index_map", {})
    production_indexes = []
    for raw in INDEX_CONFIG.get("default", []) or []:
        for index in str(raw).split(","):
            index = index.strip()
            if index and index not in production_indexes:
                production_indexes.append(index)
    for topic_cfg in topic_map.values():
        for raw in (topic_cfg or {}).get("indexes", []):
            for index in str(raw).split(","):
                index = index.strip()
                if index and index not in production_indexes:
                    production_indexes.append(index)

    acceptance_index = requirement_e2e_es_index()
    try:
        es = _build_es()
    except Exception:
        es_probe = Probe(False, "transport_unavailable")
    else:
        prepared = prepare_requirement_elasticsearch(
            es, acceptance_index, production_indexes,
        )
        if not prepared.usable:
            es_probe = prepared
        else:
            def acceptance_search(client: Any) -> bool:
                cases = (
                    "加薩 停火 人道援助",
                    "臺灣海峽 灰色地帶",
                    "美中戰略競爭 印太",
                )
                for query in cases:
                    terms = query.split()
                    body = build_main_query_body(
                        query, False, False, 1, None, None, 6.0, 2.5,
                        False, "importDT", "30d", effective_terms=terms,
                        core_terms=[], syn_terms=[], all_terms=terms,
                    )
                    response = client.search(index=acceptance_index, body=body)
                    body = getattr(response, "body", response)
                    if not (((body or {}).get("hits") or {}).get("hits") or []):
                        return False
                return True
            es_probe = probe_elasticsearch(es, acceptance_index, acceptance_search)
    return resolve_plan(mode, llm, es_probe)


def reset_plan_for_tests() -> None:
    global _PLAN
    with _LOCK:
        _PLAN = None
