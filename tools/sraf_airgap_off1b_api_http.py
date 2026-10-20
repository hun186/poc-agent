"""OFF-1B configured API /healthz observation (NOT full deployment acceptance).

Run from the deployed repository root:
    python tools/sraf_airgap_off1b_api_http.py
    python tools/sraf_airgap_off1b_api_http.py --no-network

This reuses the reviewed OFF-1A bounded, strict anonymous loopback HTTP GET
implementation and OFF-1B effective runtime config discovery. It NEVER uses
PUBLIC_API_BASE as an API listener target, sends credentials, follows redirects,
or initializes the application. HTTP 200 confirms /healthz only, not that the
listener belongs to the desired API process or that workers are ready.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off1_probes import probe_api_health  # noqa: E402
from tools.sraf_airgap_off1b_auto import (  # noqa: E402
    MODE,
    _api_bind_endpoint,
    _effective_runtime_config,
)

SCHEMA = "sraf_airgap_off1b_configured_api_http_v1"


def _observe(cfg: dict[str, str], *, no_network: bool) -> dict[str, object]:
    endpoint, host = _api_bind_endpoint(cfg)
    result: dict[str, object] = {
        "component": "api",
        "config_key": "PORT",
        **endpoint,
        "http_probe": "SKIP",
        "reason": "config_not_resolved",
        "http_status": None,
        "healthz_endpoint": "/healthz",
        "http_method": "GET",
        "service_identity": "NOT_TESTED",
        "worker_readiness": "NOT_TESTED",
        "tls_validation": "NOT_APPLICABLE_LOOPBACK_HTTP",
        "auth": "NOT_TESTED",
        "feature_acceptance": "NOT_TESTED",
    }
    if endpoint["configuration"] != "RESOLVED":
        return result
    if no_network:
        result["reason"] = "network_disabled"
        return result
    if host != "127.0.0.1":
        result["reason"] = "not_exact_loopback"
        return result

    # OFF-1A enforces one anonymous 127.0.0.1 GET, a 3-second absolute
    # monotonic deadline, bounded 64 KiB body, strict HTTP framing, no redirects.
    try:
        observation = probe_api_health(int(endpoint["port"]))
    except Exception:
        # Do not serialize third-party parser exceptions or filesystem paths.
        result["http_probe"] = "FAIL"
        result["reason"] = "http_probe_internal_failure"
        return result
    result["http_probe"] = observation.status
    result["reason"] = observation.reason
    status = observation.evidence.get("http_status")
    if isinstance(status, int) and 100 <= status <= 599:
        result["http_status"] = status
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-network", action="store_true",
                        help="Resolve configuration only; never open a socket")
    args = parser.parse_args(argv)

    if Path.cwd().resolve() != PROJECT_ROOT:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "run_from_repository_root"}, sort_keys=True))
        return 2
    try:
        cfg = _effective_runtime_config(PROJECT_ROOT)
    except Exception:
        print(json.dumps({"schema": SCHEMA, "mode": MODE,
                          "error": "runtime_configuration_unavailable"}, sort_keys=True))
        return 2

    observation = _observe(cfg, no_network=args.no_network)
    print(json.dumps({
        "schema": SCHEMA,
        "mode": MODE,
        "network_mode": "CONFIG_ONLY" if args.no_network else "BOUNDED_LOOPBACK_HTTP_ONLY",
        "results": [observation],
    }, sort_keys=True, ensure_ascii=False))
    if observation["configuration"] == "INVALID" or observation["http_probe"] == "FAIL":
        return 1
    return 0 if observation["http_probe"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
