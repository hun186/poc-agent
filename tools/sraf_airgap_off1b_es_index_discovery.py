"""OFF-1B read-only SRAF Elasticsearch selector discovery and scoped diagnosis.

Separate from the legacy single-index Requirement Mapping diagnostic. Never
equate a Mapping observation with real RAG, Requirement, or airgap acceptance.
No index enumeration, wildcard expansion, document bodies or ES writes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.es.reference_text import get_reference_text_field  # noqa: E402
from agent.external_capabilities import _field, mapping_compatibility  # noqa: E402
from shared.runtime_provenance import index_config_paths  # noqa: E402
from tools import sraf_airgap_off1b_es_https_mapping as transport  # noqa: E402
from tools.sraf_airgap_off1b_auto import (  # noqa: E402
    MODE, _effective_runtime_config, _parse_endpoint,
)

SCHEMA = "sraf_airgap_off1b_es_index_discovery_v1"
MAX_SELECTORS = 12
MAX_YAML_BYTES = 256 * 1024
MAX_RESOLVED_TARGETS = 8


def _literals(value: object) -> list[str]:
    """Normalize loader-style comma lists; reject unsafe selectors entirely."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        for part in item.split(","):
            name = transport._configured_index(part.strip())
            if name and name not in result:
                result.append(name)
    return result


def discover(root: Path, cfg: dict[str, str]) -> tuple[list[dict[str, object]], list[str]]:
    """Reproduce index_loader's selected files + additive topic merge safely.

    Effective OS/dotenv config comes from the same OFF-1B bootstrap. This
    inspector does not import INDEX_CONFIG because that singleton prints paths
    and the complete merged internal index configuration on import.
    """
    errors: list[str] = []
    topics: dict[str, list[str]] = {}
    defaults: list[str] = []
    for path in index_config_paths(root, cfg, selector_base=root):
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
                errors.append("index_config_outside_trusted_root")
                continue
            if path.is_symlink() or resolved.stat().st_size > MAX_YAML_BYTES:
                errors.append("index_config_unsafe")
                continue
            data = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                errors.append("index_config_invalid")
                continue
            topic_map = data.get("topic_index_map", {})
            if not isinstance(topic_map, dict):
                errors.append("index_config_invalid")
                continue
            for topic, definition in topic_map.items():
                if not isinstance(topic, str) or not isinstance(definition, dict):
                    errors.append("index_config_invalid")
                    continue
                new = _literals(definition.get("indexes"))
                old = topics.get(topic, [])
                topics[topic] = list(dict.fromkeys(old + new))
            if "default_indexes" in data:
                defaults = _literals(data["default_indexes"])
        except FileNotFoundError:
            # Runtime index_loader skips absent optional environment YAML files.
            if cfg.get("INDEXES_CONFIG") or cfg.get("INDEX_CONFIG") or cfg.get("INDEXES_CONFIGS"):
                errors.append("index_config_unavailable")
        except (OSError, ValueError, yaml.YAMLError, UnicodeError):
            errors.append("index_config_invalid")

    # Runtime es_client.init_index_cache reads ES_INDEX, default_indexes, and
    # the additive topic_index_map. ES_INDEX alone is not proof of actual use.
    explicit_default = _literals(cfg.get("ES_INDEX"))
    candidate_defaults = explicit_default if explicit_default else defaults
    selected: dict[str, set[str]] = {}
    for idx in candidate_defaults:
        selected.setdefault(idx, set()).add("default_selector")
    for names in topics.values():
        for idx in names:
            selected.setdefault(idx, set()).add("topic_selector")

    fixture = _literals(cfg.get("REQUIREMENT_E2E_ES_INDEX"))
    # E2E defaults are intentionally NOT auto-created or guessed by OFF-1B.
    for idx in fixture:
        selected.setdefault(idx, set()).add("e2e_fixture")
    if cfg.get("REQUIREMENT_E2E_ES_INDEX") and not fixture:
        errors.append("e2e_selector_invalid")

    entries: list[dict[str, object]] = []
    for idx, evidence in selected.items():
        conflict = "e2e_fixture" in evidence and len(evidence) > 1
        if conflict:
            role = "UNRESOLVED"
            reason = "acceptance_index_conflict"
        elif "e2e_fixture" in evidence:
            # Only a dedicated explicitly configured selector earns this role.
            role, reason = "E2E_FIXTURE", "explicit_e2e_selector"
        elif "topic_selector" in evidence and "default_selector" in evidence:
            role, reason = "ACTIVE_REQUIRED", "configured_default_and_topic"
        elif "topic_selector" in evidence:
            role, reason = "ACTIVE_OPTIONAL", "configured_topic_selector"
        else:
            # May be a legacy value, but no evidence yet that it is retired.
            role, reason = "UNRESOLVED", "default_selector_usage_unverified"
        entries.append({
            "_name": idx, "role": role, "role_reason": reason,
            "_conflict": conflict, "source_count": len(evidence),
        })
    if len(entries) > MAX_SELECTORS:
        errors.append("selector_inspection_limit")
        entries = entries[:MAX_SELECTORS]
    if not entries:
        errors.append("no_verified_selectors")
    return entries, sorted(set(errors))


def _mapping_profile(body: bytes, selector: str, role: str) -> tuple[str, str, str]:
    """One bounded Mapping response; profile-specific, with no false feature PASS."""
    if len(body) > transport.MAX_MAPPING_BODY:
        return "FAIL", "es_mapping_response_oversized", "NOT_TESTED"
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or len(data) != 1:
            return "NOT_VERIFIED", "es_mapping_target_ambiguous", "NOT_TESTED"
        one = next(iter(data.values()))
        if not isinstance(one, dict):
            raise ValueError("invalid")
        mapping = one.get("mappings")
        if not isinstance(mapping, dict) or not transport._mapping_containers_valid(mapping):
            raise ValueError("invalid")
        if role == "E2E_FIXTURE":
            probe = mapping_compatibility(data, selector)
            return (("PASS", "e2e_mapping_compatible", "NOT_TESTED") if probe.usable
                    else ("FAIL", "e2e_mapping_incompatible", "NOT_TESTED"))

        # RAG's configured reference text is the essential query anchor.
        text_field = _field(mapping, get_reference_text_field())
        subject = _field(mapping, "communication.subject")
        if not text_field and not subject:
            return "WARN", "rag_reference_fields_missing", "NOT_TESTED"
        if text_field and text_field.get("type") not in (None, "text", "match_only_text"):
            return "WARN", "rag_reference_field_type_unverified", "NOT_TESTED"

        # Multidim is a separate optional capability, NOT the default RAG
        # contract and NOT a Requirement E2E fixture.
        multidim = _field(mapping, "multidim_event_json")
        if multidim is None:
            return "PASS", "rag_mapping_baseline", "NOT_TESTED"
        event = _field(mapping, "multidim_event_json.Event")
        timeline = _field(mapping, "multidim_event_json.Event_Timeline")
        evidence = _field(mapping, "multidim_event_json.evidence_snippets")
        if (multidim.get("type") != "nested" or not event
                or event.get("type") != "nested"
                or not timeline or timeline.get("type") != "nested"
                or not evidence or evidence.get("type") != "nested"
                or not _field(mapping, "multidim_event_json.Event.event_id")
                or not _field(mapping, "multidim_event_json.Event_Timeline.time_iso")):
            return "WARN", "rag_ok_multidim_mapping_partial", "NOT_TESTED"
        return "PASS", "rag_and_multidim_mapping_baseline", "NOT_TESTED"
    except (ValueError, TypeError, AttributeError, KeyError,
            RecursionError, UnicodeError):
        return "FAIL", "es_mapping_response_invalid", "NOT_TESTED"


def _resolve_payload(body: bytes, selector: str) -> tuple[str, str, int]:
    """Only named index/alias targets. No hidden wildcard or giant expansions."""
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("invalid")
        resolved: set[str] = set()
        for key in ("indices", "aliases", "data_streams"):
            group = payload.get(key, [])
            if not isinstance(group, list):
                raise ValueError("invalid")
            for item in group:
                if not isinstance(item, dict):
                    raise ValueError("invalid")
                if key == "indices":
                    names = [item.get("name")]
                else:
                    names = item.get("indices" if key == "aliases" else "backing_indices", [])
                if not isinstance(names, list):
                    names = [names] if key == "indices" else []
                for name in names:
                    if not isinstance(name, str) or not transport._configured_index(name):
                        raise ValueError("invalid")
                    resolved.add(name)
                    if len(resolved) > MAX_RESOLVED_TARGETS:
                        return "NOT_VERIFIED", "es_selector_expansion_bounded", len(resolved)
        if not resolved:
            return "NOT_VERIFIED", "es_selector_resolution_empty", 0
        if len(resolved) != 1:
            return "WARN", "es_selector_multiple_targets", len(resolved)
        return "PASS", "es_selector_single_target", 1
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return "NOT_VERIFIED", "es_selector_response_invalid", 0


def observe(cfg: dict[str, str], *, root: Path = PROJECT_ROOT,
            no_network: bool = False, strict_ip_san: bool = False,
            read_only_search: bool = False,
            show_names: bool = False) -> dict[str, object]:
    entries, config_errors = discover(root, cfg)
    for i, item in enumerate(entries, 1):
        item["selector_id"] = f"index_{i:02d}"
        if show_names:
            item["selector_name"] = item["_name"]
        item["index_probe"] = "NOT_TESTED"
        item["mapping_probe"] = "NOT_TESTED"
        item["search_probe"] = "NOT_TESTED"
        item["feature_acceptance"] = "NOT_TESTED"
        item["reason"] = item["role_reason"]
    endpoint, host = _parse_endpoint(cfg.get("ES_URL"))
    summary: dict[str, object] = {
        "schema": SCHEMA, "mode": MODE,
        "network_mode": "CONFIG_ONLY" if no_network else "PRIVATE_IPV4_TLS_GET_ONLY",
        "configuration": endpoint["configuration"],
        "tls_validation": "NOT_TESTED", "auth": "NOT_VERIFIED",
        "identity_warning": False, "feature_acceptance": "NOT_TESTED",
        "config_warnings": config_errors, "results": entries,
        "independent_es_checks_continued": 0, "reason": "configuration_only",
    }
    # Never leak raw index names by accident in the default report.
    for item in entries:
        del item["role_reason"]
        del item["source_count"]
    def finish():
        for item in entries:
            item.pop("_name", None)
            item.pop("_conflict", None)
        return summary
    if no_network:
        return finish()
    if endpoint["configuration"] != "RESOLVED" or endpoint["scheme"] != "https" or host is None:
        summary["reason"] = "es_https_private_endpoint_unavailable"
        return finish()
    username, password = cfg.get("ES_USERNAME") or "", cfg.get("ES_PASSWORD") or ""
    ca = transport._trusted_ca_file(root)
    if not username or not password or ":" in username or ca is None:
        summary["reason"] = "es_credentials_or_ca_unavailable"
        return finish()
    if not entries:
        summary["reason"] = "es_selectors_unavailable"
        return finish()
    port = int(endpoint["port"])
    warn = not strict_ip_san

    def get(path: str):
        return transport._https_get(host, port, path, username, password, ca,
                                    warn_only_ip_san=warn)

    def tls(reason: str):
        if reason in ("https_response_ca_only_ip_san_mismatch",
                      "es_https_transport_unavailable_ip_san_mismatch"):
            summary["identity_warning"] = True
            summary["tls_validation"] = "WARN"
        elif reason == "es_tls_identity_unverified":
            summary["tls_validation"] = "FAIL"
        elif reason == "https_response_received" and summary["tls_validation"] == "NOT_TESTED":
            summary["tls_validation"] = "PASS"

    status, body, reason = get("/")
    tls(reason)
    if status != 200:
        summary["reason"] = "es_root_unverified"
        return finish()
    try:
        root_info = json.loads(body)
        if (not isinstance(root_info, dict) or not isinstance(root_info.get("cluster_name"), str)
                or not isinstance(root_info.get("version"), dict)
                or not isinstance(root_info["version"].get("number"), str)):
            raise ValueError("invalid")
    except (ValueError, TypeError, UnicodeError):
        summary["reason"] = "es_root_identity_unverified"
        return finish()
    auth_status, auth_body, auth_reason = get("/_security/_authenticate")
    tls(auth_reason)
    if auth_status != 200 or not transport._verified_basic_principal(auth_body, username):
        summary["reason"] = "es_principal_unverified"
        return finish()
    summary["reason"] = "bounded_read_only_index_diagnosis"
    # A positive principal does not prove the supplied password was applied;
    # no negative password challenge is issued by this scanner.
    for item in entries:
        if summary["tls_validation"] == "FAIL":
            # Do not continue credential-bearing reads after a hard TLS error.
            item["reason"] = "blocked_by_tls_failure"
            continue
        if item["_conflict"]:
            item["index_probe"] = "FAIL"
            item["reason"] = "acceptance_index_conflict"
            continue
        selector = item["_name"]
        status, body, reason = get(f"/_resolve/index/{selector}")
        tls(reason)
        if summary["tls_validation"] == "FAIL":
            item["index_probe"] = "NOT_VERIFIED"
            item["reason"] = "es_tls_identity_unverified"
            continue
        if status == 404:
            # Under SAN warning mode even 404 may be from the wrong peer.
            if summary["identity_warning"]:
                item["index_probe"] = "NOT_VERIFIED"
                item["reason"] = "index_missing_identity_unverified"
            else:
                item["index_probe"] = ("FAIL" if item["role"] == "ACTIVE_REQUIRED" else "WARN")
                item["reason"] = ("required_index_missing" if item["role"] == "ACTIVE_REQUIRED"
                                  else "optional_or_unresolved_index_missing")
                if item["role"] == "ACTIVE_REQUIRED":
                    item["role"] = "MISSING_REQUIRED"
            continue
        if status != 200:
            item["index_probe"] = "NOT_VERIFIED"
            item["reason"] = "es_selector_resolution_unavailable"
            continue
        rp, rr, count = _resolve_payload(body or b"", selector)
        item["index_probe"], item["reason"], item["resolved_count"] = rp, rr, count
        if rp != "PASS":
            continue
        status, body, reason = get(f"/{selector}/_mapping")
        tls(reason)
        if summary["tls_validation"] == "FAIL":
            item["mapping_probe"] = "NOT_VERIFIED"
            item["reason"] = "es_tls_identity_unverified"
            continue
        if status == 200:
            mapped, why, _ = _mapping_profile(body or b"", selector, item["role"])
            if summary["identity_warning"] and mapped == "PASS":
                mapped, why = "WARN", "mapping_identity_unverified"
            item["mapping_probe"], item["reason"] = mapped, why
        else:
            item["mapping_probe"] = "NOT_VERIFIED"
            item["reason"] = "es_mapping_unavailable"
        # Read-only query is opt-in, strict TLS only; no hits or sources.
        if (read_only_search and strict_ip_san
                and summary["tls_validation"] == "PASS"
                and item["mapping_probe"] in ("PASS", "WARN")):
            search_status, _, sr = get(
                f"/{selector}/_search?size=0&track_total_hits=false")
            tls(sr)
            item["search_probe"] = ("PASS" if search_status == 200 and
                                    summary["tls_validation"] == "PASS" else "NOT_VERIFIED")
            summary["independent_es_checks_continued"] += 1
    if summary["identity_warning"]:
        # A later GET can discover SAN mismatch after earlier clean responses.
        for item in entries:
            if item["mapping_probe"] == "PASS":
                item["mapping_probe"] = "WARN"
                item["reason"] = "mapping_identity_unverified"
            if item["search_probe"] == "PASS":
                item["search_probe"] = "NOT_VERIFIED"
    return finish()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--strict-ip-san", action="store_true")
    parser.add_argument("--read-only-search", action="store_true",
                        help="Optional size=0 ES search, strict TLS identity only")
    parser.add_argument("--show-index-names", action="store_true",
                        help="Include sensitive selector names on local operator stdout")
    args = parser.parse_args(argv)
    if args.read_only_search and not args.strict_ip_san:
        parser.error("--read-only-search requires --strict-ip-san")
    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}))
        return 2
    try:
        cfg = _effective_runtime_config(PROJECT_ROOT)
        result = observe(cfg, no_network=args.no_network,
                         strict_ip_san=args.strict_ip_san,
                         read_only_search=args.read_only_search,
                         show_names=args.show_index_names)
    except Exception:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "operator_diagnostic_unavailable"}))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    if result["tls_validation"] == "FAIL" or any(
        item["index_probe"] == "FAIL" or item["mapping_probe"] == "FAIL"
        for item in result["results"]
    ):
        return 1
    # Mapping/schema/config evidence alone can never prove FULL_LIVE.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
