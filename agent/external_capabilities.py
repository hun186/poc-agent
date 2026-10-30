"""Frozen external-backend policy for Requirement operator E2E acceptance.

``REQUIREMENT_E2E_EXTERNAL_MODE`` controls only verified E2E test jobs.
Semantic mocks and the dedicated acceptance fixture are valid only while the
verified E2E execution scope is active. Ordinary production/user Report Jobs,
including normal Requirement -> Schedule -> Handoff jobs, always stay on the
ordinary real LLM and Elasticsearch paths and never inherit an E2E fallback.
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

from agent.e2e_preflight_budget import (
    PreflightDeadlineExceeded, budget_active, budget_timeout, check_budget,
)

from agent.es.reference_text import get_reference_text_field


MODES = frozenset({"live", "auto", "offline"})
REQUIREMENT_E2E_MODEL_PREFIX = "requirement-e2e:"
# Shared runtime/diagnostic name rule; validate effective config before
# either runtime fixture access or operator-only Elasticsearch probes.
REQUIREMENT_E2E_INDEX_PATTERN = re.compile(r"requirement_e2e_[a-z0-9._-]{1,238}")
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


_REQUIREMENT_ADMITTED_PLAN: ContextVar[BackendPlan | None] = ContextVar(
    "requirement_e2e_admitted_plan", default=None,
)


def admitted_requirement_e2e_plan() -> BackendPlan | None:
    """Only a verified Report Job's current execution context may hold this."""
    if not requirement_acceptance_active():
        return None
    return _REQUIREMENT_ADMITTED_PLAN.get()


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
    if REQUIREMENT_E2E_INDEX_PATTERN.fullmatch(value) is None:
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


def verified_requirement_e2e_job_model(job: Any) -> tuple[bool, str]:
    """Identify a verified Operator E2E test job, not a normal Requirement job.

    The reserved model prefix alone is untrusted and never proves test origin.
    Verification also requires the server-derived canonical Handoff owner and
    durable idempotency/session/metadata contract. A normal production Handoff
    job without the reserved E2E marker remains ordinary production execution.
    """
    marked, effective_model = split_requirement_e2e_model(getattr(job, "model", ""))
    if not marked:
        return False, effective_model

    expected_owner = (os.getenv("REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL") or "").strip()
    metadata = getattr(job, "metadata", {})
    submission_id = str(getattr(job, "idempotency_key", "") or "")
    trusted = (
        bool(expected_owner)
        and getattr(job, "owner_kind", None) == "service"
        and getattr(job, "owner_id", None) == expected_owner
        and re.fullmatch(r"rhsub_[0-9a-f]{48}", submission_id) is not None
        and getattr(job, "session_id", None) == f"requirement-handoff:{submission_id}"
        and isinstance(metadata, Mapping)
        and metadata.get("submission_id") == submission_id
        and metadata.get("workflow_id") == "report_v1"
    )
    if not trusted:
        raise CapabilityError("external_e2e_provenance_invalid")
    return True, effective_model


# Backward-compatible internal alias for older imports. New code and operator
# documentation use "verified E2E test job" to avoid implying that Requirement
# content itself is trusted.
trusted_requirement_e2e_job_model = verified_requirement_e2e_job_model


@contextmanager
def requirement_acceptance_scope(admitted_plan: BackendPlan | None = None):
    """Scope only a verified Report Job's already-admitted immutable plan.

    Normal API/production work never enters this scope. A plan admitted by the
    Report Job Worker stays pinned for that job's later LLM/ES tool lookups,
    including a revalidation that suspends new E2E job admission.
    """
    token = _REQUIREMENT_ACCEPTANCE_ACTIVE.set(True)
    plan_token = _REQUIREMENT_ADMITTED_PLAN.set(admitted_plan)
    try:
        yield
    finally:
        _REQUIREMENT_ADMITTED_PLAN.reset(plan_token)
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
        check_budget()
        try:
            value = invoke()
            check_budget()
            category = "pass" if isinstance(value, str) and value.strip() else "empty_response"
        except PreflightDeadlineExceeded:
            raise
        except Exception as exc:
            check_budget()
            category = _llm_boundary_exception_category(exc)
        results.append((name, category))
    failed = next((category for _, category in results if category != "pass"), None)
    return Probe(failed is None, "pass" if failed is None else failed, tuple(results))


def _operator_es_call(client: Any, action: Callable[[Any], Any]) -> Any:
    """Cap each operator-only ES request without changing production clients."""
    check_budget()
    selected = client
    if budget_active():
        options = getattr(client, "options", None)
        if not callable(options):
            raise CapabilityError("external_e2e_es_deadline_unavailable")
        try:
            selected = options(
                request_timeout=budget_timeout(30.0), max_retries=0,
                retry_on_timeout=False,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise CapabilityError("external_e2e_es_deadline_unavailable") from exc
    result = action(selected)
    check_budget()
    return result


def probe_elasticsearch(client: Any, indexes: str | Sequence[str],
                        acceptance_search: Callable[[Any], bool]) -> Probe:
    try:
        if not _operator_es_call(client, lambda es: es.ping()):
            return Probe(False, "transport_unavailable")
        targets = [indexes] if isinstance(indexes, str) else list(indexes)
        for index in targets:
            if not _operator_es_call(client, lambda es: es.indices.exists(index=index)):
                return Probe(False, "index_missing")
            compatible = mapping_compatibility(
                _operator_es_call(client, lambda es: es.indices.get_mapping(index=index)), index)
            if not compatible.usable:
                return compatible
        check_budget()
        if not acceptance_search(client):
            return Probe(False, "dataset_incompatible")
        return Probe(True, "pass")
    except PreflightDeadlineExceeded:
        raise
    except PermissionError:
        return Probe(False, "access_failure")
    except Exception as exc:
        check_budget()
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


def validate_production_index_selectors(
    client: Any, acceptance_index: str, selectors: Sequence[str],
) -> Probe:
    """Prove production selectors cannot resolve to the acceptance fixture.

    Wildcard selectors are rejected because creating the fixture could make a
    previously non-matching wildcard match after validation. Existing aliases
    are resolved before any fixture mutation and checked for the same collision.
    """
    normalized = tuple(dict.fromkeys(str(value).strip() for value in selectors if str(value).strip()))
    if acceptance_index in normalized:
        return Probe(False, "acceptance_index_conflict")
    if any(value == "_all" or "*" in value or "?" in value for value in normalized):
        return Probe(False, "production_selector_unsafe")

    resolver = getattr(getattr(client, "indices", None), "resolve_index", None)
    if not callable(resolver):
        return Probe(False, "production_selector_unverified")

    for selector in normalized:
        try:
            response = _operator_es_call(
                client, lambda es: es.indices.resolve_index(name=selector))
        except PreflightDeadlineExceeded:
            raise
        except Exception as exc:
            check_budget()
            meta = getattr(exc, "meta", None)
            status = (getattr(exc, "status_code", None) or getattr(exc, "status", None)
                      or getattr(meta, "status", None))
            if status == 404:
                continue
            return _elasticsearch_exception_probe(exc)

        body = getattr(response, "body", response)
        if not isinstance(body, Mapping):
            return Probe(False, "production_selector_unverified")
        resolved: set[str] = set()
        for item in body.get("indices", ()) or ():
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                resolved.add(item["name"])
        for item in body.get("aliases", ()) or ():
            if isinstance(item, Mapping):
                resolved.update(
                    str(name) for name in (item.get("indices", ()) or ())
                    if isinstance(name, str)
                )
        for item in body.get("data_streams", ()) or ():
            if isinstance(item, Mapping):
                resolved.update(
                    str(name) for name in (item.get("backing_indices", ()) or ())
                    if isinstance(name, str)
                )
        if acceptance_index in resolved:
            return Probe(False, "acceptance_index_conflict")
    return Probe(True, "pass")


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
        if not _operator_es_call(client, lambda es: es.ping()):
            return Probe(False, "transport_unavailable")
        if not _operator_es_call(client, lambda es: es.indices.exists(index=index)):
            _operator_es_call(client, lambda es: es.indices.create(
                index=index,
                mappings=REQUIREMENT_E2E_MAPPING["mappings"],
            ))
        mapping_response = _operator_es_call(
            client, lambda es: es.indices.get_mapping(index=index))
        mapping_entry = mapping_response.get(index)
        mapping_meta = (
            (mapping_entry or {}).get("mappings", {}).get("_meta", {})
            if isinstance(mapping_entry, Mapping) else {}
        )
        if mapping_meta.get("requirement_e2e_fixture") != "v1":
            return Probe(False, "fixture_ownership_unverified")
        compatible = mapping_compatibility(mapping_response, index)
        if not compatible.usable:
            return compatible

        fixtures = MOCK_DOCS[REQUIREMENT_E2E_INDEX]
        for source in fixtures.values():
            validate_requirement_fixture(source)

        def read_fixture_state() -> tuple[int, set[str]] | Probe:
            """Never overwrite an unexpected document, even when counts match."""
            count_response = _operator_es_call(
                client, lambda es: es.count(index=index))
            count_body = getattr(count_response, "body", count_response)
            total = int((count_body or {}).get("count", -1))
            if total < 0 or total > len(fixtures):
                return Probe(False, "fixture_dataset_drift")

            response = _operator_es_call(
                client, lambda es: es.mget(index=index, ids=list(fixtures)))
            body = getattr(response, "body", response)
            docs = body.get("docs") if isinstance(body, Mapping) else None
            if not isinstance(docs, list) or len(docs) != len(fixtures):
                return Probe(False, "fixture_dataset_drift")
            seen: set[str] = set()
            present: set[str] = set()
            for entry in docs:
                if not isinstance(entry, Mapping):
                    return Probe(False, "fixture_dataset_drift")
                doc_id = entry.get("_id")
                # A concrete index identity is required: an alias or routed
                # backing index must never be mistaken for our owned fixture.
                if entry.get("_index") != index:
                    return Probe(False, "fixture_dataset_drift")
                if not isinstance(doc_id, str) or doc_id not in fixtures or doc_id in seen:
                    return Probe(False, "fixture_dataset_drift")
                seen.add(doc_id)
                if entry.get("found") is True:
                    if entry.get("_source") != fixtures[doc_id]:
                        return Probe(False, "fixture_dataset_drift")
                    present.add(doc_id)
                elif entry.get("found") is not False:
                    return Probe(False, "fixture_dataset_drift")
            # If the count exceeds the exact set of expected IDs, other IDs
            # are present. Refuse mutation and avoid hiding index pollution.
            if seen != set(fixtures) or total != len(present):
                return Probe(False, "fixture_dataset_drift")
            return total, present

        initial = read_fixture_state()
        if isinstance(initial, Probe):
            return initial
        _, present = initial
        for doc_id, source in fixtures.items():
            if doc_id in present:
                continue
            check_budget()
            # A parallel creator gets a 409 instead of us overwriting data.
            _operator_es_call(client, lambda es: es.index(
                index=index, id=doc_id, document=source,
                op_type="create", refresh="wait_for",
            ))

        final = read_fixture_state()
        if isinstance(final, Probe):
            return final
        total, present = final
        if total != len(fixtures) or present != set(fixtures):
            return Probe(False, "fixture_dataset_drift")
        return Probe(True, "pass")
    except PreflightDeadlineExceeded:
        raise
    except PermissionError:
        return Probe(False, "access_failure")
    except Exception as exc:
        check_budget()
        return _elasticsearch_exception_probe(exc, setup=True)


_LOCK = threading.Lock()
_PLAN: BackendPlan | None = None
# Admission for *new* verified E2E jobs. A recheck suspends this process's
# previously published plan; an already-running job is not forcibly canceled.
_PLAN_TRUSTED = True


def suspend_published_plan() -> None:
    """Fail closed for newly entering E2E jobs during operator revalidation."""
    global _PLAN_TRUSTED
    with _LOCK:
        if _PLAN is not None:
            _PLAN_TRUSTED = False


@dataclass
class _StagedBackendPlan:
    """Unpublished candidate visible only inside the operator request context."""
    candidate: BackendPlan | None = None


_STAGED_PLAN: ContextVar[_StagedBackendPlan | None] = ContextVar(
    "operator_e2e_staged_plan", default=None,
)


@contextmanager
def staged_plan_publication():
    """Only the operator handler opts in; normal E2E resolution is unchanged."""
    stage = _StagedBackendPlan()
    token = _STAGED_PLAN.set(stage)
    try:
        yield stage
    finally:
        _STAGED_PLAN.reset(token)


def publish_staged_plan(stage: _StagedBackendPlan) -> None:
    """Commit exactly once after complete, timely runtime-evidence success."""
    global _PLAN, _PLAN_TRUSTED
    if _STAGED_PLAN.get() is not stage:
        raise CapabilityError("external_capability_plan_stage_invalid")
    check_budget()
    if stage.candidate is None:
        # Existing plan may be suspended; do not silently complete without
        # a fresh candidate for this operator request.
        with _LOCK:
            if _PLAN is not None and not _PLAN_TRUSTED:
                raise CapabilityError("external_capability_plan_revalidation_required")
        return
    with _LOCK:
        check_budget()
        if _PLAN is not None and _PLAN != stage.candidate:
            raise CapabilityError("external_capability_plan_drift")
        _PLAN = stage.candidate
        _PLAN_TRUSTED = True
        stage.candidate = None


def frozen_plan(resolver: Callable[[str], BackendPlan] | None = None) -> BackendPlan | None:
    """Only a freshly validated local plan may authorize verified E2E jobs."""
    global _PLAN, _PLAN_TRUSTED
    # The verified worker's admission is an immutable per-job snapshot, even
    # if a new operator run suspends its process-wide authority or config drifts.
    # This context is only entered after provenance + initial admission checks.
    admitted = admitted_requirement_e2e_plan() if resolver is None else None
    if admitted is not None:
        return admitted
    mode = parse_mode(os.getenv("REQUIREMENT_E2E_EXTERNAL_MODE"))
    if mode is None:
        return None
    stage = _STAGED_PLAN.get()
    # Never block verified E2E worker threads behind a long operator probe.
    if resolver is None and stage is None:
        if _PLAN is None:
            raise CapabilityError("external_capability_plan_unresolved")
        if not _PLAN_TRUSTED:
            raise CapabilityError("external_capability_plan_revalidation_required")
    with _LOCK:
        if _PLAN is not None and _PLAN.requested_mode != mode:
            raise CapabilityError("external_capability_plan_frozen")
        if stage is not None:
            if stage.candidate is not None:
                if stage.candidate.requested_mode != mode:
                    raise CapabilityError("external_capability_plan_frozen")
                return stage.candidate
            if resolver is None:
                raise CapabilityError("external_capability_plan_revalidation_required"
                                      if _PLAN is not None else
                                      "external_capability_plan_unresolved")
            # Re-probe existing plans instead of echoing cached capabilities.
            # The Linux host lock serializes operator calls on the same host.
            candidate = resolver(mode)
            check_budget()
            if candidate.requested_mode != mode:
                raise CapabilityError("external_capability_plan_frozen")
            if _PLAN is not None and candidate != _PLAN:
                raise CapabilityError("external_capability_plan_drift")
            stage.candidate = candidate
            return candidate
        if _PLAN is not None:
            if not _PLAN_TRUSTED:
                raise CapabilityError("external_capability_plan_revalidation_required")
            return _PLAN
        if resolver is None:
            raise CapabilityError("external_capability_plan_unresolved")
        resolved = resolver(mode)
        check_budget()
        if resolved.requested_mode != mode:
            raise CapabilityError("external_capability_plan_frozen")
        # Maintain direct/non-HTTP caller compatibility. The authenticated
        # operator handler alone guarantees final evidence before publication.
        _PLAN = resolved
        _PLAN_TRUSTED = True
        return resolved


def install_plan(plan: BackendPlan) -> BackendPlan:
    global _PLAN, _PLAN_TRUSTED
    with _LOCK:
        # Test/bootstrap installation must not bypass an active operator
        # suspension of previously published E2E authority.
        if _PLAN is not None and not _PLAN_TRUSTED:
            raise CapabilityError("external_capability_plan_revalidation_required")
        if _PLAN is not None and _PLAN != plan:
            raise CapabilityError("external_capability_plan_frozen")
        _PLAN = plan
        _PLAN_TRUSTED = True
        return plan


def resolve_environment_plan(mode: str) -> BackendPlan:
    """Probe both real boundaries before selecting either E2E backend."""
    from agent.es.es_client import _build_es, _normalize_indexes
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
            [{"role": "user", "content": "Reply with READY."}],
            timeout=budget_timeout(10.0)))
        for name, model in direct_models.items()
    }
    # Operator-only READY probe: production Data Agent generation keeps its
    # separately configured model settings and does not inherit this limit.
    E2E_DATA_AGENT_PROBE_TIMEOUT_SECONDS = 30

    def data_agent_call() -> str:
        from smolagents import LiteLLMModel
        model_id = (ENV.data_agent_model_id if "/" in ENV.data_agent_model_id
                    else f"ollama_chat/{ENV.data_agent_model_id}")
        model = LiteLLMModel(model_id=model_id, api_base=ENV.model_base_url,
                             temperature=ENV.model_temperature,
                             timeout=budget_timeout(E2E_DATA_AGENT_PROBE_TIMEOUT_SECONDS),
                             num_retries=0)
        response = model.generate([{
            "role": "user",
            "content": [{"type": "text", "text": "Reply with READY."}],
        }])
        check_budget()
        return str(response.content or "")
    boundaries["data_agent"] = data_agent_call
    llm = probe_llm_boundaries(boundaries)
    topic_map = INDEX_CONFIG.get("topic_index_map", {})
    production_indexes = []
    protected_sources = [
        INDEX_CONFIG.get("default", []) or [],
        os.getenv("ES_INDEX") or "",
        *[(topic_cfg or {}).get("indexes", []) for topic_cfg in topic_map.values()],
    ]
    for raw in protected_sources:
        for index in _normalize_indexes(raw):
            if index not in production_indexes:
                production_indexes.append(index)

    check_budget()
    acceptance_index = requirement_e2e_es_index()
    try:
        es = _build_es()
        check_budget()
    except PreflightDeadlineExceeded:
        raise
    except Exception:
        check_budget()
        es_probe = Probe(False, "transport_unavailable")
    else:
        selector_probe = validate_production_index_selectors(
            es, acceptance_index, production_indexes,
        )
        if not selector_probe.usable:
            es_probe = selector_probe
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
                        response = _operator_es_call(
                            client, lambda es: es.search(index=acceptance_index, body=body))
                        body = getattr(response, "body", response)
                        if not (((body or {}).get("hits") or {}).get("hits") or []):
                            return False
                    return True
                es_probe = probe_elasticsearch(es, acceptance_index, acceptance_search)
    check_budget()
    return resolve_plan(mode, llm, es_probe)


def reset_plan_for_tests() -> None:
    global _PLAN, _PLAN_TRUSTED
    with _LOCK:
        _PLAN = None
        _PLAN_TRUSTED = True
