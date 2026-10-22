"""OFF-1B operator-only configured ES selector discovery (partial evidence only).

Inventory selected runtime config, NEVER enumerate the cluster. Reuse OFF-1B's
bounded private-IPv4 CA-verified HTTPS transport and protected auth preflight.
Neither static mapping nor an HTTP success proves RAG / FULL_LIVE acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.external_capabilities import mapping_compatibility  # noqa: E402
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
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        for name in item.split(","):
            name = name.strip()
            if name and name not in out:
                out.append(name)
    return out


def _load_declarations(root: Path, cfg: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Read only the loader-selected files; honor additive topic + replace default.

    Do not import config.index_loader: import would eagerly load/print runtime
    configuration, including operator-managed index names, to general logs.
    """
    notes: list[str] = []
    merged: dict[str, Any] = {"topic_index_map": {}, "default_indexes": []}
    paths = index_config_paths(root, cfg, selector_base=root)
    if len(paths) > MAX_CONFIG_FILES:
        return merged, ["index_config_file_budget_exceeded"]
    for path in paths:
        try:
            # Restrict this operator tool to the attested repository root.
            path.relative_to(root.resolve())
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
            if not isinstance(data, dict):
                notes.append("index_config_invalid")
                continue
            if "default_index" in data and "default_indexes" not in data:
                # Runtime index_loader ignores this singular legacy spelling.
                notes.append("legacy_default_index_key_ignored")
            topics = data.get("topic_index_map")
            if isinstance(topics, dict):
                for topic, declared in topics.items():
                    if not isinstance(topic, str) or not isinstance(declared, dict):
                        notes.append("topic_config_invalid")
                        continue
                    old = merged["topic_index_map"].get(topic, {})
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
        except (OSError, UnicodeError, yaml.YAMLError, ValueError):
            notes.append("index_config_unavailable")
    return merged, sorted(set(notes))


def discover(cfg: Mapping[str, str], root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover declared call targets, not every index present on the cluster."""
    merged, notes = _load_declarations(root.resolve(), cfg)
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
        if not reference_field or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", reference_field) is None:
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
        "selector_discovery": "CONFIGURED_TARGETS_ONLY",
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
    reference = cfg.get("SRA_REFERENCE_TEXT_FIELD") or "rawInfo.content"
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
            verdict, verdict_reason, resolution, md = inspect_mapping(
                body or b"", name, target["classification"], reference)
            obs["selector_resolution"] = resolution
            obs["multidim_mapping"] = md
            obs["mapping_probe"] = verdict
            obs["reason"] = verdict_reason
            if verdict == "FAIL" and target["classification"] == "ACTIVE_OPTIONAL":
                obs["mapping_probe"] = "WARN"
        if reason in ("https_response_ca_only_ip_san_mismatch",
                      "es_https_transport_unavailable_ip_san_mismatch") or base["identity_warning"]:
            report["base_probe"]["identity_warning"] = True
            report["base_probe"]["tls_validation"] = "WARN"
            if obs["mapping_probe"] == "PASS":
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
        if (report["base_probe"]["https_probe"] == "FAIL" or
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
