"""Operator-only, strict-TLS, GET-only news_test Event/Evidence date acceptance.

Run: bash scripts/sraf_event_time_readonly.sh
No CLI supplied: NO NETWORK. This checker never writes to ES, imports the
runtime ES client (which relaxes hostname validation), calls an LLM, or dumps
article text/credentials. PASS means only the observed read-only scope passed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCHEMA = "sraf_event_time_news_test_readonly_v1"
INDEX = "news_test"  # fixed literal: no wildcard, alias expansion or operator URL
MAX_SEARCH_PATH = 3072  # fit within ES default 4 KiB GET request line
SOURCE_FIELDS = [
    "uuid",
    "multidim_event_json.article_date_iso",
    "multidim_event_json.Event.event_id",
    "multidim_event_json.Event.time_iso",
    "multidim_event_json.Event.time_precision",
    "multidim_event_json.Event_Timeline.event_ids",
    "multidim_event_json.Event_Timeline.time_iso",
    "multidim_event_json.Event_Timeline.time_precision",
    "multidim_event_json.evidence_snippets.event_ids",
    "multidim_event_json.evidence_snippets.text",
]


class ObservationError(Exception):
    """Never include server payloads, endpoints or raw transport exceptions."""


def _properties(mapping_response: Any) -> tuple[dict, list[str]]:
    """Validate the specific two-level nested mapping needed by #395."""
    if not isinstance(mapping_response, dict) or len(mapping_response) != 1:
        return {}, ["mapping_target_not_unique"]
    if next(iter(mapping_response)) != INDEX:
        return {}, ["mapping_target_not_fixed_index"]
    entry = mapping_response[INDEX]
    if not isinstance(entry, dict):
        return {}, ["mapping_response_invalid"]
    node = ((entry.get("mappings") or {}).get("properties") or {}).get(
        "multidim_event_json"
    )
    if not isinstance(node, dict) or node.get("type") != "nested":
        return {}, ["multidim_not_nested"]
    props = node.get("properties")
    if not isinstance(props, dict):
        return {}, ["multidim_properties_missing"]
    errors: list[str] = []
    for child in ("Event", "Event_Timeline", "evidence_snippets"):
        item = props.get(child)
        if not isinstance(item, dict) or item.get("type") != "nested":
            errors.append(f"{child.lower()}_not_nested")
            continue
        child_props = item.get("properties")
        if not isinstance(child_props, dict):
            errors.append(f"{child.lower()}_properties_missing")
            continue
        required = (
            {"event_id": "keyword", "time_iso": "date",
             "time_precision": "keyword"} if child == "Event" else
            {"event_ids": "keyword", "time_iso": "date",
             "time_precision": "keyword"} if child == "Event_Timeline" else
            {"event_ids": "keyword", "text": "text"}
        )
        for field_name, expected_type in required.items():
            field = child_props.get(field_name)
            if not isinstance(field, dict) or field.get("type") != expected_type:
                errors.append(f"{child.lower()}_{field_name}_not_{expected_type}")
    return props, errors


def _hits(document: Any) -> list[dict]:
    if not isinstance(document, dict):
        raise ObservationError("search_json_invalid")
    if document.get("timed_out") is True:
        raise ObservationError("es_search_timed_out")
    shards = document.get("_shards") or {}
    if isinstance(shards, dict) and shards.get("failed", 0):
        raise ObservationError("es_shard_failure")
    rows = ((document.get("hits") or {}).get("hits") or [])
    if not isinstance(rows, list):
        raise ObservationError("search_hits_invalid")
    for row in rows:
        if not isinstance(row, dict):
            raise ObservationError("search_hit_shape_invalid")
        if row.get("_index") != INDEX:
            raise ObservationError("search_hit_unexpected_index")
    return rows


def _total_at_least_two(document: dict) -> bool:
    total = (document.get("hits") or {}).get("total")
    count = total.get("value") if isinstance(total, dict) else total
    return isinstance(count, int) and count >= 2


def _json_load_maybe(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _as_blocks(value: Any) -> list[dict]:
    # Keep the read-only probe independent of the runtime Evidence package;
    # that package's __init__ eagerly imports unrelated report dependencies.
    raw = _json_load_maybe(value)
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _candidate_source_summary(hits: list[dict]) -> dict[str, int]:
    """Evaluate true source-local IDs. No article text, IDs or dates printed."""
    from agent.es.event_time import (
        collect_linked_times, linked_dates_for_ids,
    )
    from agent.es.event_time import _ids
    summary = {
        "documents": len(hits), "blocks": 0, "events_dated": 0,
        "timelines_dated": 0, "evidence_with_event_ids": 0,
        "evidence_linked": 0, "evidence_without_link": 0,
    }
    for hit in hits:
        source = hit.get("_source")
        if not isinstance(source, dict):
            continue
        for block in _as_blocks(source.get("multidim_event_json")):
            summary["blocks"] += 1
            lookup, _ = collect_linked_times([block])
            for key, metric in (
                ("Event", "events_dated"),
                ("Event_Timeline", "timelines_dated"),
            ):
                raw = _json_load_maybe(block.get(key)) or []
                if isinstance(raw, dict):
                    raw = [raw]
                if isinstance(raw, list):
                    summary[metric] += sum(
                        bool(isinstance(row, dict) and row.get("time_iso"))
                        for row in raw
                    )
            snippets = _json_load_maybe(block.get("evidence_snippets")) or []
            if isinstance(snippets, dict):
                snippets = [snippets]
            if not isinstance(snippets, list):
                continue
            for snippet in snippets:
                if not isinstance(snippet, dict):
                    continue
                ids = _ids(snippet.get("event_ids"))
                if not ids:
                    continue
                summary["evidence_with_event_ids"] += 1
                times, complete = linked_dates_for_ids(ids, lookup)
                summary["evidence_linked" if complete and times else "evidence_without_link"] += 1
    return summary


def _sample_period(hit: dict) -> tuple[str, str, str] | None:
    """Return source-local day, nested child, and declared precision category.

    Missing precision requires the legacy ES filter branch; using inferred
    day here would exclude the very documents under test.
    """
    from agent.es.event_time import parse_structured_time
    src = hit.get("_source") or {}
    for block in _as_blocks(src.get("multidim_event_json")):
        for child in ("Event", "Event_Timeline"):
            rows = _json_load_maybe(block.get(child)) or []
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                declared = row.get("time_precision")
                point = parse_structured_time(
                    row.get("time_iso"), declared, child
                )
                if point is not None:
                    selected_precision = (
                        declared.strip().lower()
                        if isinstance(declared, str) and declared.strip()
                        else "legacy"
                    )
                    return point.start, child, selected_precision
    return None


def _sampled_sraf_date_clause(day: str, child: str, precision: str) -> dict:
    """Reuse a selected precision branch of the SRAF nested date query DSL.

    The entire 14-branch union exceeds the Elasticsearch default 4KiB HTTP
    request-line limit as a GET URI. Observing one real source-local branch
    is a PARTIAL validation of the production query, not full live acceptance.
    """
    from agent.es.query_body import _structured_date_filter
    order = ("second", "minute", "hour", "day", "month", "year", "legacy")
    if child not in ("Event", "Event_Timeline") or precision not in order:
        raise ObservationError("sampled_date_clause_invalid")
    full = _structured_date_filter(day, day)
    outer = full.get("nested")
    if not isinstance(outer, dict) or outer.get("path") != "multidim_event_json":
        raise ObservationError("sraf_date_filter_contract_changed")
    try:
        child_clause = outer["query"]["bool"]["should"][(
            "Event", "Event_Timeline"
        ).index(child)]["nested"]
        branches = child_clause["query"]["bool"]["should"]
        single = branches[order.index(precision)]
    except (IndexError, TypeError, KeyError):
        raise ObservationError("sraf_date_filter_contract_changed") from None
    if child_clause.get("path") != f"multidim_event_json.{child}":
        raise ObservationError("sraf_date_filter_contract_changed")
    return {"nested": {
        **outer,
        "query": {"nested": {**child_clause, "query": single}},
    }}


def _search_request(body: dict) -> str:
    """ES supports JSON DSL in GET ?source; never send arbitrary URL/method."""
    encoded = quote(json.dumps(body, ensure_ascii=False, separators=(",", ":")), safe="")
    path = f"/{INDEX}/_search?source={encoded}&source_content_type=application%2Fjson"
    if len(path) > MAX_SEARCH_PATH:
        raise ObservationError("bounded_search_uri_too_long")
    return path


def _strict_live_observe(root: Path, *, warn_only_ip_san: bool = False) -> dict[str, Any]:
    # Delayed imports keep --no-network independent from dotenv and ES clients.
    from tools.sraf_airgap_off1b_auto import _effective_runtime_config, _parse_endpoint
    from tools.sraf_airgap_off1b_es_https_mapping import (
        _https_get, _trusted_ca_file, _verified_basic_principal,
    )
    cfg = _effective_runtime_config(root)
    endpoint, host = _parse_endpoint(cfg.get("ES_URL"))
    username, password = cfg.get("ES_USERNAME") or "", cfg.get("ES_PASSWORD") or ""
    ca = _trusted_ca_file(root)
    if (endpoint.get("configuration") != "RESOLVED"
            or endpoint.get("scheme") != "https" or host is None):
        raise ObservationError("private_numeric_https_es_url_required")
    if not username or ":" in username or not password:
        raise ObservationError("es_credentials_not_configured")
    if ca is None:
        raise ObservationError("trusted_ca_missing")
    port = int(endpoint["port"])
    identity_warning = False

    def get(path: str, expected_bytes: int = 65536) -> Any:
        nonlocal identity_warning
        # The operator-only diagnostic keeps CA verification mandatory and
        # examines IP SAN before sending Basic credentials. A mismatched SAN
        # is only a CA-verified observation, NOT strict endpoint identity.
        if warn_only_ip_san:
            status, payload, reason = _https_get(
                host, port, path, username, password, ca,
                warn_only_ip_san=True,
            )
            if status is not None and reason not in (
                "https_response_received",
                "https_response_ca_only_ip_san_mismatch",
            ):
                raise ObservationError("es_tls_observation_inconclusive")
        else:
            status, payload, reason = _https_get(
                host, port, path, username, password, ca,
            )
        if reason == "https_response_ca_only_ip_san_mismatch":
            identity_warning = True
        if status is None:
            raise ObservationError(reason)
        if status != 200:
            raise ObservationError("es_http_rejected")
        if not isinstance(payload, bytes) or len(payload) > expected_bytes:
            raise ObservationError("es_response_missing_or_oversized")
        try:
            return json.loads(payload)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ObservationError("es_response_not_json") from None

    identity = get("/")
    if (not isinstance(identity, dict)
            or not isinstance(identity.get("cluster_name"), str)
            or not isinstance(identity.get("version"), dict)):
        raise ObservationError("es_identity_unverified")
    principal = get("/_security/_authenticate")
    if not _verified_basic_principal(
        json.dumps(principal).encode("utf-8"), username
    ):
        raise ObservationError("es_principal_unverified")
    mapping = get(f"/{INDEX}/_mapping", expected_bytes=2 * 1024 * 1024)
    _, mapping_errors = _properties(mapping)
    result: dict[str, Any] = {
        "identity": (
            "CA_VERIFIED_IP_SAN_MISMATCH" if identity_warning else
            "CA_VERIFIED_IP_SAN_MATCH_OBSERVED" if warn_only_ip_san else
            "STRICT_TLS_CA_IP_SAN_VERIFIED"
        ),
        "ip_san_policy": "WARN_ONLY" if warn_only_ip_san else "STRICT",
        "tls_validation": "WARN" if identity_warning else "PASS",
        "identity_warning": identity_warning,
        "release_tls_identity_verified": not warn_only_ip_san,
        **({"tls_warning": "ip_san_mismatch_ca_chain_verified"} if identity_warning else {}),
        "principal": "PROTECTED_ENDPOINT_ATTESTED_NO_NEGATIVE_PASSWORD_CHALLENGE",
        "mapping": "PASS" if not mapping_errors else "FAIL",
        "mapping_issues": mapping_errors,
    }
    if mapping_errors:
        result["status"] = "FAIL"
        return result

    def search(body: dict) -> dict:
        response = get(_search_request(body))
        if not isinstance(response, dict):
            raise ObservationError("search_json_invalid")
        _hits(response)
        return response

    def query_exists(child: str, offset: int = 0) -> dict:
        return {
            "size": 1, "from": offset, "track_total_hits": 2,
            "_source": {"includes": SOURCE_FIELDS},
            "query": {"nested": {
                "path": "multidim_event_json",
                "query": {"nested": {
                    "path": f"multidim_event_json.{child}",
                    "query": {"exists": {
                        "field": f"multidim_event_json.{child}.time_iso"
                    }},
                }},
            }},
        }

    ev_response = search(query_exists("Event"))
    tl_response = search(query_exists("Event_Timeline"))
    candidates = _hits(ev_response) + _hits(tl_response)
    coverage = _candidate_source_summary(candidates)
    result["source_sample"] = coverage
    result["event_sample"] = "OBSERVED" if _hits(ev_response) else "NOT_OBSERVED"
    result["timeline_sample"] = "OBSERVED" if _hits(tl_response) else "NOT_OBSERVED"
    result["evidence_link"] = (
        "OBSERVED" if coverage["evidence_linked"] else "NOT_OBSERVED"
    )

    chosen = next((h for h in candidates if _sample_period(h) and h.get("_id") is not None), None)
    if chosen is None:
        result["date_filter"] = "NOT_OBSERVED"
    else:
        when, child, precision = _sample_period(chosen)
        matched = search({
            "size": 1, "_source": False,
            "query": {"bool": {"filter": [
                {"ids": {"values": [str(chosen["_id"])]}},
                _sampled_sraf_date_clause(when, child, precision),
            ]}},
        })
        result["date_filter"] = (
            "PASS" if any(
                row.get("_id") == chosen["_id"]
                for row in _hits(matched)
            ) else "FAIL"
        )

    # Exactly two bounded GET pages, no _scroll, PIT, profile or deep search.
    if _total_at_least_two(ev_response):
        second = search(query_exists("Event", offset=1))
        p0, p1 = _hits(ev_response), _hits(second)
        result["paging"] = (
            "PASS" if p0 and p1 and (
                p0[0].get("_index"), p0[0].get("_id")
            ) != (
                p1[0].get("_index"), p1[0].get("_id")
            ) else "INCONCLUSIVE"
        )
    else:
        result["paging"] = "NOT_OBSERVED"

    if result.get("date_filter") == "FAIL":
        result["status"] = "FAIL"
    elif all(result.get(k) in ("PASS", "OBSERVED") for k in (
        "event_sample", "timeline_sample", "evidence_link", "date_filter", "paging",
    )):
        result["status"] = "PASS_PARTIAL"
    else:
        result["status"] = "INCOMPLETE"
    # Later GETs can see a different CA-signed peer; never lose their SAN warning.
    if identity_warning:
        result.update(
            identity="CA_VERIFIED_IP_SAN_MISMATCH",
            tls_validation="WARN",
            identity_warning=True,
            release_tls_identity_verified=False,
            tls_warning="ip_san_mismatch_ca_chain_verified",
        )
    # PASS_PARTIAL describes only date-query samples, never FULL_LIVE.
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="opt in to CA-validated GET-only private index checks")
    mode.add_argument("--no-network", action="store_true", help="default: no config, network or ES access")
    parser.add_argument(
        "--warn-only-ip-san", action="store_true",
        help="operator only: retain CA verification but warn and continue if the leaf IP SAN differs; weakens peer IP identity",
    )
    parser.add_argument(
        "--config-root", default=None,
        help="Existing deployed SRAF repository for local dotenv/CA only; "
             "useful when running probe code from a separate Git worktree",
    )
    args = parser.parse_args(argv)
    if args.warn_only_ip_san and not args.run:
        parser.error("--warn-only-ip-san requires --run")
    output: dict[str, Any] = {
        "schema": SCHEMA, "index": INDEX, "read_only": True,
        "scope": "MAPPING_EVENT_TIMELINE_SOURCE_LINK_DATE_QUERY_SMALL_PAGING",
    }
    if not args.run:
        output.update(status="NOT_TESTED", reason="network_not_enabled")
        print(json.dumps(output, sort_keys=True, ensure_ascii=False))
        return 2
    if Path.cwd().resolve() != PROJECT_ROOT:
        output.update(status="INCOMPLETE", reason="run_from_repository_root")
        print(json.dumps(output, sort_keys=True, ensure_ascii=False))
        return 2
    try:
        cfg_root = Path(args.config_root).resolve() if args.config_root else PROJECT_ROOT
        if not cfg_root.is_dir() or not (cfg_root / "run_sra_api.sh").is_file():
            raise ObservationError("configured_repository_root_invalid")
        # Never print the config root; dotenv/certificate are read only.
        if args.warn_only_ip_san:
            output.update(_strict_live_observe(cfg_root, warn_only_ip_san=True))
        else:
            output.update(_strict_live_observe(cfg_root))
    except ObservationError as exc:
        output.update(status="INCOMPLETE", reason=str(exc))
    except Exception:
        # No raw URLs, query JSON, index responses or credentials in errors.
        output.update(status="INCOMPLETE", reason="unhandled_probe_error")
    print(json.dumps(output, sort_keys=True, ensure_ascii=False))
    # Observation-only PARTIAL is never a formal release acceptance exit 0.
    return 1 if output["status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
