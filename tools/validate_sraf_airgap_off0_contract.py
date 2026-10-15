#!/usr/bin/env python3
"""Validate the OFF-0 air-gap acceptance inventory without external dependencies.

This command validates contract shape and check dependencies only. It never
connects to SQL/ES/LLM, starts workers, imports SRA runtime, or runs E2E.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


MODES = ("quick", "diagnose", "acceptance")
EFFECTS = frozenset({"read_only", "compute_only", "test_job_write"})
READINESS = frozenset({"existing_component", "existing_external_smoke", "planned"})
STATUSES = ("PASS", "FAIL", "WARN", "SKIP")
CHECK_KEYS = frozenset({
    "id", "title", "component", "minimum_mode", "effect", "readiness",
    "depends_on", "existing_evidence", "error_code", "remediation",
})
REPORT_FIELDS = frozenset({
    "check_id", "component", "status", "severity", "error_code", "summary",
    "evidence", "remediation", "dependency", "duration_ms",
})
ROOT_KEYS = frozenset({
    "schema_version", "issue", "scope", "default_mode", "modes",
    "valid_states", "effects", "report_required", "checks", "report_policy",
})
REPORT_POLICY_KEYS = frozenset({
    "strategy", "summary_source", "remediation_source",
    "allow_raw_exceptions", "allow_unstructured_evidence",
    "max_evidence_entries", "max_evidence_value_chars", "permitted_evidence",
})
PERMITTED_EVIDENCE = {
    "http_status": "http_status",
    "item_count": "nonnegative_integer",
    "accepted_count": "nonnegative_integer",
    "rejected_count": "nonnegative_integer",
    "file_count": "nonnegative_integer",
    "worker_count": "nonnegative_integer",
    "component_size_bytes": "nonnegative_integer",
    "package_sha256": "sha256",
    "provenance_fingerprint": "sha256",
    "artifact_sha256": "sha256",
    "identity_verified": "boolean",
    "mapping_compatible": "boolean",
    "model_available": "boolean",
    "classification": "classification",
}
REPORT_SYSTEM_CODES = frozenset({
    "blocked_by_dependency", "check_not_implemented", "auth_session_unavailable",
    "mode_not_enabled",
})


class ContractError(ValueError):
    """A bounded validation error, safe to show in a terminal."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _validate_report_policy(policy: Any) -> None:
    _require(isinstance(policy, dict) and set(policy) == REPORT_POLICY_KEYS,
             "contract_report_policy_shape_invalid")
    _require(policy["strategy"] == "allowlisted_fields_fail_closed" and
             policy["summary_source"] == "inventory_check_title" and
             policy["remediation_source"] == "inventory_check_remediation" and
             policy["allow_raw_exceptions"] is False and
             policy["allow_unstructured_evidence"] is False and
             type(policy["max_evidence_entries"]) is int and
             policy["max_evidence_entries"] == 12 and
             type(policy["max_evidence_value_chars"]) is int and
             policy["max_evidence_value_chars"] == 80 and
             policy["permitted_evidence"] == PERMITTED_EVIDENCE,
             "contract_report_policy_unsafe")


def validate_contract(document: Any) -> int:
    _require(isinstance(document, dict), "contract_not_object")
    _require(set(document) == ROOT_KEYS, "contract_top_level_shape_invalid")
    _require(document.get("schema_version") == "sraf_airgap_off0_inventory_v1",
             "contract_schema_version_invalid")
    _require(document.get("scope") == "contract_only_not_executable",
             "contract_scope_invalid")
    _require(document.get("default_mode") == "quick", "contract_unsafe_default")
    _require(document.get("modes") == list(MODES), "contract_modes_invalid")
    _require(document.get("valid_states") == list(STATUSES),
             "contract_states_invalid")
    effects = document.get("effects")
    required = document.get("report_required")
    _require(isinstance(effects, list) and
             all(isinstance(v, str) for v in effects) and
             len(effects) == len(EFFECTS) and set(effects) == EFFECTS,
             "contract_effects_invalid")
    _require(isinstance(required, list) and
             all(isinstance(v, str) for v in required) and
             len(required) == len(REPORT_FIELDS) and
             set(required) == REPORT_FIELDS,
             "contract_report_fields_invalid")
    _validate_report_policy(document["report_policy"])
    checks = document.get("checks")
    _require(isinstance(checks, list) and bool(checks),
             "contract_checks_missing")
    by_id: dict[str, dict[str, Any]] = {}
    for item in checks:
        _require(isinstance(item, dict) and set(item) == CHECK_KEYS,
                 "contract_check_shape_invalid")
        identifier = item["id"]
        _require(isinstance(identifier, str) and identifier,
                 "contract_check_id_invalid")
        _require(identifier not in by_id, "contract_duplicate_check_id")
        for key in ("title", "component", "existing_evidence",
                    "error_code", "remediation"):
            _require(isinstance(item[key], str) and bool(item[key].strip()),
                     "contract_check_field_invalid")
        _require(item["minimum_mode"] in MODES, "contract_mode_invalid")
        _require(item["effect"] in EFFECTS, "contract_effect_invalid")
        _require(item["readiness"] in READINESS, "contract_readiness_invalid")
        _require(isinstance(item["depends_on"], list) and
                 all(isinstance(dep, str) and dep for dep in item["depends_on"]),
                 "contract_dependencies_invalid")
        _require(len(item["depends_on"]) == len(set(item["depends_on"])),
                 "contract_duplicate_dependency")
        if item["minimum_mode"] in ("quick", "diagnose"):
            _require(item["effect"] == "read_only",
                     "contract_readonly_mode_violation")
        by_id[identifier] = item

    checked: set[str] = set()
    active: set[str] = set()

    def visit(identifier: str) -> None:
        _require(identifier in by_id, "contract_unknown_dependency")
        _require(identifier not in active, "contract_dependency_cycle")
        if identifier in checked:
            return
        active.add(identifier)
        item = by_id[identifier]
        for dependency in item["depends_on"]:
            _require(dependency != identifier, "contract_self_dependency")
            _require(dependency in by_id, "contract_unknown_dependency")
            _require(MODES.index(by_id[dependency]["minimum_mode"]) <=
                     MODES.index(item["minimum_mode"]),
                     "contract_dependency_mode_violation")
            visit(dependency)
        active.remove(identifier)
        checked.add(identifier)

    for identifier in by_id:
        visit(identifier)
    return len(checked)


def make_report_record(
    contract: dict[str, Any], check_id: str, status: str, *,
    evidence: dict[str, object] | None = None,
    error_code: str | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    """Construct a bounded record only from reviewed strings and allowlisted facts.

    There is deliberately no argument for raw exception text, dynamic summary,
    free-form remediation, URLs, file paths, SQL queries, or secret-bearing logs.
    Future report runners MUST use this boundary instead of serializing probes.
    """
    validate_contract(contract)
    checks = {item["id"]: item for item in contract["checks"]}
    _require(isinstance(check_id, str) and check_id in checks,
             "report_check_unknown")
    check = checks[check_id]
    _require(status in STATUSES, "report_status_invalid")
    _require(not (status == "PASS" and check["readiness"] == "planned"),
             "report_unimplemented_pass")
    _require(type(duration_ms) is int and 0 <= duration_ms <= 86_400_000,
             "report_duration_invalid")
    permitted_codes = {check["error_code"]} | REPORT_SYSTEM_CODES
    _require(error_code is None or
             (isinstance(error_code, str) and error_code in permitted_codes),
             "report_error_code_unsafe")
    if status == "FAIL":
        _require(error_code is not None, "report_failure_code_missing")
    if status == "PASS":
        _require(error_code is None, "report_pass_with_error")
    if status == "SKIP":
        _require(error_code is not None, "report_skip_code_missing")
    values = evidence if evidence is not None else {}
    _require(isinstance(values, dict) and
             len(values) <= contract["report_policy"]["max_evidence_entries"],
             "report_evidence_invalid")
    policy = contract["report_policy"]["permitted_evidence"]
    safe: dict[str, object] = {}
    for key, value in values.items():
        _require(isinstance(key, str) and key in policy,
                 "report_evidence_key_unsafe")
        kind = policy[key]
        if kind == "nonnegative_integer":
            ok = type(value) is int and 0 <= value <= 10**12
        elif kind == "http_status":
            ok = type(value) is int and 100 <= value <= 599
        elif kind == "boolean":
            ok = type(value) is bool
        elif kind == "sha256":
            ok = (isinstance(value, str) and
                  re.fullmatch(r"[0-9a-f]{64}", value) is not None)
        elif kind == "classification":
            ok = value in ("FULL_LIVE", "HYBRID", "OFFLINE")
        else:
            ok = False
        _require(ok and
                 (not isinstance(value, str) or
                  len(value) <= contract["report_policy"]["max_evidence_value_chars"]),
                 "report_evidence_value_unsafe")
        safe[key] = value
    return {
        "check_id": check_id,
        "component": check["component"],
        "status": status,
        "severity": ("error" if status == "FAIL" else
                     "warning" if status == "WARN" else "info"),
        "error_code": error_code,
        "summary": check["title"],
        "evidence": safe,
        "remediation": check["remediation"] if status != "PASS" else None,
        "dependency": list(check["depends_on"]),
        "duration_ms": duration_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path,
        default=Path(__file__).resolve().parents[1] /
                "docs/operations/sraf_airgap_off0_checks.v1.json",
    )
    args = parser.parse_args()
    try:
        value = json.loads(args.registry.read_text(encoding="utf-8"))
        count = validate_contract(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"OFF0_CONTRACT = FAIL (contract_file_unreadable: {type(exc).__name__})")
        return 2
    except ContractError as exc:
        print(f"OFF0_CONTRACT = FAIL ({exc})")
        return 1
    print(f"OFF0_CONTRACT = PASS (checks={count}, schema-only; no runtime probes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
