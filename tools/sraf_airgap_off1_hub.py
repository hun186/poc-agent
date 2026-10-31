#!/usr/bin/env python3
"""One-command OFF-1 operator hub for an already deployed SRAF application.

Uses the *application's installed Python environment* (not standalone stdlib).
Default and --suite diagnose are read-only; no SQL query, login, Worker restart,
Job creation, model request, DNS, internet access or package installation.
--live-report is a separate explicit operator action delegated to the reviewed
Report Job acceptance and OFF-1S strict listener guard.
This is PARTIAL evidence, never OFF-2--5 or physical-airgap certification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_report_jobs_acceptance as report_jobs
from tools.sraf_airgap_off1_probes import probe_disk, probe_odbc_library
from tools.sraf_airgap_off1h_worker_identity import probe_worker_process_identities
from tools.sraf_airgap_off1_es_hub import strict_mapping_observation

ROOT = report_jobs.ROOT
SCHEMA = "sraf_airgap_off1_unified_hub_v1"
MODE = "PARTIAL_ONLY_NOT_AIRGAP_CERTIFICATION"

# Fixed inventory of gates deliberately NOT executed by a read-only hub.
# These checks need their own inputs, trust evidence and/or authorization.
MANUAL_GATES = (
    ("es_tls_ca_san_mapping", "strict_es_identity_mapping_not_tested"),
    ("sql_schema_source_permissions", "sql_authority_not_tested"),
    ("schedule_handoff_workers", "schedule_handoff_e2e_not_tested"),
    ("real_agent_llm_es", "provider_agent_e2e_not_tested"),
    ("browser_visual", "actual_browser_not_tested"),
    ("package_release_provenance", "release_manifest_not_tested"),
    ("backup_restore_off5", "restore_not_tested"),
    ("physical_airgap", "disconnected_network_not_tested"),
)

REQUIRED_QUICK = frozenset((
    "host_disk", "api_health", "ui_page", "ui_javascript", "ui_stylesheet",
))


def _manual_gates():
    return [{"check": name, "status": "NOT_TESTED", "reason": reason}
            for name, reason in MANUAL_GATES]


def _exit_for_selected(rows: list[dict], suite: str) -> int:
    """Evaluate only selected operational observations, not advisory gates."""
    required = set(REQUIRED_QUICK)
    if suite == "diagnose":
        required.update(("tcp_api", "tcp_es", "tcp_llm"))
    selected = [r["status"] for r in rows if r["check"] in required]
    if len(selected) != len(required):
        return 2
    if any(status == "FAIL" for status in selected):
        return 1
    return 0 if all(status == "PASS" for status in selected) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("quick", "diagnose"), default="quick")
    parser.add_argument("--no-network", action="store_true",
                        help="No HTTP/TCP; report connectivity as SKIP/INCOMPLETE")
    parser.add_argument("--probe-es-tls-mapping", action="store_true",
                        help="Explicitly send configured ES Basic credentials only after "
                             "strict CA+IP SAN verification; bounded read-only GETs. "
                             "Auth still NOT_VERIFIED; never a release certificate.")
    parser.add_argument("--live-report", action="store_true",
                        help="EXPLICIT authorization for one real Agent/LLM Report Job")
    parser.add_argument("--token-env", default=None,
                        help="Name of an existing authorized Report Job bearer env variable")
    parser.add_argument("--username", default=None,
                        help="Optional login username; password is prompted privately")
    parser.add_argument("--max-seconds", type=int, default=1200)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "sraf-acceptance-results")
    args = parser.parse_args(argv)
    if args.live_report and args.no_network:
        parser.error("--live-report is incompatible with --no-network")
    if args.probe_es_tls_mapping and (
            args.suite != "diagnose" or args.no_network or args.live_report):
        parser.error("--probe-es-tls-mapping requires --suite diagnose and "
                     "cannot combine with --no-network or --live-report")
    if args.token_env and re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", args.token_env) is None:
        parser.error("invalid --token-env NAME")
    if not 30 <= args.max_seconds <= 3600:
        parser.error("--max-seconds must be between 30 and 3600")
    if Path.cwd().resolve() != ROOT:
        print("SRAF_OFF1_HUB=INCOMPLETE reason=run_from_repository_root")
        return 2

    rows: list[dict] = []
    evidence = {
        "schema": SCHEMA,
        "mode": MODE,
        "suite": args.suite,
        "network_mode": "NONE" if args.no_network else "BOUNDED_LOCAL_ONLY",
        "live_report_requested": args.live_report,
        "live_report_observation": "NOT_TESTED",
        "checks": rows,
        "manual_gates": _manual_gates(),
        "full_airgap_acceptance": "NOT_TESTED",
        "production_release_ready": False,
    }
    result_fd = None
    code = 2
    try:
        # Validate and pin the output location BEFORE any probe or credential.
        result_fd = report_jobs._secure_output_dir(args.output_dir)
        for name, probe in (("host_disk", probe_disk),
                            ("host_odbc_library", probe_odbc_library)):
            obs = probe()
            rows.append(report_jobs._row(name, obs.status, obs.reason))
        cfg = report_jobs._effective_runtime_config(ROOT)
        if args.probe_es_tls_mapping:
            # Independently observe ES even if API health later fails.
            # No ES request is possible in default quick/diagnose.
            # Strict CA+IP SAN and bounded read-only GETs are owned by OFF-1B.
            rows.append(strict_mapping_observation(cfg, ROOT))
        endpoint, host = report_jobs._api_bind_endpoint(cfg)
        if endpoint["configuration"] != "RESOLVED" or host != "127.0.0.1":
            raise report_jobs.ObservationError("api_port_invalid")
        port = int(endpoint["port"])
        proof = report_jobs._quick(port, cfg, rows, args.suite, args.no_network)
        if args.suite == "diagnose":
            # OFF-1H is a no-network /proc and launcher-identity observation.
            # It cannot establish SQL leases, Handoff execution or readiness.
            # Advisory only: a missing or unverified Worker may be legitimate.
            try:
                observed = probe_worker_process_identities(ROOT)
                count = observed.evidence["verified_role_count"]
                if type(count) is not int or not 0 <= count <= 2:
                    raise ValueError("worker_observation_invalid")
                if (observed.status, observed.reason) not in (
                    ("PASS", "worker_process_identities_verified"),
                    ("SKIP", "worker_process_identity_unverified"),
                    ("SKIP", "worker_process_host_unsupported"),
                ):
                    raise ValueError("worker_observation_invalid")
                if (observed.status == "PASS" and count != 2
                        or observed.reason == "worker_process_host_unsupported" and count != 0):
                    raise ValueError("worker_observation_inconsistent")
                rows.append(report_jobs._row(
                    "worker_process_identity", observed.status, observed.reason,
                    verified_role_count=count,
                ))
            except Exception:
                # Never serialize /proc exceptions, paths, PIDs or credentials.
                rows.append(report_jobs._row(
                    "worker_process_identity", "SKIP", "worker_process_identity_unverified",
                    verified_role_count=0,
                ))
        code = _exit_for_selected(rows, args.suite)
        if args.probe_es_tls_mapping:
            es_status = next(row["status"] for row in rows
                             if row["check"] == "es_strict_tls_mapping")
            if es_status == "FAIL":
                code = 1
            elif es_status != "PASS" and code == 0:
                code = 2
        if args.live_report:
            if code == 0:
                code = report_jobs._live(port, proof, args, rows, result_fd)
                evidence["live_report_observation"] = (
                    "OBSERVED_PARTIAL" if code == 0 else "INCOMPLETE_OR_FAILED"
                )
            else:
                rows.append(report_jobs._row(
                    "live_report", "SKIP", "prerequisite_checks_not_passed"))
                evidence["live_report_observation"] = "INCOMPLETE"
    except report_jobs.ObservationError as exc:
        incomplete = "unverified" in exc.code
        rows.append(report_jobs._row(
            "operator", "SKIP" if incomplete else "FAIL", exc.code))
        code = 2 if incomplete else 1
    except (OSError, ValueError, RuntimeError, EOFError, KeyboardInterrupt):
        rows.append(report_jobs._row(
            "operator", "SKIP", "operator_environment_or_transport_unavailable"))
        code = 2
    if result_fd is None:
        # Never write even failure JSON through an unverified output path.
        print("SRAF_OFF1_HUB=INCOMPLETE reason=output_dir_unverified")
        return 2

    evidence["result"] = "PASS_PARTIAL" if code == 0 else "FAIL" if code == 1 else "INCOMPLETE"
    evidence["exit_code"] = code
    evidence["completed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    evidence["counts"] = {
        status: sum(row["status"] == status for row in rows)
        for status in ("PASS", "FAIL", "SKIP", "WARN")
    }
    try:
        filename = ("off1-hub-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    + "-" + os.urandom(5).hex() + ".json")
        report_jobs._secure_write(filename, json.dumps(
            evidence, sort_keys=True, indent=2, ensure_ascii=False
        ).encode("utf-8"), result_fd)
        print("SRAF_OFF1_HUB=" + evidence["result"])
        for row in rows:
            print(row["check"] + "=" + row["status"] + " reason=" + row["reason"])
        print("MANUAL_GATES=NOT_TESTED count=" + str(len(MANUAL_GATES)))
        print("EVIDENCE_FILE=" + str(args.output_dir / filename))
    except (OSError, report_jobs.ObservationError):
        print("SRAF_OFF1_HUB=INCOMPLETE reason=evidence_write_unavailable")
        return 2
    finally:
        os.close(result_fd)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
