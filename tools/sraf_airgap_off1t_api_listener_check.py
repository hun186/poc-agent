#!/usr/bin/env python3
"""OFF-1T: standalone, offline, read-only SRAF API listener observation.

Reuses OFF-1S's strict Linux launcher/process/listener attestation. This CLI
does not connect to a socket, send a credential, start a job, or imply
cryptographic API identity, real E2E readiness, or physical air-gap acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off1s_api_listener import probe_api_listener  # noqa: E402

SCHEMA = "sraf_airgap_off1t_api_listener_v1"
SCOPE = "PARTIAL_ONLY_NOT_ACCEPTANCE"


def observe(project_root: Path, api_port: str) -> dict[str, object]:
    """Return reviewed status/booleans only; no PID, paths, sockets or secrets."""
    observation = probe_api_listener(project_root, api_port)
    verified = observation.status == "PASS"
    return {
        "schema": SCHEMA,
        "check_id": "API-LISTENER-01",
        "status": "PASS" if verified else "SKIP",
        "reason": "api_listener_attested" if verified else "api_listener_unverified",
        "mode": SCOPE,
        "feature_acceptance": "NOT_TESTED",
        "listener_identity_observed": verified,
        "network_requests": 0,
        "credentials_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute deployed repository root (not printed)")
    parser.add_argument("--api-port", required=True,
                        help="Local launcher numeric API port (not printed)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    result = observe(args.project_root, args.api_port)
    if args.format == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print("OFF1T_API_LISTENER={status} reason={reason} "
              "mode=PARTIAL_ONLY_NOT_ACCEPTANCE "
              "feature_acceptance=NOT_TESTED".format(**result))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
