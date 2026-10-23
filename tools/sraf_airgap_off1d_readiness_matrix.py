"""OFF-1D operator readiness matrix: existing bounded probes, NEVER full acceptance.

Default is entirely offline except fixed local filesystem observations. Opt in
to network with --probe-network: at most one configured private IPv4 TCP connect
each for API, ES, and LLM, plus one anonymous 127.0.0.1 GET /healthz when the
API TCP connection succeeds. Does not connect to SQL, authenticate to ES,
invoke models, start workers, inspect artifacts or test physical isolation.

From deployed repository root:
    python tools/sraf_airgap_off1d_readiness_matrix.py
    python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_off1b_auto as tcp  # noqa: E402
from tools import sraf_airgap_off1b_api_http as api_http  # noqa: E402
from tools.sraf_airgap_off1_probes import (  # noqa: E402
    probe_disk, probe_odbc_library,
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
))


def _reason(value: Any) -> str:
    return value if isinstance(value, str) and value in REASONS else "unexpected_probe_result"


def _record(key: str, component: str, aspect: str, status: str, reason: str,
            *, executed: bool = False, depends_on: tuple[str, ...] = ()
            ) -> dict[str, Any]:
    if status not in STATUSES:
        status, reason, executed = "SKIP", "unexpected_probe_result", False
    return {
        "id": key, "component": component, "aspect": aspect,
        "status": status, "reason": _reason(reason),
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
            status, reason, executed = "PASS", obs.get("reason"), True
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
        status = probe if probe in ("PASS", "FAIL") else "SKIP"
        reason = obs.get("reason")
    except Exception:
        status, reason = "FAIL", "probe_internal_failure"
    return _record("API-HEALTH", "api", "healthz_http_only", status,
                   reason, executed=(status in ("PASS", "FAIL")),
                   depends_on=("API-TCP",))


def build_report(cfg: dict[str, str], *, probe_network: bool = False
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
    rows.append(_tcp_probe("llm", cfg, probe_network=probe_network))
    # These are genuine NOT_TESTED slices, not simulated results or dependent
    # PASS declarations. Future work must add reviewed real probes.
    rows.extend((
        _record("SQL-READ", "sql", "sql_server_read_only", "NOT_TESTED",
                "sql_read_not_implemented", depends_on=("SQL-ODBC",)),
        _record("ES-MAPPING", "es", "authenticated_es_mapping", "NOT_TESTED",
                "es_tls_mapping_not_aggregated", depends_on=("ES-TCP",)),
        _record("LLM-INVENTORY", "llm", "model_inventory", "NOT_TESTED",
                "llm_inventory_not_aggregated", depends_on=("LLM-TCP",)),
        _record("LLM-INFERENCE", "llm", "model_inference", "NOT_TESTED",
                "llm_inference_not_implemented", depends_on=("LLM-INVENTORY",)),
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
        "network_mode": ("BOUNDED_TCP_AND_LOOPBACK_HTTP" if probe_network
                         else "LOCAL_ONLY_NO_NETWORK"),
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
    args = parser.parse_args(argv)
    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}))
        return 2
    try:
        cfg = tcp._effective_runtime_config(PROJECT_ROOT)
        report = build_report(cfg, probe_network=args.probe_network)
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
