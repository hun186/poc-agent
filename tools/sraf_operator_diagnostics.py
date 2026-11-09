#!/usr/bin/env python3
"""SRAF layered operator diagnostics: observed probes, never a full-release certificate.

Default L1 is bounded read-only local checks plus anonymous HTTP/TCP.
L2 probes run only on separate opt-in flags. L3 submits exactly one existing
Report Job only with a named scoped token, trusted output directory and the
reviewed OFF-1S listener guard. No hidden model call, SQL write, or worker
restart. Full Requirement -> Schedule -> Handoff E2E is NOT performed here.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "sraf_operator_layered_diagnostics_v1"
LEVELS = ("L1", "L2", "L3")
STATES = frozenset(("PASS", "PASS_PARTIAL", "WARN", "FAIL", "SKIP", "INCOMPLETE", "NOT_TESTED"))
SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{0,79}\Z", re.ASCII)
TOKEN_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z", re.ASCII)
L0_CHECKS = ("target_platform", "direct_distribution_metadata",
             "static_launchers", "host_disk", "worker_process_identity",
             "api_listener_preflight")
L1_CHECKS = ("api_tcp", "api_health", "es_tcp", "llm_tcp")
L2_CHECKS = ("sql_constant_read", "es_tls_mapping", "llm_inference")


def _row(name: str, status: str, reason: str, elapsed_ms: int | None = None) -> dict[str, object]:
    if status not in STATES or not SAFE_REASON.fullmatch(reason):
        status, reason = "INCOMPLETE", "probe_contract_unverified"
    return {"id": name, "status": status, "reason": reason,
            "elapsed_ms": (None if elapsed_ms is None else max(0, min(elapsed_ms, 3_600_000)))}


def _run(name: str, fn) -> dict[str, object]:
    start = time.monotonic()
    try:
        status, reason = fn()
    except Exception:
        status, reason = "INCOMPLETE", "probe_unavailable"
    return _row(name, status, reason, int((time.monotonic() - start) * 1000))


def _local_rows(launcher_port: str | None) -> tuple[str, list[dict[str, object]]]:
    from tools import sraf_local_deploy_quickcheck as quick
    # Standalone quickcheck retains its 9002 default; this layered entrypoint
    # observes the actual pre-dotenv launcher PORT without credential/FD scan.
    if launcher_port is None or launcher_port == "":
        api_port = 9002
    elif re.fullmatch(r"[0-9]{1,5}", launcher_port):
        api_port = int(launcher_port)
    else:
        api_port = 0  # explicitly invalid, fail closed without a socket probe
    report = quick.observe(ROOT, api_port=api_port)
    checks = report.get("checks", [])
    if (report.get("schema") != quick.SCHEMA or
            not isinstance(checks, list) or len(checks) != len(L0_CHECKS)):
        raise ValueError("local_contract_unverified")
    rows = []
    for expected, check in zip(L0_CHECKS, checks):
        if not isinstance(check, dict) or check.get("id") != expected:
            raise ValueError("local_contract_unverified")
        status, reason = check.get("status"), check.get("reason")
        if status not in ("PASS", "PASS_PARTIAL", "WARN", "INCOMPLETE"):
            raise ValueError("local_status_unverified")
        rows.append(_row("L0." + expected, status, reason))
    if report.get("status") != ("PASS_PARTIAL" if all(
            row["status"] in ("PASS", "PASS_PARTIAL") for row in rows) else "INCOMPLETE"):
        raise ValueError("local_summary_mismatch")
    return report["status"], rows


def _tcp_status(raw: dict[str, object]) -> tuple[str, str]:
    if not isinstance(raw, dict):
        return "INCOMPLETE", "tcp_contract_unverified"
    if raw.get("configuration") == "INVALID":
        return "FAIL", "configuration_invalid"
    if (raw.get("tcp_probe") == "PASS"
            and raw.get("configuration") == "RESOLVED"
            and raw.get("reason") == "configured_tcp_connected"
            and raw.get("host_scope") in ("LOOPBACK_IPV4", "RFC1918_IPV4")):
        return "PASS", "configured_tcp_connected"
    if raw.get("tcp_probe") == "FAIL" and raw.get("reason") == "configured_tcp_unavailable":
        return "FAIL", "configured_tcp_unavailable"
    if raw.get("tcp_probe") == "SKIP":
        reason = raw.get("reason")
        if reason in ("config_not_resolved", "endpoint_outside_bounded_tcp_scope"):
            return "SKIP", reason
    return "INCOMPLETE", "tcp_contract_unverified"


def _health_status(raw: dict[str, object]) -> tuple[str, str]:
    if not isinstance(raw, dict):
        return "INCOMPLETE", "health_contract_unverified"
    if (raw.get("http_probe") == "PASS" and raw.get("http_status") == 200
            and raw.get("reason") == "healthz_http_200"
            and raw.get("healthz_endpoint") == "/healthz"
            and raw.get("http_method") == "GET"):
        return "PASS", "healthz_http_200"
    if raw.get("http_probe") == "FAIL":
        return "FAIL", "healthz_http_unavailable"
    return "SKIP", "healthz_unverified"


def _l1_rows() -> tuple[dict[str, str] | None, list[dict[str, object]]]:
    from tools import sraf_airgap_off1b_auto as tcp
    try:
        with redirect_stdout(io.StringIO()):
            cfg = tcp._effective_runtime_config(ROOT)
    except Exception:
        return None, [_row("L1." + name, "SKIP", "runtime_config_unavailable")
                      for name in L1_CHECKS]
    rows = []
    for service in ("api", "es", "llm"):
        rows.append(_run("L1." + service + "_tcp", lambda service=service:
                         _tcp_status(tcp._observe(service, cfg, no_network=False))))
    if rows[0]["status"] != "PASS":
        rows.insert(1, _row("L1.api_health", "SKIP", "api_tcp_not_verified"))
    else:
        def health():
            from tools import sraf_airgap_off1b_api_http as api_http
            return _health_status(api_http._observe(cfg, no_network=False))
        rows.insert(1, _run("L1.api_health", health))
    return cfg, rows


def _sql_status() -> tuple[str, str]:
    from tools.sraf_airgap_off1_sql_hub import sql_constant_read_observation
    raw = sql_constant_read_observation()
    status = raw.get("status")
    reason = raw.get("reason")
    if (status == "PASS" and reason == "sql_constant_select_observed"
            and raw.get("constant_select_observed") is True):
        return status, reason
    if (status == "FAIL" and reason == "sql_read_response_invalid"
            and raw.get("constant_select_observed") is False):
        return status, reason
    if status == "SKIP" and reason in (
            "sql_read_config_invalid", "sql_read_driver_unavailable",
            "sql_read_connection_unverified", "sql_read_observation_unavailable"):
        return status, reason
    return "INCOMPLETE", "sql_contract_unverified"


def _es_status(cfg: dict[str, str]) -> tuple[str, str]:
    from tools.sraf_airgap_off1_es_hub import strict_mapping_observation
    raw = strict_mapping_observation(cfg, ROOT)
    status, reason = raw.get("status"), raw.get("reason")
    # A strict TLS/Mapping observation with no independent credential negative
    # control is deliberately SKIP, not a certified authenticated ES PASS.
    allowed = {
        "es_tls_identity_failed", "es_https_identity_failed",
        "es_auth_rejected", "es_mapping_failed", "es_strict_incomplete",
        "es_strict_observation_unavailable",
        "es_tls_mapping_observed_auth_not_verified",
    }
    if status in ("FAIL", "SKIP") and reason in allowed:
        return status, reason
    return "INCOMPLETE", "es_contract_unverified"


def _llm_status(cfg: dict[str, str], ollama_pid: int) -> tuple[str, str]:
    # Import is deferred until the operator explicitly authorizes a model call.
    from tools import sraf_airgap_off1d_readiness_matrix as matrix
    tcp = matrix._tcp_probe("llm", cfg, probe_network=True)
    inventory = matrix._llm_inventory(
        cfg, probe_network=True, probe_model_inventory=True,
        tcp_status=tcp["status"])
    result = matrix._llm_inference(
        cfg, probe_network=True, probe_model_inventory=True,
        probe_model_inference=True, inventory_status=inventory["status"],
        ollama_server_pid=ollama_pid)
    if result.get("id") != "LLM-INFERENCE":
        return "INCOMPLETE", "llm_contract_unverified"
    status, reason = result.get("status"), result.get("reason")
    if status == "PASS" and reason == "llm_inference_generation_observed":
        return status, reason
    if status in ("SKIP", "FAIL") and isinstance(reason, str) and SAFE_REASON.fullmatch(reason):
        if reason in matrix.REASONS:
            return status, reason
    return "INCOMPLETE", "llm_contract_unverified"


def _live_status(args: argparse.Namespace, launcher_port: str | None) -> tuple[str, str]:
    # The existing reviewed operator CLI enforces strict OFF-1S owner proof,
    # single POST, bounded polling, DOCX validation and no-follow private
    # evidence storage; do not implement another HTTP/report-job client.
    if not os.environ.get(args.token_env):
        return "SKIP", "report_token_unavailable"
    from tools import sraf_airgap_report_jobs_acceptance as jobs
    params = ["--suite", "quick", "--live-report",
              "--token-env", args.token_env, "--output-dir", args.output_dir,
              "--max-seconds", str(args.max_seconds)]
    captured = io.StringIO()
    # OFF-1B bootstrap loads dotenv into os.environ; the original launcher
    # PORT is the shell value BEFORE that load, not a later dotenv fallback.
    # Preserve that selection when delegating to the existing Jobs CLI.
    prior_port = os.environ.get("PORT")
    try:
        if launcher_port is None:
            os.environ.pop("PORT", None)
        else:
            os.environ["PORT"] = launcher_port
        with redirect_stdout(captured):
            code = jobs.main(params)
    finally:
        if prior_port is None:
            os.environ.pop("PORT", None)
        else:
            os.environ["PORT"] = prior_port
    # Never forward path-bearing evidence filenames, job IDs or log contents.
    lines = captured.getvalue().splitlines()
    if code == 0 and "SRAF_REPORT_JOBS_ACCEPTANCE=PASS_PARTIAL" in lines:
        return "PASS_PARTIAL", "one_report_job_docx_observed_only"
    if any(line == "SRAF_REPORT_JOBS_ACCEPTANCE=FAIL" for line in lines):
        return "FAIL", "report_job_acceptance_failed"
    return "SKIP", "report_job_acceptance_incomplete"


def run(args: argparse.Namespace) -> dict[str, object]:
    # Capture launch-time PORT before the runtime dotenv bootstrap changes env.
    launcher_port = os.environ.get("PORT")
    rows: list[dict[str, object]] = []
    try:
        l0_status, l0 = _local_rows(launcher_port)
        rows.extend(l0)
    except Exception:
        l0_status = "INCOMPLETE"
        rows.extend(_row("L0." + name, "INCOMPLETE", "local_probe_unavailable")
                    for name in L0_CHECKS)
    try:
        cfg, l1 = _l1_rows()
    except ModuleNotFoundError:
        cfg = None
        l1 = [_row("L1." + name, "INCOMPLETE", "l1_dependency_import_unavailable")
              for name in L1_CHECKS]
    except Exception:
        cfg = None
        l1 = [_row("L1." + name, "INCOMPLETE", "runtime_probe_unavailable")
              for name in L1_CHECKS]
    rows.extend(l1)
    l1_by_id = {row["id"]: row["status"] for row in l1}

    if args.level in ("L2", "L3"):
        for name, selected in (
                ("sql_constant_read", args.probe_sql_read),
                ("es_tls_mapping", args.probe_es_tls_mapping),
                ("llm_inference", args.probe_llm_inference)):
            if not selected:
                rows.append(_row("L2." + name, "NOT_TESTED", "probe_not_requested"))
            elif name == "sql_constant_read":
                rows.append(_run("L2." + name, _sql_status))
            elif cfg is None or l1_by_id.get("L1." + ("es_tcp" if name == "es_tls_mapping" else "llm_tcp")) != "PASS":
                rows.append(_row("L2." + name, "SKIP", "upstream_not_verified"))
            elif name == "es_tls_mapping":
                rows.append(_run("L2." + name, lambda: _es_status(cfg)))
            else:
                rows.append(_run("L2." + name, lambda: _llm_status(cfg, args.ollama_server_pid)))
    else:
        rows.extend(_row("L2." + name, "NOT_TESTED", "probe_not_requested")
                    for name in L2_CHECKS)

    if args.level == "L3":
        if (l0_status != "PASS_PARTIAL" or
                l1_by_id.get("L1.api_health") != "PASS" or
                l1_by_id.get("L1.es_tcp") != "PASS" or
                l1_by_id.get("L1.llm_tcp") != "PASS"):
            rows.append(_row("L3.report_job_docx", "SKIP", "prerequisites_not_verified"))
        else:
            rows.append(_run("L3.report_job_docx", lambda: _live_status(args, launcher_port)))
    else:
        rows.append(_row("L3.report_job_docx", "NOT_TESTED", "probe_not_requested"))
    # This runner never creates Requirement/Schedule fixtures. An observed Job
    # does NOT prove Requirement -> Scheduler -> Handoff full E2E.
    rows.append(_row("L3.requirement_schedule_handoff_e2e", "NOT_TESTED",
                     "full_e2e_not_implemented"))

    selected = [row for row in rows if row["status"] != "NOT_TESTED"]
    if any(row["status"] == "FAIL" for row in selected):
        overall = "FAIL"
    elif (any(row["status"] in ("SKIP", "INCOMPLETE", "WARN") for row in selected)
          or args.level == "L2" and not any((args.probe_sql_read,
                                              args.probe_es_tls_mapping,
                                              args.probe_llm_inference))):
        overall = "INCOMPLETE"
    else:
        overall = "PASS_PARTIAL"
    return {
        "schema": SCHEMA, "level": args.level, "status": overall,
        "production_release_ready": False,
        "full_requirement_schedule_handoff_e2e": "NOT_TESTED",
        "physical_airgap": "NOT_TESTED",
        "l2_selected": [name for name, flag in (
            ("sql_constant_read", args.probe_sql_read),
            ("es_tls_mapping", args.probe_es_tls_mapping),
            ("llm_inference", args.probe_llm_inference)) if flag],
        "l3_job_requested": args.live_report,
        "checks": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", choices=LEVELS, default="L1")
    parser.add_argument("--probe-sql-read", action="store_true")
    parser.add_argument("--probe-es-tls-mapping", action="store_true")
    parser.add_argument("--probe-llm-inference", action="store_true")
    parser.add_argument("--ollama-server-pid", type=int)
    parser.add_argument("--live-report", action="store_true")
    parser.add_argument("--token-env")
    parser.add_argument("--output-dir")
    parser.add_argument("--max-seconds", type=int, default=1200)
    args = parser.parse_args(argv)

    l2_selected = any((args.probe_sql_read, args.probe_es_tls_mapping,
                       args.probe_llm_inference))
    if (args.level == "L1" and l2_selected
            or args.level == "L3" and (not args.live_report or l2_selected)
            or args.level != "L3" and (args.live_report or args.token_env or args.output_dir)
            or args.probe_llm_inference != (args.ollama_server_pid is not None)
            or args.level == "L3" and (
                not args.token_env or not TOKEN_NAME.fullmatch(args.token_env)
                or not args.output_dir or not Path(args.output_dir).is_absolute())
            or args.max_seconds < 30 or args.max_seconds > 3600):
        parser.error("invalid layered diagnostic flags or missing explicit authorization")
    if Path.cwd().resolve() != ROOT:
        print("SRAF_DIAGNOSTICS=INCOMPLETE reason=run_from_repository_root")
        return 2
    result = run(args)
    print("SRAF 分層診斷 | " + args.level + " | " + result["status"])
    for row in result["checks"]:
        print(row["id"] + "=" + row["status"] + " reason=" + row["reason"]
              + " elapsed_ms=" + (str(row["elapsed_ms"]) if row["elapsed_ms"] is not None else "not_measured"))
    print("SRAF_DIAGNOSTICS_JSON=" + json.dumps(result, sort_keys=True,
          ensure_ascii=True, separators=(",", ":")))
    return 1 if result["status"] == "FAIL" else 2 if result["status"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
