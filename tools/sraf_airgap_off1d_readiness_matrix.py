"""OFF-1D operator readiness matrix: existing bounded probes, NEVER full acceptance.

Default is entirely offline except fixed local filesystem observations. Opt in
to network with --probe-network: at most one configured private IPv4 TCP connect
each for API, ES, and LLM, plus one anonymous 127.0.0.1 GET /healthz when the
API TCP connection succeeds. A separate triple opt-in can make one local
bounded LLM generation POST; never contacts SQL, starts workers or tests
physical network isolation.

From deployed repository root:
    python tools/sraf_airgap_off1d_readiness_matrix.py
    python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_off1b_auto as tcp  # noqa: E402
from tools import sraf_airgap_off1b_api_http as api_http  # noqa: E402
from tools.sraf_airgap_off1f_llm_inference import (  # noqa: E402
    probe_local_ollama_inference,
)
from tools.sraf_airgap_off1_probes import (  # noqa: E402
    probe_disk, probe_odbc_library, probe_llm_inventory,
)

SCHEMA = "sraf_airgap_off1d_readiness_matrix_v1"
MODE = "PARTIAL_ONLY_NOT_ACCEPTANCE"
STATUSES = frozenset(("PASS", "WARN", "FAIL", "SKIP", "NOT_TESTED"))
# Whitelist only reviewed, non-sensitive fixed reason codes. Never forward
# arbitrary nested plugin/config/exception text to the operator report.
REASONS = frozenset((
    "disk_threshold_met", "disk_space_low", "disk_information_unavailable",
    "host_information_invalid", "odbc_filesystem_probe_unsupported",
    "odbc_discovery_unavailable", "odbc_library_file_observed",
    "odbc_library_not_found", "config_not_resolved", "network_disabled",
    "endpoint_outside_bounded_tcp_scope", "configured_tcp_connected",
    "configured_tcp_unavailable", "not_exact_loopback", "http_probe_internal_failure",
    "healthz_http_200", "healthz_http_not_200", "api_transport_unavailable",
    "api_response_oversized", "upstream_api_tcp_not_passed",
    "sql_read_not_implemented", "es_tls_mapping_not_aggregated",
    "llm_inventory_not_aggregated", "llm_inference_not_implemented",
    "worker_identity_not_implemented", "word_artifact_not_implemented",
    "network_isolation_not_attested", "unexpected_probe_result",
    "probe_internal_failure", "configuration_invalid",
    "llm_inventory_not_requested", "llm_inventory_tcp_not_passed",
    "llm_inventory_endpoint_outside_scope", "llm_inventory_model_invalid",
    "model_inventory_auth_required", "model_name_not_configured",
    "model_service_unavailable", "model_inventory_oversized",
    "model_inventory_http_error", "model_inventory_invalid",
    "configured_model_listed", "configured_model_not_listed",
    "llm_inference_not_requested", "llm_inference_inventory_not_passed",
    "llm_inference_endpoint_invalid", "llm_inference_model_invalid",
    "llm_inference_request_invalid", "llm_inference_transport_unverified",
    "llm_inference_service_unverified", "llm_inference_http_error",
    "llm_inference_response_invalid", "llm_inference_model_unverified",
    "llm_inference_generation_unverified", "llm_inference_generation_observed",
))


def _reason(value: Any) -> str:
    return value if isinstance(value, str) and value in REASONS else "unexpected_probe_result"


def _record(key: str, component: str, aspect: str, status: str, reason: str,
            *, executed: bool = False, depends_on: tuple[str, ...] = ()
            ) -> dict[str, Any]:
    if not isinstance(status, str) or status not in STATUSES:
        # An unknown status is not credible evidence. The provider's words
        # never escape our fixed, reviewed report schema.
        status, reason, executed = "SKIP", "unexpected_probe_result", False
    elif not isinstance(reason, str) or reason not in REASONS:
        # Preserve any definite FAIL (and WARN) severity, even if a provider
        # introduces a new private/error reason. Only unknown PASS evidence
        # must be demoted: incomplete is safer than a fabricated success.
        if status == "PASS":
            status, executed = "SKIP", False
        reason = "unexpected_probe_result"
    return {
        "id": key, "component": component, "aspect": aspect,
        "status": status, "reason": reason,
        "executed": bool(executed), "depends_on": list(depends_on),
        "feature_acceptance": "NOT_TESTED",
    }


def _local_probe(key: str, component: str, aspect: str, fn: Any
                 ) -> dict[str, Any]:
    try:
        obs = fn()
        status = obs.status
        return _record(key, component, aspect, status, obs.reason,
                       executed=obs.executed)
    except Exception:
        return _record(key, component, aspect, "FAIL",
                       "probe_internal_failure", executed=True)


def _expected_tcp_endpoint(service: str, cfg: dict[str, str]
                           ) -> tuple[dict[str, object], str | None]:
    """Reconstruct the reviewed configured endpoint, without any network."""
    if service == "api":
        return tcp._api_bind_endpoint(cfg)
    if service == "es":
        return tcp._parse_endpoint(cfg.get("ES_URL"))
    return tcp._parse_endpoint(
        cfg.get("MODEL_BASE_URL"),
        allowed_paths=("", "/", "/api/chat", "/api/generate"),
        normalize_llm_path=True,
    )


def _credible_tcp_pass(service: str, cfg: dict[str, str],
                       obs: dict[str, Any], *, probe_network: bool) -> bool:
    """A nested PASS alone must never authorize the dependent health GET."""
    if not probe_network:
        return False
    endpoint, selected_host = _expected_tcp_endpoint(service, cfg)
    scope = endpoint["host_scope"]
    allowed = (("LOOPBACK_IPV4",) if service == "api" else
               ("LOOPBACK_IPV4", "RFC1918_IPV4"))
    keys = {"api": "PORT", "es": "ES_URL", "llm": "MODEL_BASE_URL"}
    return (
        selected_host is not None
        and endpoint["configuration"] == "RESOLVED"
        and scope in allowed
        and type(endpoint["port"]) is int
        and 1 <= endpoint["port"] <= 65535
        and obs.get("component") == service
        and obs.get("config_key") == keys[service]
        and obs.get("configuration") == "RESOLVED"
        and obs.get("tcp_probe") == "PASS"
        and obs.get("reason") == "configured_tcp_connected"
        and obs.get("host_scope") == scope
        and obs.get("scheme") == endpoint["scheme"]
        and type(obs.get("port")) is int
        and obs["port"] == endpoint["port"]
    )


def _tcp_probe(service: str, cfg: dict[str, str], *, probe_network: bool
               ) -> dict[str, Any]:
    key, component = {
        "api": ("API-TCP", "api"),
        "es": ("ES-TCP", "es"),
        "llm": ("LLM-TCP", "llm"),
    }[service]
    try:
        obs = tcp._observe(service, cfg, no_network=not probe_network)
        configuration = obs.get("configuration")
        probe = obs.get("tcp_probe")
        if configuration == "INVALID":
            status, reason, executed = "FAIL", "configuration_invalid", False
        elif probe == "PASS":
            # Require the exact trusted contract, not merely a PASS token.
            if _credible_tcp_pass(service, cfg, obs, probe_network=probe_network):
                status, reason, executed = "PASS", "configured_tcp_connected", True
            else:
                status, reason, executed = "SKIP", "unexpected_probe_result", False
        elif probe == "FAIL":
            status, reason, executed = "FAIL", obs.get("reason"), True
        else:
            status, reason, executed = "SKIP", obs.get("reason"), False
    except Exception:
        status, reason, executed = "FAIL", "probe_internal_failure", False
    return _record(key, component, "configured_tcp_only",
                   status, reason, executed=executed)


def _api_health(cfg: dict[str, str], *, probe_network: bool,
                tcp_status: str) -> dict[str, Any]:
    if not probe_network:
        return _record("API-HEALTH", "api", "healthz_http_only", "SKIP",
                       "network_disabled", depends_on=("API-TCP",))
    if tcp_status != "PASS":
        return _record("API-HEALTH", "api", "healthz_http_only", "SKIP",
                       "upstream_api_tcp_not_passed", depends_on=("API-TCP",))
    try:
        obs = api_http._observe(cfg, no_network=False)
        probe = obs.get("http_probe")
        reason = obs.get("reason")
        if probe == "PASS":
            # The audited source asserts these fields on a genuine 200.
            # A contradictory provider payload must never certify health.
            if (obs.get("configuration") == "RESOLVED"
                    and type(obs.get("http_status")) is int
                    and obs["http_status"] == 200
                    and reason == "healthz_http_200"
                    and obs.get("http_method") == "GET"
                    and obs.get("healthz_endpoint") == "/healthz"):
                status = "PASS"
            elif obs.get("configuration") == "INVALID":
                status, reason = "FAIL", "configuration_invalid"
            elif (type(obs.get("http_status")) is int
                  and 100 <= obs["http_status"] <= 599
                  and obs["http_status"] != 200):
                status, reason = "FAIL", "healthz_http_not_200"
            else:
                status, reason = "SKIP", "unexpected_probe_result"
        elif obs.get("configuration") == "INVALID":
            status, reason = "FAIL", "configuration_invalid"
        elif probe == "FAIL":
            status = "FAIL"
        else:
            status = "SKIP"
    except Exception:
        status, reason = "FAIL", "probe_internal_failure"
    return _record("API-HEALTH", "api", "healthz_http_only", status,
                   reason, executed=(status in ("PASS", "FAIL")),
                   depends_on=("API-TCP",))


def _llm_inventory(cfg: dict[str, str], *, probe_network: bool,
                   probe_model_inventory: bool, tcp_status: str
                   ) -> dict[str, Any]:
    """One optional anonymous localhost Ollama inventory; never inference."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "LLM-INVENTORY", "llm", "named_model_inventory_only",
            status, reason, executed=executed, depends_on=("LLM-TCP",),
        )

    if not probe_network:
        return result("NOT_TESTED", "network_disabled")
    if not probe_model_inventory:
        return result("NOT_TESTED", "llm_inventory_not_requested")
    if tcp_status != "PASS":
        return result("SKIP", "llm_inventory_tcp_not_passed")

    # _http_get uses 127.0.0.1, anonymous HTTP and fixed /api/tags;
    # never query another host/port, HTTPS or reverse proxy prefix.
    endpoint, selected_host = _expected_tcp_endpoint("llm", cfg)
    raw = cfg.get("MODEL_BASE_URL")
    try:
        selected_path = urlsplit(raw).path.rstrip("/")
    except (TypeError, ValueError):
        return result("SKIP", "llm_inventory_endpoint_outside_scope")
    if (endpoint["configuration"] != "RESOLVED"
            or selected_host != "127.0.0.1"
            or endpoint.get("scheme") != "http"
            or type(endpoint.get("port")) is not int
            or selected_path not in ("", "/api/chat", "/api/generate")):
        return result("SKIP", "llm_inventory_endpoint_outside_scope")
    model_name = cfg.get("MODEL_ID")
    if not isinstance(model_name, str) or not model_name:
        return result("SKIP", "model_name_not_configured")
    if (len(model_name) > 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in model_name)):
        return result("SKIP", "llm_inventory_model_invalid")
    try:
        obs = probe_llm_inventory(endpoint["port"], model_name,
                                  backend="ollama")
        status = obs.status
        if status == "PASS":
            fields = obs.evidence
            if (obs.check_id == "LLM-01"
                    and obs.probe == "llm-inventory"
                    and obs.aspect == "named_model_inventory_only"
                    and obs.executed is True
                    and obs.reason == "configured_model_listed"
                    and isinstance(fields, dict)
                    and fields.get("model_available") is True
                    and type(fields.get("http_status")) is int
                    and fields["http_status"] == 200
                    and type(fields.get("item_count")) is int
                    and 1 <= fields["item_count"] <= 1000):
                return result("PASS", "configured_model_listed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if status == "FAIL":
            return result("FAIL", _reason(obs.reason),
                          executed=bool(obs.executed))
        if (status == "SKIP" and obs.reason == "model_inventory_auth_required"
                and obs.executed is True
                and obs.evidence.get("http_status") in (401, 403)):
            return result("SKIP", "model_inventory_auth_required",
                          executed=True)
        return result("SKIP", "unexpected_probe_result")
    except Exception:
        return result("FAIL", "probe_internal_failure", executed=True)


def _llm_inference(cfg: dict[str, str], *, probe_network: bool,
                   probe_model_inventory: bool, probe_model_inference: bool,
                   inventory_status: str) -> dict[str, Any]:
    """Operator-authorized one-shot local model generation, not end-to-end."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "LLM-INFERENCE", "llm", "single_bounded_generation_only",
            status, reason, executed=executed,
            depends_on=("LLM-TCP", "LLM-INVENTORY"),
        )

    # Unlike status-only smoke checks, generation may load a large model.
    # The operator must opt in explicitly to all three prerequisites.
    if not (probe_network and probe_model_inventory and probe_model_inference):
        return result("NOT_TESTED", "llm_inference_not_requested")
    if inventory_status != "PASS":
        return result("SKIP", "llm_inference_inventory_not_passed")
    endpoint, host = _expected_tcp_endpoint("llm", cfg)
    url = cfg.get("MODEL_BASE_URL")
    try:
        path = urlsplit(url).path.rstrip("/")
    except (TypeError, ValueError):
        return result("SKIP", "llm_inference_endpoint_invalid")
    if (endpoint["configuration"] != "RESOLVED" or host != "127.0.0.1"
            or endpoint["scheme"] != "http"
            or type(endpoint["port"]) is not int
            or not 1 <= endpoint["port"] <= 65535
            or path not in ("", "/api/chat", "/api/generate")):
        return result("SKIP", "llm_inference_endpoint_invalid")
    model = cfg.get("MODEL_ID")
    if (not isinstance(model, str) or not 1 <= len(model) <= 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in model)):
        return result("SKIP", "llm_inference_model_invalid")
    try:
        obs = probe_local_ollama_inference(endpoint["port"], model)
        if obs.status == "PASS":
            info = obs.evidence
            if (obs.check_id == "LLM-02"
                    and obs.probe == "llm-inference"
                    and obs.aspect == "single_bounded_generation_only"
                    and obs.executed is True
                    and obs.reason == "llm_inference_generation_observed"
                    and isinstance(info, dict)
                    and info.get("generation_observed") is True
                    and type(info.get("http_status")) is int
                    and info["http_status"] == 200):
                return result("PASS", "llm_inference_generation_observed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status == "FAIL":
            return result("FAIL", _reason(obs.reason), executed=bool(obs.executed))
        if obs.status == "SKIP":
            return result("SKIP", _reason(obs.reason), executed=bool(obs.executed))
        return result("SKIP", "unexpected_probe_result")
    except Exception:
        return result("FAIL", "probe_internal_failure", executed=True)


def build_report(cfg: dict[str, str], *, probe_network: bool = False,
                 probe_model_inventory: bool = False,
                 probe_model_inference: bool = False
                 ) -> dict[str, Any]:
    """Run independent reviewed probes even when another component fails."""
    rows = [
        _local_probe("HOST-DISK", "host", "disk_space_only", probe_disk),
        _local_probe("SQL-ODBC", "sql", "odbc_library_file_only",
                     probe_odbc_library),
    ]
    api = _tcp_probe("api", cfg, probe_network=probe_network)
    rows.append(api)
    rows.append(_api_health(cfg, probe_network=probe_network,
                            tcp_status=api["status"]))
    rows.append(_tcp_probe("es", cfg, probe_network=probe_network))
    llm = _tcp_probe("llm", cfg, probe_network=probe_network)
    rows.append(llm)
    # These are genuine NOT_TESTED slices, not simulated results or dependent
    # PASS declarations. Future work must add reviewed real probes.
    inventory = _llm_inventory(
        cfg, probe_network=probe_network,
        probe_model_inventory=probe_model_inventory,
        tcp_status=llm["status"],
    )
    rows.extend((
        _record("SQL-READ", "sql", "sql_server_read_only", "NOT_TESTED",
                "sql_read_not_implemented", depends_on=("SQL-ODBC",)),
        _record("ES-MAPPING", "es", "authenticated_es_mapping", "NOT_TESTED",
                "es_tls_mapping_not_aggregated", depends_on=("ES-TCP",)),
        inventory,
        _llm_inference(cfg, probe_network=probe_network,
                       probe_model_inventory=probe_model_inventory,
                       probe_model_inference=probe_model_inference,
                       inventory_status=inventory["status"]),
        _record("WORKERS", "workers", "process_and_schedule_worker_identity",
                "NOT_TESTED", "worker_identity_not_implemented",
                depends_on=("API-HEALTH", "SQL-READ")),
        _record("WORD", "report", "real_word_artifact_validation",
                "NOT_TESTED", "word_artifact_not_implemented",
                depends_on=("WORKERS", "LLM-INFERENCE")),
        _record("ISOLATION", "deployment", "airgap_network_isolation",
                "NOT_TESTED", "network_isolation_not_attested"),
    ))
    counts = Counter(row["status"] for row in rows)
    return {
        "schema": SCHEMA, "mode": MODE,
        "network_mode": (
            "BOUNDED_TCP_AND_LOOPBACK_HTTP_WITH_OPTIONAL_GENERATION"
            if probe_network and probe_model_inventory and probe_model_inference
            else "BOUNDED_TCP_AND_LOOPBACK_HTTP" if probe_network
            else "LOCAL_ONLY_NO_NETWORK"
        ),
        "overall": "ISSUES_FOUND" if counts["FAIL"] else "INCOMPLETE",
        "feature_acceptance": "NOT_TESTED",
        "counts": {status: counts[status] for status in
                   ("PASS", "WARN", "FAIL", "SKIP", "NOT_TESTED")},
        "results": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-network", action="store_true",
                        help="Opt in to private-IP TCP and anonymous loopback API health.")
    parser.add_argument("--probe-llm-inventory", action="store_true",
                        help="With --probe-network, check anonymous localhost Ollama /api/tags once.")
    parser.add_argument("--probe-llm-inference", action="store_true",
                        help="With BOTH other flags, run one real local Ollama generation (may load model).")
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}))
        return 2
    try:
        cfg = tcp._effective_runtime_config(PROJECT_ROOT)
    except ValueError as exc:
        if str(exc) == "invalid_profile":
            print(json.dumps({
                "schema": SCHEMA, "mode": MODE,
                "overall": "ISSUES_FOUND",
                "feature_acceptance": "NOT_TESTED",
                "error": "runtime_profile_invalid",
            }))
            return 1
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "readiness_matrix_unavailable"}))
        return 2
    except Exception:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "readiness_matrix_unavailable"}))
        return 2
    try:
        report = build_report(cfg, probe_network=args.probe_network,
                              probe_model_inventory=args.probe_llm_inventory,
                              probe_model_inference=args.probe_llm_inference)
    except Exception:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "readiness_matrix_unavailable"}))
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    # Never return zero while SQL, inference, workers, artifacts, and isolation
    # have not been independently attested.
    return 1 if report["overall"] == "ISSUES_FOUND" else 2


if __name__ == "__main__":
    raise SystemExit(main())
