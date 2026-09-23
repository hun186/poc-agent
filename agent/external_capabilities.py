"""Frozen external-backend policy for Requirement operator acceptance.

This module is intentionally inactive unless ``REQUIREMENT_E2E_EXTERNAL_MODE``
is set.  Normal application deployments therefore retain their existing LLM
and Elasticsearch selection behaviour.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping


MODES = frozenset({"live", "auto", "offline"})
REQUIRED_NESTED_PATHS = (
    "multidim_event_json", "multidim_event_json.Event",
    "multidim_event_json.Event_Timeline", "multidim_event_json.Person",
    "multidim_event_json.Involved_Parties",
    "multidim_event_json.evidence_snippets",
)
REQUIRED_LEAVES = (
    "uuid", "communication.subject", "rawInfo.content", "importDT",
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


@dataclass(frozen=True)
class BackendPlan:
    requested_mode: str
    llm_backend: str
    elasticsearch_backend: str
    llm_probe: str
    elasticsearch_probe: str

    @property
    def classification(self) -> str:
        live = (self.llm_backend == "live") + (self.elasticsearch_backend == "live")
        return ("FULL_LIVE", "HYBRID", "OFFLINE")[2 - live]

    def evidence(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode,
            "classification": self.classification,
            "capabilities": {
                "llm": {"backend": self.llm_backend, "probe": self.llm_probe},
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
    )


def _field(mapping: Mapping[str, Any], dotted: str) -> Mapping[str, Any] | None:
    node: Mapping[str, Any] = mapping.get("properties", mapping)
    for part in dotted.split("."):
        value = node.get(part)
        if not isinstance(value, Mapping):
            return None
        node = value.get("properties", {}) if "properties" in value else value
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
    if any(_field(mapping, path) is None for path in REQUIRED_LEAVES):
        return Probe(False, "mapping_incompatible")
    return Probe(True, "pass")


def probe_llm(client: Any) -> Probe:
    try:
        value = client.chat([{"role": "user", "content": "Reply with READY."}], timeout=10)
    except Exception:
        return Probe(False, "transport_unavailable")
    return Probe(bool(isinstance(value, str) and value.strip()),
                 "pass" if isinstance(value, str) and value.strip() else "empty_response")


def probe_elasticsearch(client: Any, index: str,
                        acceptance_search: Callable[[Any, str], bool]) -> Probe:
    try:
        if not client.ping():
            return Probe(False, "transport_unavailable")
        if not client.indices.exists(index=index):
            return Probe(False, "index_missing")
        compatible = mapping_compatibility(client.indices.get_mapping(index=index), index)
        if not compatible.usable:
            return compatible
        if not acceptance_search(client, index):
            return Probe(False, "dataset_incompatible")
        return Probe(True, "pass")
    except PermissionError:
        return Probe(False, "access_failure")
    except Exception as exc:
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        return Probe(False, "access_failure" if status in {401, 403} else "transport_unavailable")


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
    from agent.es.es_client import _build_es, _calc_default_index
    from agent.llm_utils.ollama_client import LLMClient

    if mode == "offline":
        return resolve_plan(mode, Probe(False, "offline_not_probed"),
                            Probe(False, "offline_not_probed"))
    llm = probe_llm(LLMClient())
    index = _calc_default_index()
    try:
        es = _build_es()
    except Exception:
        es_probe = Probe(False, "transport_unavailable")
    else:
        def acceptance_search(client: Any, target: str) -> bool:
            # Suitability is evidence, not ping: each canonical Requirement
            # content phrase must retrieve at least one production-shaped hit.
            for ordinal in ("first", "second", "third"):
                response = client.search(index=target, body={
                    "size": 1,
                    "query": {"match": {"rawInfo.content":
                        f"{ordinal} stable Requirement E2E topic"}},
                })
                body = getattr(response, "body", response)
                if not (((body or {}).get("hits") or {}).get("hits") or []):
                    return False
            return True
        es_probe = probe_elasticsearch(es, index, acceptance_search)
    return resolve_plan(mode, llm, es_probe)


def reset_plan_for_tests() -> None:
    global _PLAN
    with _LOCK:
        _PLAN = None
