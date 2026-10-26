"""OFF-1D operator readiness matrix: existing bounded probes, NEVER full acceptance.

Default is entirely offline except fixed local filesystem observations. Opt in
to network with --probe-network: at most one configured private IPv4 TCP connect
each for API, ES, and LLM, plus one anonymous 127.0.0.1 GET /healthz when the
API TCP connection succeeds. A separate triple opt-in can make one local
bounded LLM generation POST; never contacts SQL, starts workers or tests
physical network isolation. The optional --probe-sql-read
switch (also requiring --probe-network) can execute exactly one TLS-verified
constant SELECT using separate operator-only SQL credentials.

From deployed repository root:
    python tools/sraf_airgap_off1d_readiness_matrix.py
    python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sraf_airgap_off1b_auto as tcp  # noqa: E402
from tools import sraf_airgap_off1b_api_http as api_http  # noqa: E402
from tools.sraf_airgap_off1q_remote_report_job import (  # noqa: E402
    PORT_KEY as REPORT_LIVE_PORT_KEY,
    TOKEN_KEY as REPORT_LIVE_TOKEN_KEY,
    probe_remote_report_job,
)
from tools.sraf_airgap_off1p_docx_integrity import (  # noqa: E402
    ARTIFACT_ROOT_KEY, probe_docx_byte_integrity,
)
from tools.sraf_airgap_off1o_report_checkpoint import (  # noqa: E402
    probe_report_sql_checkpoint,
)
from tools.sraf_airgap_off1n_handoff_ack import (  # noqa: E402
    probe_handoff_sql_ack,
)
from tools.sraf_airgap_off1m_schedule_run_link import (  # noqa: E402
    probe_schedule_run_link,
)
from tools.sraf_airgap_off1l_schedule_claim import (  # noqa: E402
    SCHEDULE_ID_KEY, probe_schedule_claim_ledger,
)
from tools.sraf_airgap_off1k_handoff_owner import (  # noqa: E402
    probe_handoff_local_owner,
)
from tools.sraf_airgap_off1j_handoff_renewal import (  # noqa: E402
    probe_handoff_lease_renewal,
)
from tools.sraf_airgap_off1i_handoff_lease import (  # noqa: E402
    SCHEMA_KEY as LEASE_SCHEMA_KEY, DEFAULT_SCHEMA as LEASE_SCHEMA_DEFAULT,
    probe_handoff_lease_snapshot,
)
from tools.sraf_airgap_off1h_worker_identity import (  # noqa: E402
    probe_worker_process_identities,
)
from tools.sraf_airgap_off1g_sql_read import (  # noqa: E402
    ENV_KEYS as SQL_ENV_KEYS, probe_sql_constant_read,
)
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
    "llm_inference_cloud_disable_unverified", "llm_inference_remote_response",
    "sql_read_not_requested", "sql_read_odbc_not_passed",
    "sql_read_config_invalid", "sql_read_driver_unavailable",
    "sql_read_connection_unverified", "sql_read_response_invalid",
    "sql_constant_select_observed",
    "worker_process_probe_not_requested", "worker_process_host_unsupported",
    "worker_process_identity_unverified", "worker_process_identities_verified",
    "lease_probe_not_requested", "lease_sql_read_not_passed",
    "lease_schema_invalid", "lease_sql_config_invalid",
    "lease_driver_unavailable", "lease_row_ambiguous",
    "lease_row_not_observed", "lease_result_invalid",
    "lease_active_state_unverified", "lease_active_snapshot_observed",
    "lease_sql_unverified",
    "lease_renewal_not_requested", "lease_renewal_snapshot_not_passed",
    "lease_renewal_schema_invalid", "lease_renewal_config_invalid",
    "lease_renewal_driver_unavailable", "lease_renewal_sql_unverified",
    "lease_renewal_rows_ambiguous", "lease_renewal_row_unavailable",
    "lease_renewal_result_invalid", "lease_renewal_snapshot_inactive",
    "lease_renewal_wait_interrupted", "lease_renewal_generation_changed",
    "lease_renewal_not_advanced", "lease_renewal_advanced",
    "owner_not_requested", "owner_upstream_not_passed",
    "owner_schema_invalid", "owner_sql_config_invalid",
    "owner_local_identity_unverified", "owner_local_identity_changed",
    "owner_driver_unavailable", "owner_rows_ambiguous",
    "owner_row_unavailable", "owner_result_invalid",
    "owner_binding_unverified", "owner_local_sql_match_observed",
    "owner_sql_unverified",
    "claim_not_requested", "claim_upstream_not_passed",
    "claim_schedule_id_invalid", "claim_schema_invalid",
    "claim_sql_config_invalid", "claim_driver_unavailable",
    "claim_sql_unverified", "claim_result_invalid",
    "claim_wait_interrupted", "claim_not_advanced",
    "claim_actor_labeled_run_added",
    "link_not_requested", "link_claim_not_passed",
    "link_schedule_id_invalid", "link_schema_invalid",
    "link_sql_config_invalid", "link_driver_unavailable",
    "link_sql_unverified", "link_rows_ambiguous",
    "link_schedule_not_observed", "link_result_invalid",
    "link_predicates_unverified", "link_current_schedule_run_observed",
    "ack_not_requested", "ack_link_not_passed", "ack_schema_invalid",
    "ack_schedule_id_invalid", "ack_sql_config_invalid",
    "ack_driver_unavailable", "ack_sql_unverified",
    "ack_rows_ambiguous", "ack_schedule_not_observed",
    "ack_result_invalid", "ack_predicates_unverified",
    "ack_persisted_submission_observed",
    "report_checkpoint_not_requested",
    "report_checkpoint_ack_not_passed",
    "report_checkpoint_schema_invalid",
    "report_checkpoint_schedule_id_invalid",
    "report_checkpoint_sql_config_invalid",
    "report_checkpoint_driver_unavailable",
    "report_checkpoint_sql_unverified",
    "report_checkpoint_rows_ambiguous",
    "report_checkpoint_schedule_absent",
    "report_checkpoint_result_invalid",
    "report_checkpoint_not_observed",
    "report_checkpoint_persisted",
    "docx_not_requested", "docx_checkpoint_not_passed",
    "docx_root_invalid", "docx_schema_invalid",
    "docx_schedule_id_invalid", "docx_sql_config_invalid",
    "docx_driver_unavailable", "docx_reference_ambiguous",
    "docx_reference_absent", "docx_reference_invalid",
    "docx_reference_sql_unverified", "docx_host_unsupported",
    "docx_root_mismatch", "docx_path_invalid",
    "docx_file_unverified", "docx_digest_mismatch",
    "docx_structure_invalid", "docx_local_bytes_match",
    "remote_not_requested", "remote_docx_not_passed",
    "remote_schema_invalid", "remote_schedule_id_invalid",
    "remote_port_invalid", "remote_token_invalid",
    "remote_sql_config_invalid", "remote_driver_unavailable",
    "remote_reference_ambiguous", "remote_reference_absent",
    "remote_reference_invalid", "remote_sql_unverified",
    "remote_http_unverified", "remote_response_invalid",
    "remote_response_oversized", "remote_job_identity_mismatch",
    "remote_submission_mismatch", "remote_state_disagrees",
    "remote_still_in_progress", "remote_completed_attested",
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
                   inventory_status: str,
                   ollama_server_pid: int | None = None) -> dict[str, Any]:
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
    # No PID -> never invoke the generation helper; a value from the
    # CLI does not attest identity until /proc checks inside the helper.
    if (type(ollama_server_pid) is not int or ollama_server_pid < 2
            or ollama_server_pid > 4_194_304):
        return result("SKIP", "llm_inference_cloud_disable_unverified")
    try:
        obs = probe_local_ollama_inference(
            endpoint["port"], model, ollama_server_pid=ollama_server_pid)
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


def _sql_constant_read(*, probe_network: bool, probe_sql_read: bool,
                       odbc_status: str, sql_config: dict[str, str] | None
                       ) -> dict[str, Any]:
    """Only a separate operator-supplied constant SELECT, never app tables."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "SQL-READ", "sql", "sql_server_constant_select_only",
            status, reason, executed=executed, depends_on=("SQL-ODBC",),
        )

    if not probe_network or not probe_sql_read:
        return result("NOT_TESTED", "sql_read_not_requested")
    if odbc_status != "PASS":
        return result("SKIP", "sql_read_odbc_not_passed")
    # No implicit production SQL connection strings, registry DB credentials,
    # or ambient process secrets are ever consulted by the nested probe.
    if not isinstance(sql_config, dict):
        return result("SKIP", "sql_read_config_invalid")
    try:
        obs = probe_sql_constant_read(sql_config)
        if obs.status == "PASS":
            if (obs.check_id == "SQL-01"
                    and obs.probe == "sql-constant-read"
                    and obs.aspect == "sql_server_constant_select_only"
                    and obs.executed is True
                    and obs.reason == "sql_constant_select_observed"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("constant_select_observed") is True):
                return result("PASS", "sql_constant_select_observed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status == "FAIL":
            return result("FAIL", _reason(obs.reason),
                          executed=bool(obs.executed))
        if obs.status == "SKIP":
            return result("SKIP", _reason(obs.reason),
                          executed=bool(obs.executed))
        return result("SKIP", "unexpected_probe_result")
    except Exception:
        return result("SKIP", "sql_read_connection_unverified")


def _worker_identities(*, probe_worker_identities: bool
                       ) -> dict[str, Any]:
    """Independent local role/PID evidence, NOT a worker lease or job proof."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "WORKERS", "workers", "schedule_handoff_process_identity_only",
            status, reason, executed=executed,
            depends_on=("API-HEALTH", "SQL-READ"),
        )
    if not probe_worker_identities:
        return result("NOT_TESTED", "worker_process_probe_not_requested")
    try:
        obs = probe_worker_process_identities(PROJECT_ROOT)
        if obs.status == "PASS":
            ev = obs.evidence
            if (obs.check_id == "WORKER-01"
                    and obs.probe == "worker-identities"
                    and obs.aspect == "schedule_handoff_process_identity_only"
                    and obs.executed is True
                    and obs.reason == "worker_process_identities_verified"
                    and isinstance(ev, dict)
                    and type(ev.get("verified_role_count")) is int
                    and ev["verified_role_count"] == 2):
                return result("PASS", "worker_process_identities_verified",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status == "SKIP":
            return result("SKIP", _reason(obs.reason),
                          executed=bool(obs.executed))
        if obs.status == "FAIL":
            return result("FAIL", _reason(obs.reason),
                          executed=bool(obs.executed))
        return result("SKIP", "unexpected_probe_result")
    except Exception:
        return result("SKIP", "worker_process_identity_unverified")


def _handoff_lease_snapshot(*, probe_network: bool,
                            probe_sql_read: bool,
                            probe_worker_lease: bool,
                            sql_read_status: str,
                            sql_config: dict[str, str] | None,
                            lease_schema: str | None) -> dict[str, Any]:
    """Independently observe one Handoff DB lease, not Schedule progress."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "HANDOFF-LEASE", "workers", "handoff_db_lease_snapshot_only",
            status, reason, executed=executed, depends_on=("SQL-READ",),
        )
    if not (probe_network and probe_sql_read and probe_worker_lease):
        return result("NOT_TESTED", "lease_probe_not_requested")
    if sql_read_status != "PASS":
        return result("SKIP", "lease_sql_read_not_passed")
    if not isinstance(sql_config, dict):
        return result("SKIP", "lease_sql_config_invalid")
    try:
        obs = probe_handoff_lease_snapshot(
            sql_config, schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "LEASE-01"
                    and obs.probe == "handoff-lease-snapshot"
                    and obs.aspect == "handoff_db_lease_snapshot_only"
                    and obs.executed is True
                    and obs.reason == "lease_active_snapshot_observed"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("active_lease_observed") is True):
                return result("PASS", "lease_active_snapshot_observed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status == "FAIL":
            return result("FAIL", _reason(obs.reason),
                          executed=bool(obs.executed))
        if obs.status == "SKIP":
            return result("SKIP", _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "lease_sql_unverified")
    return result("SKIP", "unexpected_probe_result")


def _handoff_lease_renewal(*, probe_network: bool,
                          probe_sql_read: bool,
                          probe_worker_lease: bool,
                          probe_lease_renewal: bool,
                          lease_status: str,
                          sql_config: dict[str, str] | None,
                          lease_schema: str | None) -> dict[str, Any]:
    """Extra operator-only 15s double snapshot; not worker ownership."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "HANDOFF-RENEWAL", "workers",
            "two_sample_db_heartbeat_advance_only",
            status, reason, executed=executed,
            depends_on=("SQL-READ", "HANDOFF-LEASE"),
        )
    if not (probe_network and probe_sql_read and probe_worker_lease
            and probe_lease_renewal):
        return result("NOT_TESTED", "lease_renewal_not_requested")
    if lease_status != "PASS":
        return result("SKIP", "lease_renewal_snapshot_not_passed")
    if not isinstance(sql_config, dict):
        return result("SKIP", "lease_renewal_config_invalid")
    try:
        obs = probe_handoff_lease_renewal(
            sql_config, schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT)
        if obs.status == "PASS":
            if (obs.check_id == "LEASE-02"
                    and obs.probe == "handoff-lease-renewal"
                    and obs.aspect == "two_sample_db_heartbeat_advance_only"
                    and obs.executed is True
                    and obs.reason == "lease_renewal_advanced"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("renewal_observed") is True):
                return result("PASS", "lease_renewal_advanced", executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status == "FAIL":
            return result("FAIL", _reason(obs.reason),
                          executed=bool(obs.executed))
        if obs.status == "SKIP":
            return result("SKIP", _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "lease_renewal_sql_unverified")
    return result("SKIP", "unexpected_probe_result")


def _handoff_local_owner(*, probe_network: bool,
                         probe_sql_read: bool, probe_worker_lease: bool,
                         probe_lease_renewal: bool,
                         probe_worker_identities: bool,
                         probe_handoff_owner: bool,
                         worker_status: str, renewal_status: str,
                         sql_config: dict[str, str] | None,
                         lease_schema: str | None) -> dict[str, Any]:
    """Bound local inherited owner to DB row; no environment guesses."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record(
            "HANDOFF-OWNER", "workers",
            "local_inherited_owner_matches_db_lease_only",
            status, reason, executed=executed,
            depends_on=("WORKERS", "HANDOFF-RENEWAL"),
        )
    if not (probe_network and probe_sql_read and probe_worker_lease
            and probe_lease_renewal and probe_worker_identities
            and probe_handoff_owner):
        return result("NOT_TESTED", "owner_not_requested")
    if worker_status != "PASS" or renewal_status != "PASS":
        return result("SKIP", "owner_upstream_not_passed")
    if not isinstance(sql_config, dict):
        return result("SKIP", "owner_sql_config_invalid")
    try:
        obs = probe_handoff_local_owner(
            sql_config, project_root=PROJECT_ROOT,
            schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "LEASE-03"
                    and obs.probe == "handoff-local-owner"
                    and obs.aspect == "local_inherited_owner_matches_db_lease_only"
                    and obs.executed is True
                    and obs.reason == "owner_local_sql_match_observed"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("local_owner_match_observed") is True):
                return result("PASS", "owner_local_sql_match_observed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("FAIL", "SKIP"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
        return result("SKIP", "unexpected_probe_result")
    except Exception:
        return result("SKIP", "owner_local_identity_unverified")


def _schedule_claim(*, probe_network: bool, probe_sql_read: bool,
                    probe_worker_identities: bool, probe_schedule_claim: bool,
                    sql_read_status: str, worker_status: str,
                    sql_config: dict[str, str] | None, schedule_id: str | None,
                    lease_schema: str | None) -> dict[str, Any]:
    """Read-only SQL actor-labelled run growth; never local PID attribution."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record("SCHEDULE-CLAIM", "workers",
                       "schedule_actor_labeled_run_increment_only",
                       status, reason, executed=executed,
                       depends_on=("SQL-READ", "WORKERS"))

    if not (probe_network and probe_sql_read and probe_worker_identities
            and probe_schedule_claim):
        return result("NOT_TESTED", "claim_not_requested")
    if sql_read_status != "PASS" or worker_status != "PASS":
        return result("SKIP", "claim_upstream_not_passed")
    if (not isinstance(sql_config, dict)
            or not isinstance(schedule_id, str)
            or not schedule_id):
        return result("SKIP", "claim_schedule_id_invalid")
    try:
        obs = probe_schedule_claim_ledger(
            sql_config, schedule_id=schedule_id,
            schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "SCHEDULE-01"
                    and obs.probe == "schedule-claim-ledger"
                    and obs.aspect == "schedule_actor_labeled_run_increment_only"
                    and obs.reason == "claim_actor_labeled_run_added"
                    and obs.executed is True
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("run_increment_observed") is True):
                return result("PASS", "claim_actor_labeled_run_added",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("SKIP", "FAIL"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "claim_sql_unverified")
    return result("SKIP", "unexpected_probe_result")


def _schedule_link(*, probe_network: bool, probe_sql_read: bool,
                   probe_worker_identities: bool, probe_schedule_claim: bool,
                   probe_schedule_link: bool, claim_status: str,
                   sql_config: dict[str, str] | None, schedule_id: str | None,
                   lease_schema: str | None) -> dict[str, Any]:
    """Extra explicitly authorized SQL linkage predicates, not PID proof."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record("SCHEDULE-LINK", "workers",
                       "latest_actor_labeled_run_schedule_link_only",
                       status, reason, executed=executed,
                       depends_on=("SQL-READ", "SCHEDULE-CLAIM"))
    if not (probe_network and probe_sql_read and probe_worker_identities
            and probe_schedule_claim and probe_schedule_link):
        return result("NOT_TESTED", "link_not_requested")
    if claim_status != "PASS":
        return result("SKIP", "link_claim_not_passed")
    if not isinstance(schedule_id, str) or not schedule_id:
        return result("SKIP", "link_schedule_id_invalid")
    if not isinstance(sql_config, dict):
        return result("SKIP", "link_sql_config_invalid")
    try:
        obs = probe_schedule_run_link(
            sql_config, schedule_id=schedule_id,
            schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "SCHEDULE-02"
                    and obs.probe == "schedule-run-link"
                    and obs.aspect == "latest_actor_labeled_run_schedule_link_only"
                    and obs.executed is True
                    and obs.reason == "link_current_schedule_run_observed"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("link_predicates_observed") is True):
                return result("PASS", "link_current_schedule_run_observed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("SKIP", "FAIL"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "link_sql_unverified")
    return result("SKIP", "unexpected_probe_result")


def _handoff_sql_ack(*, probe_network: bool, probe_sql_read: bool,
                     probe_worker_identities: bool, probe_schedule_claim: bool,
                     probe_schedule_link: bool, probe_handoff_ack: bool,
                     link_status: str, sql_config: dict[str, str] | None,
                     schedule_id: str | None,
                     lease_schema: str | None) -> dict[str, Any]:
    """A persisted SQL acknowledgement is NOT verified remote job execution."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record("HANDOFF-ACK", "workers",
                       "latest_schedule_run_persisted_handoff_ack_only",
                       status, reason, executed=executed,
                       depends_on=("SQL-READ", "SCHEDULE-LINK"))
    if not (probe_network and probe_sql_read and probe_worker_identities
            and probe_schedule_claim and probe_schedule_link
            and probe_handoff_ack):
        return result("NOT_TESTED", "ack_not_requested")
    if link_status != "PASS":
        return result("SKIP", "ack_link_not_passed")
    if not isinstance(schedule_id, str) or not schedule_id:
        return result("SKIP", "ack_schedule_id_invalid")
    if not isinstance(sql_config, dict):
        return result("SKIP", "ack_sql_config_invalid")
    try:
        obs = probe_handoff_sql_ack(
            sql_config, schedule_id=schedule_id,
            schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "HANDOFF-ACK-01"
                    and obs.probe == "handoff-sql-ack"
                    and obs.aspect == "latest_schedule_run_persisted_handoff_ack_only"
                    and obs.executed is True
                    and obs.reason == "ack_persisted_submission_observed"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("handoff_ack_persisted") is True):
                return result("PASS", "ack_persisted_submission_observed",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("SKIP", "FAIL"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "ack_sql_unverified")
    return result("SKIP", "unexpected_probe_result")


def _report_checkpoint(*, probe_network: bool, probe_sql_read: bool,
                       probe_worker_identities: bool, probe_schedule_claim: bool,
                       probe_schedule_link: bool, probe_handoff_ack: bool,
                       probe_report_checkpoint: bool, ack_status: str,
                       sql_config: dict[str, str] | None,
                       schedule_id: str | None,
                       lease_schema: str | None) -> dict[str, Any]:
    """Only persisted SQL item evidence, not actual remote/DOCX attestation."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record("REPORT-CHECKPOINT", "report",
                       "latest_schedule_run_one_item_persisted_completion_only",
                       status, reason, executed=executed,
                       depends_on=("SQL-READ", "HANDOFF-ACK"))
    if not (probe_network and probe_sql_read and probe_worker_identities
            and probe_schedule_claim and probe_schedule_link
            and probe_handoff_ack and probe_report_checkpoint):
        return result("NOT_TESTED", "report_checkpoint_not_requested")
    if ack_status != "PASS":
        return result("SKIP", "report_checkpoint_ack_not_passed")
    if not isinstance(schedule_id, str) or not schedule_id:
        return result("SKIP", "report_checkpoint_schedule_id_invalid")
    if not isinstance(sql_config, dict):
        return result("SKIP", "report_checkpoint_sql_config_invalid")
    try:
        obs = probe_report_sql_checkpoint(
            sql_config, schedule_id=schedule_id,
            schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "REPORT-CHECKPOINT-01"
                    and obs.probe == "report-sql-checkpoint"
                    and obs.aspect == "latest_schedule_run_one_item_persisted_completion_only"
                    and obs.executed is True
                    and obs.reason == "report_checkpoint_persisted"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("report_checkpoint_persisted") is True):
                return result("PASS", "report_checkpoint_persisted",
                              executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("SKIP", "FAIL"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "report_checkpoint_sql_unverified")
    return result("SKIP", "unexpected_probe_result")


def _docx_byte_check(*, probe_network: bool, probe_sql_read: bool,
                     probe_worker_identities: bool, probe_schedule_claim: bool,
                     probe_schedule_link: bool, probe_handoff_ack: bool,
                     probe_report_checkpoint: bool, probe_docx_bytes: bool,
                     checkpoint_status: str, sql_config: dict[str, str] | None,
                     schedule_id: str | None, lease_schema: str | None,
                     artifact_root: str | None) -> dict[str, Any]:
    """Only after seven prior flags/PASS; checks one local fd-bound file."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record("DOCX-BYTES", "report",
                       "one_persisted_item_local_docx_byte_match_only",
                       status, reason, executed=executed,
                       depends_on=("SQL-READ", "REPORT-CHECKPOINT"))
    if not (probe_network and probe_sql_read and probe_worker_identities
            and probe_schedule_claim and probe_schedule_link
            and probe_handoff_ack and probe_report_checkpoint
            and probe_docx_bytes):
        return result("NOT_TESTED", "docx_not_requested")
    if checkpoint_status != "PASS":
        return result("SKIP", "docx_checkpoint_not_passed")
    if not isinstance(schedule_id, str) or not schedule_id:
        return result("SKIP", "docx_schedule_id_invalid")
    if not isinstance(sql_config, dict):
        return result("SKIP", "docx_sql_config_invalid")
    if not isinstance(artifact_root, str) or not artifact_root:
        return result("SKIP", "docx_root_invalid")
    try:
        obs = probe_docx_byte_integrity(
            sql_config, schedule_id=schedule_id,
            artifact_root=artifact_root,
            schema=lease_schema if lease_schema is not None
            else LEASE_SCHEMA_DEFAULT,
        )
        if obs.status == "PASS":
            if (obs.check_id == "DOCX-BYTES-01"
                    and obs.probe == "docx-byte-integrity"
                    and obs.aspect == "one_persisted_item_local_docx_byte_match_only"
                    and obs.executed is True
                    and obs.reason == "docx_local_bytes_match"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("local_docx_byte_match") is True):
                return result("PASS", "docx_local_bytes_match", executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("SKIP", "FAIL"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "docx_file_unverified")
    return result("SKIP", "unexpected_probe_result")


def _report_live_check(*, probe_network: bool, probe_sql_read: bool,
                       probe_worker_identities: bool, probe_schedule_claim: bool,
                       probe_schedule_link: bool, probe_handoff_ack: bool,
                       probe_report_checkpoint: bool, probe_docx_bytes: bool,
                       probe_report_live: bool, docx_status: str,
                       sql_config: dict[str, str] | None,
                       schedule_id: str | None, lease_schema: str | None,
                       api_port: str | None, read_token: str | None
                       ) -> dict[str, Any]:
    """Ninth explicit opt-in: SQL-selected job then one authenticated GET."""
    def result(status: str, reason: str, *, executed: bool = False
               ) -> dict[str, Any]:
        return _record("REPORT-LIVE", "report",
                       "same_persisted_item_authenticated_remote_status_only",
                       status, reason, executed=executed,
                       depends_on=("SQL-READ", "DOCX-BYTES"))
    if not (probe_network and probe_sql_read and probe_worker_identities
            and probe_schedule_claim and probe_schedule_link
            and probe_handoff_ack and probe_report_checkpoint
            and probe_docx_bytes and probe_report_live):
        return result("NOT_TESTED", "remote_not_requested")
    if docx_status != "PASS":
        return result("SKIP", "remote_docx_not_passed")
    if not isinstance(schedule_id, str) or not schedule_id:
        return result("SKIP", "remote_schedule_id_invalid")
    if not isinstance(sql_config, dict):
        return result("SKIP", "remote_sql_config_invalid")
    try:
        obs = probe_remote_report_job(
            sql_config, schedule_id=schedule_id,
            schema=lease_schema if lease_schema is not None else LEASE_SCHEMA_DEFAULT,
            api_port=api_port, read_token=read_token,
        )
        if obs.status == "PASS":
            if (obs.check_id == "REPORT-LIVE-01"
                    and obs.probe == "report-job-loopback-get"
                    and obs.aspect == "same_persisted_item_authenticated_remote_status_only"
                    and obs.executed is True
                    and obs.reason == "remote_completed_attested"
                    and isinstance(obs.evidence, dict)
                    and obs.evidence.get("remote_job_completed_observed") is True):
                return result("PASS", "remote_completed_attested", executed=True)
            return result("SKIP", "unexpected_probe_result")
        if obs.status in ("SKIP", "FAIL"):
            return result(obs.status, _reason(obs.reason),
                          executed=bool(obs.executed))
    except Exception:
        return result("SKIP", "remote_http_unverified")
    return result("SKIP", "unexpected_probe_result")


def build_report(cfg: dict[str, str], *, probe_network: bool = False,
                 probe_model_inventory: bool = False,
                 probe_model_inference: bool = False,
                 ollama_server_pid: int | None = None,
                 probe_sql_read: bool = False,
                 sql_config: dict[str, str] | None = None,
                 probe_worker_identities: bool = False,
                 probe_worker_lease: bool = False,
                 probe_lease_renewal: bool = False,
                 probe_handoff_owner: bool = False,
                 probe_schedule_claim: bool = False,
                 probe_schedule_link: bool = False,
                 probe_handoff_ack: bool = False,
                 probe_report_checkpoint: bool = False,
                 probe_docx_bytes: bool = False,
                 probe_report_live: bool = False,
                 report_live_port: str | None = None,
                 report_live_token: str | None = None,
                 artifact_root: str | None = None,
                 schedule_id: str | None = None,
                 lease_schema: str | None = None
                 ) -> dict[str, Any]:
    """Run independent reviewed probes even when another component fails."""
    rows = [
        _local_probe("HOST-DISK", "host", "disk_space_only", probe_disk),
        _local_probe("SQL-ODBC", "sql", "odbc_library_file_only",
                     probe_odbc_library),
    ]
    odbc_status = rows[1]["status"]
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
    sql_read = _sql_constant_read(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        odbc_status=odbc_status, sql_config=sql_config,
    )
    lease_snapshot = _handoff_lease_snapshot(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_lease=probe_worker_lease,
        sql_read_status=sql_read["status"], sql_config=sql_config,
        lease_schema=lease_schema,
    )
    renewal = _handoff_lease_renewal(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_lease=probe_worker_lease,
        probe_lease_renewal=probe_lease_renewal,
        lease_status=lease_snapshot["status"], sql_config=sql_config,
        lease_schema=lease_schema,
    )
    workers = _worker_identities(probe_worker_identities=probe_worker_identities)
    owner = _handoff_local_owner(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_lease=probe_worker_lease,
        probe_lease_renewal=probe_lease_renewal,
        probe_worker_identities=probe_worker_identities,
        probe_handoff_owner=probe_handoff_owner,
        worker_status=workers["status"], renewal_status=renewal["status"],
        sql_config=sql_config, lease_schema=lease_schema,
    )
    schedule_claim = _schedule_claim(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_identities=probe_worker_identities,
        probe_schedule_claim=probe_schedule_claim,
        sql_read_status=sql_read["status"], worker_status=workers["status"],
        sql_config=sql_config, schedule_id=schedule_id,
        lease_schema=lease_schema,
    )
    schedule_link = _schedule_link(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_identities=probe_worker_identities,
        probe_schedule_claim=probe_schedule_claim,
        probe_schedule_link=probe_schedule_link,
        claim_status=schedule_claim["status"], sql_config=sql_config,
        schedule_id=schedule_id, lease_schema=lease_schema,
    )
    handoff_ack = _handoff_sql_ack(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_identities=probe_worker_identities,
        probe_schedule_claim=probe_schedule_claim,
        probe_schedule_link=probe_schedule_link,
        probe_handoff_ack=probe_handoff_ack,
        link_status=schedule_link["status"], sql_config=sql_config,
        schedule_id=schedule_id, lease_schema=lease_schema,
    )
    checkpoint = _report_checkpoint(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_identities=probe_worker_identities,
        probe_schedule_claim=probe_schedule_claim,
        probe_schedule_link=probe_schedule_link,
        probe_handoff_ack=probe_handoff_ack,
        probe_report_checkpoint=probe_report_checkpoint,
        ack_status=handoff_ack["status"], sql_config=sql_config,
        schedule_id=schedule_id, lease_schema=lease_schema,
    )
    docx_bytes = _docx_byte_check(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_identities=probe_worker_identities,
        probe_schedule_claim=probe_schedule_claim,
        probe_schedule_link=probe_schedule_link,
        probe_handoff_ack=probe_handoff_ack,
        probe_report_checkpoint=probe_report_checkpoint,
        probe_docx_bytes=probe_docx_bytes,
        checkpoint_status=checkpoint["status"], sql_config=sql_config,
        schedule_id=schedule_id, lease_schema=lease_schema,
        artifact_root=artifact_root,
    )
    report_live = _report_live_check(
        probe_network=probe_network, probe_sql_read=probe_sql_read,
        probe_worker_identities=probe_worker_identities,
        probe_schedule_claim=probe_schedule_claim,
        probe_schedule_link=probe_schedule_link,
        probe_handoff_ack=probe_handoff_ack,
        probe_report_checkpoint=probe_report_checkpoint,
        probe_docx_bytes=probe_docx_bytes,
        probe_report_live=probe_report_live, docx_status=docx_bytes["status"],
        sql_config=sql_config, schedule_id=schedule_id, lease_schema=lease_schema,
        api_port=report_live_port, read_token=report_live_token,
    )
    rows.extend((
        sql_read,
        lease_snapshot,
        renewal,
        owner,
        schedule_claim,
        schedule_link,
        handoff_ack,
        checkpoint,
        docx_bytes,
        report_live,
        _record("ES-MAPPING", "es", "authenticated_es_mapping", "NOT_TESTED",
                "es_tls_mapping_not_aggregated", depends_on=("ES-TCP",)),
        inventory,
        _llm_inference(cfg, probe_network=probe_network,
                       probe_model_inventory=probe_model_inventory,
                       probe_model_inference=probe_model_inference,
                       inventory_status=inventory["status"],
                       ollama_server_pid=ollama_server_pid),
        workers,
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
    parser.add_argument("--probe-sql-read", action="store_true",
                        help="With --probe-network, make one TLS-verified ODBC constant SELECT using dedicated operator SRAF_OFF1G_SQL_* secrets.")
    parser.add_argument("--probe-report-live", action="store_true",
                        help="With all eight Schedule/Handoff/Report/DOCX flags and real DOCX-BYTES PASS, do one SQL-bound authenticated localhost GET /v1/report/jobs/{id}, never create or download.")
    parser.add_argument("--probe-docx-bytes", action="store_true",
                        help="With all seven Schedule/Handoff/Report flags and real REPORT-CHECKPOINT PASS, verify one local published DOCX bytes and SQL digest; no remote API.")
    parser.add_argument("--probe-report-checkpoint", action="store_true",
                        help="Require six Schedule/Handoff flags plus this consent; read persisted per-item Report completion and artifact reconciliation SQL predicates only (no API/DOCX).")
    parser.add_argument("--probe-handoff-ack", action="store_true",
                        help="Require five Schedule SQL flags plus this explicit consent, then check latest run's persisted submission/remote-job acknowledgement in SQL (not remote API proof).")
    parser.add_argument("--probe-schedule-link", action="store_true",
                        help="Also require Schedule-claim observed PASS, then read SQL-computed latest-run/active-version/next-run predicates; not PID evidence.")
    parser.add_argument("--probe-schedule-claim", action="store_true",
                        help="With network, SQL-read and worker-identities flags, take two 15s-apart SQL ledger counts for SRAF_OFF1L_SCHEDULE_ID; never calls claim_due.")
    parser.add_argument("--probe-handoff-owner", action="store_true",
                        help="With ALL network/SQL/lease/renewal/worker-identity flags, compare the local Handoff process's inherited explicit owner with one SQL lease predicate.")
    parser.add_argument("--probe-lease-renewal", action="store_true",
                        help="With network, SQL-read and worker-lease flags, observe two SQL heartbeat snapshots 15 seconds apart.")
    parser.add_argument("--probe-worker-lease", action="store_true",
                        help="With --probe-network and --probe-sql-read, observe one TLS-verified Handoff lease snapshot (no worker progress proof).")
    parser.add_argument("--probe-worker-identities", action="store_true",
                        help="Read only canonical local Schedule/Handoff worker identity files and /proc; never leases or jobs.")
    parser.add_argument("--probe-llm-inventory", action="store_true",
                        help="With --probe-network, check anonymous localhost Ollama /api/tags once.")
    parser.add_argument("--probe-llm-inference", action="store_true",
                        help="With BOTH other flags, run one real local Ollama generation (may load model).")
    parser.add_argument("--ollama-server-pid", type=int, default=None,
                        help="Linux Ollama serve PID (only used with triple inference opt-in); verified /proc socket and OLLAMA_NO_CLOUD=1 are mandatory.")
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
        # Do not even inspect credential environment unless *both*
        # operator flags explicitly opted into SQL connectivity.
        sql_cfg = ({key: os.environ.get(key) for key in SQL_ENV_KEYS}
                   if args.probe_network and args.probe_sql_read else None)
        lease_schema = (os.environ.get(LEASE_SCHEMA_KEY, LEASE_SCHEMA_DEFAULT)
                        if args.probe_network and args.probe_sql_read
                        and (args.probe_worker_lease or args.probe_lease_renewal
                             or args.probe_schedule_claim)
                        else None)
        report = build_report(cfg, probe_network=args.probe_network,
                              probe_model_inventory=args.probe_llm_inventory,
                              probe_model_inference=args.probe_llm_inference,
                              ollama_server_pid=args.ollama_server_pid,
                              probe_sql_read=args.probe_sql_read,
                              sql_config=sql_cfg,
                              probe_worker_identities=args.probe_worker_identities,
                              probe_worker_lease=args.probe_worker_lease,
                              probe_lease_renewal=args.probe_lease_renewal,
                              probe_handoff_owner=args.probe_handoff_owner,
                              probe_schedule_claim=args.probe_schedule_claim,
                              probe_schedule_link=args.probe_schedule_link,
                              probe_handoff_ack=args.probe_handoff_ack,
                              probe_report_checkpoint=args.probe_report_checkpoint,
                              probe_docx_bytes=args.probe_docx_bytes,
                              probe_report_live=args.probe_report_live,
                              report_live_port=(
                                  os.environ.get(REPORT_LIVE_PORT_KEY)
                                  if all((args.probe_network, args.probe_sql_read,
                                          args.probe_worker_identities,
                                          args.probe_schedule_claim,
                                          args.probe_schedule_link,
                                          args.probe_handoff_ack,
                                          args.probe_report_checkpoint,
                                          args.probe_docx_bytes,
                                          args.probe_report_live)) else None),
                              report_live_token=(
                                  os.environ.get(REPORT_LIVE_TOKEN_KEY)
                                  if all((args.probe_network, args.probe_sql_read,
                                          args.probe_worker_identities,
                                          args.probe_schedule_claim,
                                          args.probe_schedule_link,
                                          args.probe_handoff_ack,
                                          args.probe_report_checkpoint,
                                          args.probe_docx_bytes,
                                          args.probe_report_live)) else None),
                              artifact_root=(os.environ.get(ARTIFACT_ROOT_KEY)
                                   if (args.probe_network and args.probe_sql_read
                                       and args.probe_worker_identities
                                       and args.probe_schedule_claim
                                       and args.probe_schedule_link
                                       and args.probe_handoff_ack
                                       and args.probe_report_checkpoint
                                       and args.probe_docx_bytes) else None),
                              schedule_id=(os.environ.get(SCHEDULE_ID_KEY)
                                   if (args.probe_network and args.probe_sql_read
                                       and args.probe_worker_identities
                                       and args.probe_schedule_claim) else None),
                              lease_schema=lease_schema)
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
