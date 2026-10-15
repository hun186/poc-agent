"""OFF-0 contract checks: no network, SQL, workers, or external services."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.validate_sraf_airgap_off0_contract import ContractError, validate_contract


REGISTRY = (
    Path(__file__).resolve().parents[1]
    / "docs/operations/sraf_airgap_off0_checks.v1.json"
)


@pytest.fixture
def inventory():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_inventory_is_structurally_valid_without_runtime_probe(inventory):
    assert validate_contract(inventory) == 19


def test_quick_must_remain_read_only(inventory):
    candidate = copy.deepcopy(inventory)
    candidate["checks"][0]["effect"] = "test_job_write"
    with pytest.raises(ContractError, match="contract_readonly_mode_violation"):
        validate_contract(candidate)


def test_diagnose_must_remain_read_only(inventory):
    candidate = copy.deepcopy(inventory)
    check = next(item for item in candidate["checks"] if item["id"] == "SQL-01")
    check["effect"] = "compute_only"
    with pytest.raises(ContractError, match="contract_readonly_mode_violation"):
        validate_contract(candidate)


def test_reject_unknown_dependency(inventory):
    candidate = copy.deepcopy(inventory)
    candidate["checks"][0]["depends_on"] = ["NOT-EXIST"]
    with pytest.raises(ContractError, match="contract_unknown_dependency"):
        validate_contract(candidate)


def test_reject_dependency_cycle(inventory):
    candidate = copy.deepcopy(inventory)
    first = next(item for item in candidate["checks"] if item["id"] == "PKG-01")
    second = next(item for item in candidate["checks"] if item["id"] == "API-01")
    first["depends_on"] = ["API-01"]
    second["depends_on"] = ["PKG-01"]
    with pytest.raises(ContractError, match="contract_dependency_cycle"):
        validate_contract(candidate)


def test_reject_quick_that_depends_on_acceptance(inventory):
    candidate = copy.deepcopy(inventory)
    first = next(item for item in candidate["checks"] if item["id"] == "API-01")
    first["depends_on"] = ["RUN-01"]
    with pytest.raises(ContractError, match="contract_dependency_mode_violation"):
        validate_contract(candidate)


def test_reject_duplicate_ids(inventory):
    candidate = copy.deepcopy(inventory)
    candidate["checks"].append(copy.deepcopy(candidate["checks"][0]))
    with pytest.raises(ContractError, match="contract_duplicate_check_id"):
        validate_contract(candidate)


def test_contract_cannot_claim_executable_scope(inventory):
    candidate = copy.deepcopy(inventory)
    candidate["scope"] = "runtime_pass"
    with pytest.raises(ContractError, match="contract_scope_invalid"):
        validate_contract(candidate)


def test_default_mode_must_be_quick(inventory):
    candidate = copy.deepcopy(inventory)
    candidate["default_mode"] = "acceptance"
    with pytest.raises(ContractError, match="contract_unsafe_default"):
        validate_contract(candidate)
