#!/usr/bin/env python3
"""Validate the OFF-0 air-gap acceptance inventory without external dependencies.

This command validates contract shape and check dependencies only. It never
connects to SQL/ES/LLM, starts workers, imports SRA runtime, or runs E2E.
"""
from __future__ import annotations

import argparse
import json
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


class ContractError(ValueError):
    """A bounded validation error, safe to show in a terminal."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def validate_contract(document: Any) -> int:
    _require(isinstance(document, dict), "contract_not_object")
    _require(document.get("schema_version") == "sraf_airgap_off0_inventory_v1",
             "contract_schema_version_invalid")
    _require(document.get("scope") == "contract_only_not_executable",
             "contract_scope_invalid")
    _require(document.get("default_mode") == "quick", "contract_unsafe_default")
    _require(document.get("modes") == list(MODES), "contract_modes_invalid")
    _require(document.get("valid_states") == list(STATUSES),
             "contract_states_invalid")
    _require(set(document.get("effects", [])) == EFFECTS,
             "contract_effects_invalid")
    _require(set(document.get("report_required", [])) == REPORT_FIELDS,
             "contract_report_fields_invalid")
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
