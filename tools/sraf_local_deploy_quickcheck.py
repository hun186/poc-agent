#!/usr/bin/env python3
"""SRAF one-command LOCAL passive deployment quickcheck: no network or writes.

Combines already-reviewed OFF-1H/1S/OFF-2 probes. No service startup,
credentials, HTTP/TCP, SQL/ES/LLM, package imports, installer or report file.
This is NOT a production-release, airgap or live-business acceptance runner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_off2_linux_target as platform_probe
from tools import sraf_airgap_off2_user_site as deps_probe
from tools import sraf_airgap_off2_runtime_launchers as launch_probe
from tools import sraf_airgap_off1_probes as host_probe

# The existing worker/listener modules transitively depend on pyodbc/dotenv.
# Load ONLY when their individual check runs, so an unavailable native
# dependency cannot prevent independent platform/deps/launcher/disk results.
def _load_worker_identity_probe():
    from tools.sraf_airgap_off1h_worker_identity import probe_worker_process_identities
    return probe_worker_process_identities


def _load_api_listener_module():
    from tools import sraf_airgap_off1s_api_listener
    return sraf_airgap_off1s_api_listener


SCHEMA = "sraf_local_deploy_quickcheck_v1"
MODE = "LOCAL_PASSIVE_NO_NETWORK_NO_ARTIFACTS"
_CHECK_NAMES = (
    "target_platform", "direct_distribution_metadata", "static_launchers",
    "host_disk", "worker_process_identity", "api_listener_preflight",
)
_API_STAGES = (
    "root_nofollow", "api_identity_record", "process_identity",
    "tcp_listener_unique", "pid_owns_socket", "procfs_unfiltered",
)
_OK = frozenset(("PASS", "PASS_PARTIAL"))
_MAX_REQUIREMENTS = 256


def _row(name: str, status: str, reason: str, **details: object) -> dict[str, object]:
    if name not in _CHECK_NAMES or status not in (
            "PASS", "PASS_PARTIAL", "WARN", "SKIP", "INCOMPLETE"):
        raise ValueError("invalid_check_status")
    if not reason.isascii() or not reason.replace("_", "").isalnum():
        raise ValueError("invalid_check_reason")
    return {"id": name, "status": status, "reason": reason, **details}


def _target() -> dict[str, object]:
    result = platform_probe.observe()
    good = result.get("status") == "PASS_PARTIAL"
    return _row("target_platform", "PASS_PARTIAL" if good else "INCOMPLETE",
                "target_platform_metadata_observed" if good
                else "target_platform_metadata_unverified",
                odbc_registration_metadata_observed=(
                    result.get("odbc18") == "REGISTERED_CONFIG_ONLY"),
                odbc_binary_header_observed=(
                    result.get("odbc_binary_header") == "ELF64_ARCH_MATCH_HEADER_ONLY"),
                native_odbc_load="NOT_TESTED")


def _deps(root: Path) -> dict[str, object]:
    result = deps_probe.observe(root)
    n, found, scheme, user, unlocked = (
        result.get(k) for k in (
            "requirements_checked", "installed_direct_count",
            "scheme_installed_direct_count", "user_site_fallback_direct_count",
            "unlocked_direct_count",
        )
    )
    # Accept only validated numeric counts, never return arbitrary/untrusted
    # metadata names or paths. A partial failed scan may have zero counts.
    if (any(type(v) is not int or v < 0 or v > _MAX_REQUIREMENTS
            for v in (n, found, scheme, user, unlocked))
            or scheme + user != found or found > n or unlocked > n):
        return _row("direct_distribution_metadata", "INCOMPLETE",
                    "direct_distribution_counts_unverified")
    good = result.get("status") == "PASS_PARTIAL" and n > 0 and n == found
    return _row("direct_distribution_metadata",
                "PASS_PARTIAL" if good else "INCOMPLETE",
                "all_direct_metadata_observed_only" if good
                else "direct_metadata_incomplete",
                requirements_checked=n, metadata_observed=found,
                scheme_observed=scheme, active_user_site_fallback_observed=user,
                unlocked_direct_count=unlocked,
                package_imports="NOT_TESTED",
                transitive_closure="NOT_TESTED",
                wheelhouse_compatibility="NOT_TESTED")


def _launchers() -> dict[str, object]:
    result = launch_probe.observe()
    py = result.get("path_python_identity")
    uv = result.get("uvicorn_shebang_identity")
    allowed_py = ("MATCH", "MISMATCH", "UNVERIFIABLE")
    allowed_uv = ("DIRECT_MATCH", "ENV_MATCH", "MISMATCH",
                  "UNAVAILABLE", "UNVERIFIABLE")
    if py not in allowed_py or uv not in allowed_uv:
        return _row("static_launchers", "INCOMPLETE",
                    "launcher_identity_unverifiable")
    good = result.get("status") == "PASS_PARTIAL" and py == "MATCH" and uv in (
        "DIRECT_MATCH", "ENV_MATCH",
    )
    return _row("static_launchers", "PASS_PARTIAL" if good else "INCOMPLETE",
                "current_shell_launcher_identity_only" if good
                else "current_shell_launcher_identity_unverified",
                path_python_identity=py, uvicorn_shebang_identity=uv,
                selected_python_user_site_active=(
                    result.get("selected_python_user_site_active") is True),
                actual_service_python_verified=False)


def _disk() -> dict[str, object]:
    result = host_probe.probe_disk()
    status = result.status if result.status in ("PASS", "WARN") else "INCOMPLETE"
    return _row("host_disk", status,
                "disk_threshold_met" if status == "PASS"
                else "disk_space_low" if status == "WARN"
                else "disk_information_unavailable")


def _workers(root: Path) -> dict[str, object]:
    result = _load_worker_identity_probe()(root)
    count = result.evidence.get("verified_role_count")
    if type(count) is not int or not 0 <= count <= 2:
        return _row("worker_process_identity", "INCOMPLETE",
                    "worker_identity_evidence_unverified")
    good = (result.status == "PASS"
            and result.reason == "worker_process_identities_verified"
            and count == 2)
    return _row("worker_process_identity",
                "PASS_PARTIAL" if good else "INCOMPLETE",
                "recorded_schedule_handoff_process_identity_only" if good
                else "worker_process_identity_unverified",
                verified_role_count=count, required_roles=2,
                worker_business_execution="NOT_TESTED")


def _api_preflight(root: Path) -> dict[str, object]:
    """Reuse OFF-1S strict prerequisites, without its expensive global FD scan.

    The six checks here never attest *exclusive* socket ownership or grant
    any listener proof. Keeping those explicitly NOT_TESTED is essential.
    """
    stage = _API_STAGES[0]
    passed = 0
    fd = None
    try:
        listener_probe = _load_api_listener_module()
        fd = listener_probe._pin_root_directory(root)
        passed += 1
        stage = _API_STAGES[1]
        identity = listener_probe._identity(fd, 9002)
        if identity is None:
            return _api_result(passed, stage)
        passed += 1
        pid, start = identity
        stage = _API_STAGES[2]
        if not listener_probe._same_process(pid, start, os.fstat(fd), 9002):
            return _api_result(passed, stage)
        passed += 1
        stage = _API_STAGES[3]
        inode = listener_probe._listener_inode(9002)
        if inode is None:
            return _api_result(passed, stage)
        passed += 1
        stage = _API_STAGES[4]
        if not listener_probe._owns_socket(pid, inode):
            return _api_result(passed, stage)
        passed += 1
        stage = _API_STAGES[5]
        if not listener_probe._procfs_unfiltered():
            return _api_result(passed, stage)
        passed += 1
    except (OSError, ValueError, RuntimeError, TypeError,
            UnicodeError, OverflowError):
        return _api_result(passed, stage)
    finally:
        if fd is not None:
            os.close(fd)
    return _api_result(passed, None)


def _api_result(passed: int, failed_at: str | None) -> dict[str, object]:
    good = failed_at is None and passed == len(_API_STAGES)
    return _row("api_listener_preflight",
                "PASS_PARTIAL" if good else "INCOMPLETE",
                "six_api_listener_prerequisites_observed_only" if good
                else "api_listener_prerequisite_unverified",
                prerequisites_observed=passed,
                prerequisites_total=len(_API_STAGES),
                first_unverified_gate=failed_at or "NONE",
                strict_listener_exclusive_socket_owner="NOT_TESTED",
                strict_api_listener_attested=False,
                api_http_health="NOT_TESTED")


def observe(root: Path) -> dict[str, object]:
    """Independent probes: a failed check never masks subsequent observations."""
    rows = []
    if (not isinstance(root, Path) or not root.is_absolute()
            or root != PROJECT_ROOT):
        for name in _CHECK_NAMES:
            rows.append(_row(name, "INCOMPLETE", "repository_root_unverified"))
    else:
        for name, run in (
                ("target_platform", _target),
                ("direct_distribution_metadata", lambda: _deps(root)),
                ("static_launchers", _launchers),
                ("host_disk", _disk),
                ("worker_process_identity", lambda: _workers(root)),
                ("api_listener_preflight", lambda: _api_preflight(root))):
            try:
                result = run()
                if result["id"] != name:
                    raise ValueError("check_identity_mismatch")
            except Exception:
                # Do not propagate paths, native exception text, process
                # details or data from a failed subprobe.
                result = _row(name, "INCOMPLETE", "passive_probe_unverifiable")
            rows.append(result)
    good = all(r["status"] in _OK for r in rows)
    return {
        "schema": SCHEMA, "mode": MODE,
        "status": "PASS_PARTIAL" if good else "INCOMPLETE",
        "reason": "local_passive_observations_complete_only" if good
                  else "some_local_passive_observations_incomplete",
        "checks": rows,
        "required_passive_checks": len(_CHECK_NAMES),
        "passive_checks_observed": sum(r["status"] in _OK for r in rows),
        "network_requests_performed": False,
        "evidence_file_written": False,
        "strict_api_listener_attested": False,
        "actual_api_worker_python_environment_verified": False,
        "real_sql_es_llm_report_jobs": "NOT_TESTED",
        "native_odbc_load": "NOT_TESTED",
        "trusted_offline_wheelhouse": "NOT_TESTED",
        "full_live_acceptance": "NOT_TESTED",
        "production_release_ready": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = observe(Path.cwd())
    print("SRAF LOCAL DEPLOY QUICKCHECK | PASSIVE NO-NETWORK NO-WRITE")
    for check in result["checks"]:
        print(f"{check['id']}={check['status']} reason={check['reason']}")
    print(f"RESULT={result['status']} production_release_ready=false")
    print("SRAF_DEPLOY_CHECK_JSON=" + json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0 if result["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
