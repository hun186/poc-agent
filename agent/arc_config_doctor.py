"""Offline ARC process-environment preflight; no ES/LLM/SQL or file writes.

Report only fixed flag names, normalized statuses and bounded effective
budgets. Configuration validity is not runtime authorization or readiness.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
import re
import sys

from agent.arc_mode import LOCAL_SHADOW_FLAGS, SHADOW_FLAGS, arc_shadow_enabled

_INDEX = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")


def _index_configured(value):
    return bool(value and _INDEX.fullmatch(value) and ".." not in value)


def configuration_report():
    from agent.es.evidence_core.group_frequency import GroupFrequencyBudget
    from agent.es.arc_semantic_review_transport import _approved_endpoint

    mode = os.getenv("SRAF_ARC_MODE")
    normalized_mode = ("legacy" if mode is None else mode
                       if mode in ("off", "shadow") else "unsupported")
    flags = {}
    for name in sorted(SHADOW_FLAGS):
        raw = os.getenv(name)
        enabled = arc_shadow_enabled(name)
        flags[name] = {
            "setting": ("unset" if raw is None else raw
                        if raw in ("off", "shadow") else "invalid"),
            "enabled_by_mode": enabled,
            "status": "eligible_for_observation" if enabled else "disabled",
            "reasons": [],
        }
        if raw is not None and raw not in ("off", "shadow"):
            flags[name]["reasons"].append("invalid_feature_setting")
        if raw == "shadow" and not enabled:
            flags[name]["reasons"].append("master_mode_blocks")
        if mode == "shadow" and name in LOCAL_SHADOW_FLAGS and raw == "off":
            flags[name]["reasons"].append("explicit_local_override")

    def require(name, condition, reason):
        row = flags[name]
        if row["enabled_by_mode"] and not condition:
            row["status"] = "configuration_blocked"
            row["reasons"].append(reason)

    def pending(name, reason):
        row = flags[name]
        if row["enabled_by_mode"]:
            if row["status"] != "configuration_blocked":
                row["status"] = "requires_runtime_scope"
            row["reasons"].append(reason)

    def enabled(name):
        return flags[name]["enabled_by_mode"]

    require("SRAF_ARC_RANK", enabled("SRAF_ARC_GROUP_FREQUENCY"), "group_frequency_disabled")
    for name in ("SRAF_ARC_BILINGUAL", "SRAF_ARC_STRATEGY"):
        require(name, bool(os.getenv("TOPIC_LLM_URL")), "topic_model_gate_missing")
        # MODEL_BASE_URL is not asserted here: the existing client may be
        # configured by its caller. This check cannot attest its endpoint.
        pending(name, "existing_model_and_shared_budget_required")
    require("SRAF_ARC_LLM_PRIORITY",
            enabled("SRAF_ARC_BILINGUAL") or enabled("SRAF_ARC_STRATEGY"),
            "no_optional_strategy_enabled")
    native = _index_configured(os.getenv("SRAF_ARC_ES_FREQUENCY_VERIFIED_INDEX"))
    deep = _index_configured(os.getenv("SRAF_ARC_DEEP_FREQUENCY_VERIFIED_INDEX"))
    review_index = os.getenv("SRAF_ARC_REVIEW_VERIFIED_INDEX", "")
    for freq, rank, valid, reason in (
        ("SRAF_ARC_ES_FREQUENCY", "SRAF_ARC_RANK_NATIVE", native,
         "live_mapping_analyzer_and_primary_scope_required"),
        ("SRAF_ARC_DEEP_FREQUENCY", "SRAF_ARC_RANK_DEEP", deep,
         "independent_worker_frequency_policy_required"),
    ):
        require(freq, valid, "verified_concrete_index_missing_or_invalid")
        pending(freq, reason)
        require(rank, enabled(freq) and valid, "native_frequency_not_configured")
        pending(rank, "matching_private_frequency_receipt_required")

    require("SRAF_ARC_REVIEW_SCOPE", _index_configured(review_index),
            "verified_concrete_index_missing_or_invalid")
    pending("SRAF_ARC_REVIEW_SCOPE", "local_scope_only_no_ordinary_model_transport")
    endpoint_valid = _approved_endpoint(review_index) is not None
    require("SRAF_ARC_REVIEW", endpoint_valid, "review_endpoint_or_egress_not_configured")
    pending("SRAF_ARC_REVIEW", "independent_document_and_endpoint_policy_required")
    require("SRAF_ARC_REVIEW_DEEP", endpoint_valid and enabled("SRAF_ARC_REVIEW"),
            "review_transport_not_configured")
    pending("SRAF_ARC_REVIEW_DEEP", "trusted_worker_policy_required")
    require("SRAF_ARC_REVIEW_RESOURCE_METRICS", endpoint_valid and enabled("SRAF_ARC_REVIEW_DEEP"),
            "deep_review_not_configured")
    pending("SRAF_ARC_REVIEW_RESOURCE_METRICS", "authorized_model_attempt_required")

    # Local observations still depend on actual report shape and admission.
    for name in LOCAL_SHADOW_FLAGS:
        if flags[name]["enabled_by_mode"] and flags[name]["status"] != "configuration_blocked":
            flags[name]["status"] = "eligible_for_observation"

    effective = asdict(GroupFrequencyBudget.from_env())
    ceilings = asdict(GroupFrequencyBudget())
    budget_notes = {}
    for key, ceiling in ceilings.items():
        raw = os.getenv("SRAF_ARC_GROUP_FREQUENCY_MAX_" + key.upper(), "")
        if raw:
            if not (len(raw) <= 9 and raw.isascii() and raw.isdecimal() and int(raw) > 0):
                budget_notes[key] = "invalid_uses_default"
            elif int(raw) > ceiling:
                budget_notes[key] = "clamped_to_ceiling"

    legacy = os.getenv("SRAF_TOPIC_MATCH_ADAPTIVE", "off")
    invalid = (normalized_mode == "unsupported" or bool(budget_notes)
               or any(row["setting"] == "invalid" or row["status"] == "configuration_blocked"
                      for row in flags.values()))
    return {
        "schema": "sraf_arc_config_preflight_v1",
        "scope": "current_process_environment_only",
        "status": "CONFIG_ATTENTION" if invalid else "CONFIG_CHECKED",
        "mode": normalized_mode,
        "formal_arc_selection_enabled": False,
        "runtime_authorization_verified": False,
        "live_connectivity_verified": False,
        "features": flags,
        "group_frequency_budget": effective,
        "budget_notes": budget_notes,
        "legacy_topic_adaptive": legacy if legacy in ("off", "shadow", "on") else "invalid",
        "legacy_topic_adaptive_can_change_selection": legacy == "on",
    }


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--help"], ["-h"]):
        print("python -m agent.arc_config_doctor  # checks only the current process environment")
        return 0
    if args:
        print('{"status":"INVALID_ARGUMENTS"}', file=sys.stderr)
        return 2
    try:
        result = configuration_report()
    except Exception:
        print('{"status":"CONFIG_CHECK_UNAVAILABLE"}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 2 if result["status"] == "CONFIG_ATTENTION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
