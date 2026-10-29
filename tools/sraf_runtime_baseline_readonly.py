#!/usr/bin/env python3
"""Operator-only, point-in-time SRAF baseline; never a live E2E acceptance.

Composes existing OFF-1S listener, OFF-1A anonymous 3s-loopback health, and
OFF-1H worker checks. No authentication, SQL/ES/LLM, restart, or job creation.
Run on the already-running Linux deployment as the launcher owner:

    python tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002
    python tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002 --no-network
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
from tools.sraf_airgap_off1h_worker_identity import probe_worker_process_identities  # noqa: E402
from tools.sraf_airgap_off1s_api_listener import attest_api_listener  # noqa: E402

SCHEMA = "sraf_runtime_baseline_readonly_v1"
MODE = "PARTIAL_ONLY_NOT_ACCEPTANCE"


def _row(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def _valid_port(value: str) -> int | None:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    try:
        parsed = int(value)
    except (ValueError, OverflowError):
        return None
    return parsed if 1 <= parsed <= 65535 and str(parsed) == value else None


def observe(project_root: Path, api_port: str, *, no_network: bool = False) -> dict:
    """Return only fixed labels: never paths, ports, PID, exceptions or secrets."""
    checks = {
        "API-LISTENER": _row("SKIP", "listener_identity_unverified"),
        "API-HEALTH": _row("SKIP", "health_not_observed"),
        "WORKER-IDENTITIES": _row("SKIP", "worker_identity_unverified"),
    }
    requests_sent = 0
    valid = (
        isinstance(project_root, Path) and project_root.is_absolute()
        and not project_root.is_symlink() and project_root.is_dir()
        and sys.platform == "linux" and _valid_port(api_port) is not None
    )
    if valid:
        try:
            before = attest_api_listener(project_root, api_port)
            listener_ok = before is not None
        except Exception:
            listener_ok = False

        try:
            workers = probe_worker_process_identities(project_root)
            if workers.status == "PASS" and workers.evidence.get("verified_role_count") == 2:
                checks["WORKER-IDENTITIES"] = _row("PASS", "worker_process_identities_verified")
        except Exception:
            pass

        if listener_ok:
            checks["API-LISTENER"] = _row("PASS", "listener_identity_observed")
        if no_network:
            checks["API-HEALTH"] = _row("SKIP", "network_disabled")
        elif listener_ok:
            # OFF-1A's audited GET is anonymous, numeric IPv4 loopback only;
            # absolute monotonic budget 3s, no redirects, 64KiB max body.
            requests_sent = 1
            try:
                health = probe_api_health(_valid_port(api_port))
                state = health.status if health.status in {"PASS", "FAIL", "SKIP"} else "SKIP"
                checks["API-HEALTH"] = _row(
                    state,
                    "healthz_http_200" if state == "PASS" else "healthz_unverified",
                )
            except Exception:
                checks["API-HEALTH"] = _row("SKIP", "healthz_unverified")
            # A replaced listener invalidates the combined observation.
            try:
                after = attest_api_listener(project_root, api_port)
                stable = after == before
            except Exception:
                stable = False
            if not stable:
                checks["API-LISTENER"] = _row("SKIP", "listener_identity_changed")
                checks["API-HEALTH"] = _row("SKIP", "listener_identity_changed")
        else:
            checks["API-HEALTH"] = _row("SKIP", "listener_identity_unverified")

    complete = all(row["status"] == "PASS" for row in checks.values())
    return {
        "schema": SCHEMA,
        "mode": MODE,
        "feature_acceptance": "NOT_TESTED",
        "overall": "PASS" if complete else "INCOMPLETE",
        "checks": checks,
        "loopback_http_requests": requests_sent,
        "external_network_requests": 0,
        "credentials_sent": False,
        "database_queries": 0,
        "model_inferences": 0,
        "mutations": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute installed SRAF repository root (never printed)")
    parser.add_argument("--api-port", required=True,
                        help="Local numeric API port (never printed)")
    parser.add_argument("--no-network", action="store_true",
                        help="Skip even the anonymous loopback GET")
    args = parser.parse_args(argv)
    result = observe(args.project_root, args.api_port, no_network=args.no_network)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
