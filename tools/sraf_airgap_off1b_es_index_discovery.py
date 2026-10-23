"""OFF-1B operator-only configured ES selector discovery (partial evidence only).

Inventory selected runtime config, NEVER enumerate the cluster. Reuse OFF-1B's
bounded private-IPv4 CA-verified HTTPS transport and protected auth preflight.
Neither static mapping nor an HTTP success proves RAG / FULL_LIVE acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.external_capabilities import mapping_compatibility  # noqa: E402
from agent.es.reference_text import (  # noqa: E402
    DEFAULT_REFERENCE_TEXT_FIELD, _VALID_FIELD_PATH,
)
from shared.runtime_provenance import index_config_paths  # noqa: E402
from tools.sraf_airgap_off1b_auto import (  # noqa: E402
    MODE, _effective_runtime_config,
)
from tools import sraf_airgap_off1b_es_https_mapping as es  # noqa: E402

SCHEMA = "sraf_airgap_off1b_es_index_discovery_v1"
MAX_CONFIG_FILES = 8
MAX_CONFIG_BYTES = 256 * 1024
MAX_SELECTORS = 24
MAX_NETWORK_SELECTORS = 12


def _indexes(value: Any) -> list[str]:
    """Mirror es_client/index_loader's comma expansion and ordered dedup."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item is None:
            continue
        # Mirror config.index_loader._normalize_indexes: YAML scalars
        # (including numeric index names) are stringified before splitting.
        value_text = str(item).strip()
        if not value_text:
            continue
        for name in value_text.split(","):
            name = name.strip()
            if name and name not in seen:
                out.append(name)
                seen.add(name)
    return out


def _load_declarations(root: Path, cfg: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Read only the loader-selected files; honor additive topic + replace default.

    Do not import config.index_loader: import would eagerly load/print runtime
    configuration, including operator-managed index names, to general logs.
    """
    notes: list[str] = []
    merged: dict[str, Any] = {"topic_index_map": {}, "default_indexes": []}
    paths = index_config_paths(root, cfg, selector_base=root)
    # Runtime accepts explicitly selected absolute paths outside the checkout.
    # The implicit built-in defaults remain checkout-local. External files
    # are not evidence of release provenance, even if they can be diagnosed.
    explicit_override = bool(
        cfg.get("INDEXES_CONFIG") or cfg.get("INDEX_CONFIG")
        or cfg.get("INDEXES_CONFIGS")
    )
    if len(paths) > MAX_CONFIG_FILES:
        return merged, ["index_config_file_budget_exceeded"]
    for path in paths:
        try:
            if not path.is_relative_to(root.resolve()):
                if not explicit_override:
                    notes.append("index_config_outside_checkout_not_selected")
                    continue
                notes.append("external_index_config_not_release_attested")
            if path.is_symlink():
                notes.append("index_config_symlink_not_read")
                continue
            if not path.exists():
                continue
            if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
                notes.append("index_config_not_read")
                continue
            with path.open("r", encoding="utf-8") as stream:
                data = yaml.safe_load(stream)
            # The runtime loader uses yaml.safe_load(...) or {}. Empty
            # documents are harmless, but truthy non-object roots raise
            # during _merge_index_configs() and invalidate the whole load.
            if not data:
                data = {}
            if not isinstance(data, dict):
                notes.append("index_config_invalid_root")
                return {"topic_index_map": {}, "default_indexes": []}, sorted(set(notes))
            if "default_index" in data and "default_indexes" not in data:
                # Runtime index_loader ignores this singular legacy spelling.
                notes.append("legacy_default_index_key_ignored")
            topics = data.get("topic_index_map")
            if isinstance(topics, dict):
                for topic, declared in topics.items():
                    if not isinstance(topic, str):
                        notes.append("topic_config_invalid")
                        continue
                    if not isinstance(declared, dict):
                        # Runtime _merge_index_configs replaces this topic,
                        # even with a non-dict. Do not probe its old selectors.
                        merged["topic_index_map"][topic] = declared
                        notes.append("topic_config_invalid")
                        continue
                    old = merged["topic_index_map"].get(topic, {})
                    if not isinstance(old, dict):
                        old = {}
                    combined = dict(old)
                    combined.update(declared)
                    if "indexes" in declared:
                        combined["indexes"] = _indexes(
                            _indexes(old.get("indexes")) + _indexes(declared["indexes"])
                        )
                    merged["topic_index_map"][topic] = combined
            elif topics is not None:
                notes.append("topic_config_invalid")
            if "default_indexes" in data:
                merged["default_indexes"] = _indexes(data["default_indexes"])
        except yaml.YAMLError:
            # Runtime fails on invalid YAML syntax as well; never retain
            # stale selectors from previous files after a parse failure.
            notes.append("index_config_yaml_invalid")
            return {"topic_index_map": {}, "default_indexes": []}, sorted(set(notes))
        except (OSError, UnicodeError, ValueError):
            notes.append("index_config_unavailable")
    return merged, sorted(set(notes))


def discover(cfg: Mapping[str, str], root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover declared call targets, not every index present on the cluster."""
    merged, notes = _load_declarations(root.resolve(), cfg)
    # A failed runtime config load has no effective selectors. Do not probe
    # prior YAML defaults, even when a separate ES_INDEX was provided.
    if "index_config_invalid_root" in notes or "index_config_yaml_invalid" in notes:
        return [], notes
    targets: dict[str, dict[str, Any]] = {}

    def add(name: str, role: str, source: str) -> None:
        if len(targets) >= MAX_SELECTORS and name not in targets:
            if "index_selector_budget_exceeded" not in notes:
                notes.append("index_selector_budget_exceeded")
            return
        if es._configured_index(name) is None:
            if "index_selector_unsafe_or_invalid" not in notes:
                notes.append("index_selector_unsafe_or_invalid")
            return
        entry = targets.setdefault(name, {
            "_selector": name, "classification": role, "sources": [],
        })
        if role == "ACTIVE_REQUIRED" and entry["classification"] != "E2E_FIXTURE":
            entry["classification"] = role
        if source not in entry["sources"]:
            entry["sources"].append(source)

    explicit = _indexes(cfg.get("ES_INDEX"))
    defaults = _indexes(merged["default_indexes"])
    chosen = explicit or defaults
    if not chosen:
        # Runtime currently falls back to a hard-coded development default.
        # Do NOT infer it is a valid or required production index.
        notes.append("runtime_default_fallback_not_attested")
    for n, item in enumerate(chosen):
        add(item, "ACTIVE_REQUIRED" if n == 0 else "ACTIVE_OPTIONAL",
            "environment_default" if explicit else "configured_default")
    for topic in merged["topic_index_map"].values():
        if isinstance(topic, dict):
            for item in _indexes(topic.get("indexes")):
                add(item, "ACTIVE_OPTIONAL", "topic_index_map")
    fixture = (cfg.get("REQUIREMENT_E2E_ES_INDEX") or "").strip()
    if fixture:
        if es._configured_index(fixture) is None:
            notes.append("e2e_selector_invalid")
        elif fixture in targets:
            notes.append("e2e_production_selector_conflict")
        else:
            add(fixture, "E2E_FIXTURE", "explicit_e2e_selector")
    for record in targets.values():
        record["sources"].sort()
    return list(targets.values()), sorted(set(notes))


def _field(mapping: Mapping[str, Any], dotted: str) -> Mapping[str, Any] | None:
    node: Any = mapping.get("properties", {})
    for name in dotted.split("."):
        if not isinstance(node, dict):
            return None
        field = node.get(name)
        if not isinstance(field, dict):
            return None
        node = field.get("properties", field.get("fields", {}))
    return field


def inspect_mapping(body: bytes, selector: str, role: str,
                    reference_field: str) -> tuple[str, str, str, str]:
    """Mapping-only status, reason, resolved-selector kind and multidim shape."""
    try:
        if len(body) > es.MAX_MAPPING_BODY:
            return "FAIL", "es_mapping_response_oversized", "UNRESOLVED", "NOT_TESTED"
        payload = json.loads(body)
        if not isinstance(payload, dict) or not payload:
            raise ValueError("invalid")
        if len(payload) != 1:
            return "SKIP", "es_mapping_target_ambiguous", "MULTIPLE", "NOT_TESTED"
        concrete_name, entry = next(iter(payload.items()))
        if not isinstance(concrete_name, str) or not isinstance(entry, dict):
            raise ValueError("invalid")
        mapping = entry.get("mappings")
        if not isinstance(mapping, dict) or not es._mapping_containers_valid(mapping):
            raise ValueError("invalid")
        resolved = "DIRECT" if concrete_name == selector else "ALIAS_OR_DATA_STREAM"
        if role == "E2E_FIXTURE":
            probe = mapping_compatibility(payload, selector)
            return ("PASS", "e2e_mapping_subset_compatible", resolved, "NOT_TESTED") if probe.usable else (
                "FAIL", "e2e_mapping_incompatible", resolved, "NOT_TESTED"
            )
        if not reference_field or _VALID_FIELD_PATH.fullmatch(reference_field) is None:
            return "SKIP", "reference_text_selector_invalid", resolved, "NOT_TESTED"
        ref = _field(mapping, reference_field)
        status = "PASS" if ref is not None and ref.get("type") in ("text", "keyword") else "FAIL"
        reason = "rag_reference_mapping_compatible" if status == "PASS" else "rag_reference_mapping_missing"
        multidim = _field(mapping, "multidim_event_json")
        if multidim is None:
            md_status = "NOT_APPLICABLE"
        elif multidim.get("type") != "nested":
            md_status = "WARN"
        else:
            child = _field(mapping, "multidim_event_json.Event")
            md_status = "PASS" if child is not None and child.get("type") == "nested" else "WARN"
        return status, reason, resolved, md_status
    except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError):
        return "FAIL", "es_mapping_response_invalid", "UNRESOLVED", "NOT_TESTED"


def diagnose(cfg: dict[str, str], root: Path, *, no_network: bool = False,
             strict_ip_san: bool = False, show_index_names: bool = False
             ) -> dict[str, Any]:
    targets, notes = discover(cfg, root)
    observations: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "schema": SCHEMA, "mode": MODE, "feature_acceptance": "NOT_TESTED",
        "selector_discovery": ("INVALID_CONFIG" if (
            "index_config_invalid_root" in notes or
            "index_config_yaml_invalid" in notes) else "CONFIGURED_TARGETS_ONLY"),
        "legacy_classification": "UNRESOLVED_WITHOUT_EXECUTION_EVIDENCE",
        "notes": notes, "base_probe": {"https_probe": "SKIP", "auth": "NOT_TESTED",
                                       "tls_validation": "NOT_TESTED"},
        "results": observations,
    }
    for i, target in enumerate(targets, 1):
        obs = {
            "check_id": f"ES-IDX-{i:02d}",
            "classification": target["classification"],
            "sources": target["sources"],
            "mapping_probe": "NOT_TESTED",
            "selector_resolution": "NOT_TESTED",
            "multidim_mapping": "NOT_TESTED",
            "query_probe": "NOT_TESTED", "feature_acceptance": "NOT_TESTED",
            "reason": "network_disabled" if no_network else "not_probed",
        }
        if show_index_names:
            obs["selector"] = target["_selector"]
        observations.append(obs)
    if no_network or not targets:
        report["summary"] = dict(Counter(item["mapping_probe"] for item in observations))
        return report

    # Existing, reviewed root/Basic-principal CA/private IPv4 policy; opt in
    # to skipping only the old (E2E-specific) single-selector mapping gate.
    first = targets[0]["_selector"]
    base = es._observe(
        {**cfg, "ES_INDEX": first}, no_network=False, root=root,
        warn_only_ip_san=not strict_ip_san, skip_mapping=True,
    )
    report["base_probe"] = {
        key: base[key] for key in (
            "configuration", "https_probe", "auth", "tls_validation",
            "identity_warning", "reason", "feature_acceptance"
        )
    }
    # No selector probes until protected principal is positively observed.
    # In the existing default profile auth stays NOT_VERIFIED, by design.
    if base["https_probe"] != "PASS" or base["reason"] != "es_mapping_delegated_to_discovery":
        for obs in observations:
            obs["reason"] = "es_base_preflight_not_satisfied"
        report["summary"] = dict(Counter(item["mapping_probe"] for item in observations))
        return report

    endpoint, host = es._parse_endpoint(cfg.get("ES_URL"))
    ca = es._trusted_ca_file(root)
    if host is None or ca is None:
        for obs in observations:
            obs["reason"] = "es_base_preflight_not_satisfied"
        report["summary"] = dict(Counter(item["mapping_probe"] for item in observations))
        return report
    port = int(endpoint["port"])
    user, password = cfg["ES_USERNAME"], cfg["ES_PASSWORD"]
    configured_reference = (cfg.get("SRA_REFERENCE_TEXT_FIELD") or "").strip()
    reference = (configured_reference if configured_reference and
                 _VALID_FIELD_PATH.fullmatch(configured_reference)
                 else DEFAULT_REFERENCE_TEXT_FIELD)
    configured_fixture = (cfg.get("REQUIREMENT_E2E_ES_INDEX") or "").strip()
    for i, (target, obs) in enumerate(zip(targets, observations)):
        if i >= MAX_NETWORK_SELECTORS:
            obs["mapping_probe"] = "SKIP"
            obs["reason"] = "selector_network_budget_exceeded"
            continue
        name = target["_selector"]
        if strict_ip_san:
            status, body, reason = es._https_get(
                host, port, f"/{name}/_mapping", user, password, ca)
        else:
            status, body, reason = es._https_get(
                host, port, f"/{name}/_mapping", user, password, ca,
                warn_only_ip_san=True)
        # A later Mapping GET can reach a different CA-signed TLS peer from
        # the root/auth preflight. Record its SAN warning BEFORE any local
        # early exit (including fixture alias conflicts) can bypass it.
        if reason in ("https_response_ca_only_ip_san_mismatch",
                      "es_https_transport_unavailable_ip_san_mismatch"):
            report["base_probe"]["identity_warning"] = True
            report["base_probe"]["tls_validation"] = "WARN"
        if status == 404:
            obs["mapping_probe"] = (
                "FAIL" if target["classification"] == "ACTIVE_REQUIRED" else "WARN")
            obs["reason"] = "required_index_missing" if (
                target["classification"] == "ACTIVE_REQUIRED") else "optional_index_missing"
        elif status in (401, 403):
            obs["mapping_probe"] = "NOT_VERIFIED"
            obs["reason"] = "es_mapping_access_denied"
        elif status is None:
            obs["mapping_probe"] = "NOT_VERIFIED"
            obs["reason"] = reason
            if reason == "es_tls_identity_unverified":
                report["base_probe"]["tls_validation"] = "FAIL"
                report["base_probe"]["auth"] = "NOT_VERIFIED"
                # Repeated Basic transmissions to an untrusted peer are unsafe.
                for remaining in observations[i + 1:]:
                    remaining["reason"] = "es_tls_preflight_blocked"
                break
        elif status != 200:
            obs["mapping_probe"] = "NOT_VERIFIED"
            obs["reason"] = "es_mapping_http_unexpected"
        else:
            # Map an alias' concrete target before treating the selector as
            # production-safe. A literal-name-only fixture check is insufficient.
            # Do not expose either the alias or the concrete backing index.
            try:
                resolved_payload = json.loads(body or b"")
            except (TypeError, ValueError, UnicodeError, RecursionError):
                resolved_payload = None
            if (target["classification"] != "E2E_FIXTURE"
                    and configured_fixture
                    and isinstance(resolved_payload, dict)
                    and configured_fixture in resolved_payload):
                obs["mapping_probe"] = "FAIL"
                obs["selector_resolution"] = "FIXTURE_CONFLICT"
                obs["reason"] = "e2e_production_selector_conflict"
            else:
                verdict, verdict_reason, resolution, md = inspect_mapping(
                    body or b"", name, target["classification"], reference)
                obs["selector_resolution"] = resolution
                obs["multidim_mapping"] = md
                obs["mapping_probe"] = verdict
                obs["reason"] = verdict_reason
                if verdict == "FAIL" and target["classification"] == "ACTIVE_OPTIONAL":
                    obs["mapping_probe"] = "WARN"
        # Any identity-unverified peer supplies advisory-only evidence:
        # neither a positive nor a negative Mapping verdict can be trusted.
        # Preserve local security/configuration failures (including strict SAN
        # rejection) as FAIL; only downgrade response-derived verdicts.
        if report["base_probe"]["identity_warning"] and obs["mapping_probe"] in ("PASS", "FAIL"):
            obs["mapping_probe"] = "WARN"
            obs["reason"] = "es_mapping_identity_unverified"
    report["summary"] = dict(Counter(item["mapping_probe"] for item in observations))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--strict-ip-san", action="store_true")
    parser.add_argument("--show-index-names", action="store_true",
                        help="Explicit operator-only local output; never enable in shared logs.")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}))
        return 2
    try:
        cfg = _effective_runtime_config(PROJECT_ROOT)
        report = diagnose(cfg, PROJECT_ROOT, no_network=args.no_network,
                          strict_ip_san=args.strict_ip_san,
                          show_index_names=args.show_index_names)
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        if (report.get("selector_discovery") == "INVALID_CONFIG" or
            report["base_probe"].get("configuration") == "INVALID" or
            report["base_probe"]["https_probe"] == "FAIL" or
            report["base_probe"].get("auth") == "FAIL" or
            report["base_probe"]["tls_validation"] == "FAIL" or
            any(item["mapping_probe"] == "FAIL" for item in report["results"])):
            return 1
        return 2  # Always PARTIAL_ONLY_NOT_ACCEPTANCE.
    except Exception:
        # Operator status is intentionally redacted, including unexpected errors.
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "index_discovery_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
