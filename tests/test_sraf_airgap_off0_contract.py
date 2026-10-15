"""OFF-0 contract checks: no network, SQL, workers, or external services."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.validate_sraf_airgap_off0_contract import (
    ContractError, make_report_record, validate_contract,
)


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

def test_worker_evidence_is_blocked_by_missing_provenance(inventory):
    work = next(item for item in inventory["checks"] if item["id"] == "WORK-01")
    assert "PKG-01" in work["depends_on"]
    assert "API-01" in work["depends_on"]


@pytest.mark.parametrize("field", ["effects", "report_required"])
@pytest.mark.parametrize("malformed", [{"unexpected": ["value"]}, [["unhashable"]]])
def test_unhashable_root_lists_are_stable_contract_errors(inventory, field, malformed):
    candidate = copy.deepcopy(inventory)
    candidate[field] = malformed
    with pytest.raises(ContractError, match="contract_"):
        validate_contract(candidate)


@pytest.mark.parametrize("field", ["minimum_mode", "effect", "readiness"])
def test_unhashable_check_fields_are_stable_errors(inventory, field):
    candidate = copy.deepcopy(inventory)
    candidate["checks"][0][field] = ["unexpected"]
    with pytest.raises(ContractError, match="contract_"):
        validate_contract(candidate)


def test_reject_report_policy_disabled_and_unknown_root_fields(inventory):
    unsafe = copy.deepcopy(inventory)
    unsafe["report_policy"]["allow_raw_exceptions"] = True
    with pytest.raises(ContractError, match="contract_report_policy_unsafe"):
        validate_contract(unsafe)
    another = copy.deepcopy(inventory)
    another["report_redaction"] = "disabled"
    with pytest.raises(ContractError, match="contract_top_level_shape_invalid"):
        validate_contract(another)


def test_report_records_use_allowlisted_static_strings_and_evidence(inventory):
    record = make_report_record(
        inventory, "API-01", "FAIL",
        evidence={"http_status": 503, "package_sha256": "a" * 64},
        error_code="api_unreachable", duration_ms=25,
    )
    assert record["status"] == "FAIL"
    assert record["error_code"] == "api_unreachable"
    assert record["summary"] == "SRA API Health"
    assert record["evidence"]["http_status"] == 503
    assert record["evidence"]["package_sha256"] == "a" * 64
    assert record["remediation"]
    assert set(record) == set(inventory["report_required"])


@pytest.mark.parametrize("evidence", [
    {"token": "secret"},
    {"connection_string": "Server=localhost;Password=1234"},
    {"package_sha256": "not-a-digest"},
    {"http_status": True},
    {"item_count": -1},
    {"classification": "RAW EXCEPTION: Bearer secret"},
    {"artifact_sha256": "/var/tmp/secret"},
])
def test_report_rejects_untrusted_evidence(inventory, evidence):
    with pytest.raises(ContractError, match="report_evidence_"):
        make_report_record(
            inventory, "API-01", "FAIL", evidence=evidence,
            error_code="api_unreachable",
        )


def test_report_rejects_unlisted_error_and_unimplemented_success(inventory):
    with pytest.raises(ContractError, match="report_error_code_unsafe"):
        make_report_record(
            inventory, "API-01", "FAIL",
            error_code="Password=supersecret",
        )
    with pytest.raises(ContractError, match="report_unimplemented_pass"):
        make_report_record(inventory, "SYS-01", "PASS")
    record = make_report_record(
        inventory, "API-01", "SKIP", error_code="blocked_by_dependency",
    )
    assert record["status"] == "SKIP"
    assert record["error_code"] == "blocked_by_dependency"


def test_report_rejects_raw_unbounded_evidence(inventory):
    with pytest.raises(ContractError, match="report_evidence_invalid"):
        make_report_record(
            inventory, "API-01", "FAIL",
            evidence={f"untrusted_{i}": "x" for i in range(13)},
            error_code="api_unreachable",
        )


@pytest.mark.parametrize(("field", "text_value"), [
    ("title", "x" * 97),
    ("title", "https://internal.example/secret"),
    ("title", "Error: something went wrong"),
    ("remediation", "x" * 201),
    ("remediation", "Bearer sensitive-token"),
    ("remediation", "Password=1234"),
    ("remediation", "/var/log/secret"),
    ("remediation", "Traceback (most recent call last)"),
    ("remediation", "value\nhidden"),
    ("remediation", r"C:\secret\password.txt"),
])
def test_report_text_fields_are_bounded_and_safe(inventory, field, text_value):
    changed = copy.deepcopy(inventory)
    changed["checks"][0][field] = text_value
    with pytest.raises(ContractError, match="contract_report_text_unsafe"):
        validate_contract(changed)
    with pytest.raises(ContractError, match="contract_report_text_unsafe"):
        make_report_record(
            changed, "PKG-01", "FAIL", error_code="package_missing",
        )


@pytest.mark.parametrize(("field", "text_value", "code"), [
    ("error_code", "Password=secret", "contract_report_error_code_unsafe"),
    ("error_code", "too_long_" + "x" * 80, "contract_report_error_code_unsafe"),
    ("component", r"C:\secret", "contract_report_component_unsafe"),
])
def test_structured_report_fields_reject_paths_and_secrets(
    inventory, field, text_value, code,
):
    changed = copy.deepcopy(inventory)
    changed["checks"][0][field] = text_value
    with pytest.raises(ContractError, match=code):
        validate_contract(changed)


def test_oversized_json_number_gives_bounded_cli_failure(tmp_path, inventory):
    raw = REGISTRY.read_text(encoding="utf-8")
    assert '"issue": 290' in raw
    fixture = tmp_path / "bad-integer.json"
    fixture.write_text(
        raw.replace('"issue": 290', '"issue": ' + "9" * 6000, 1),
        encoding="utf-8",
    )
    validator = Path(__file__).resolve().parents[1] / "tools/validate_sraf_airgap_off0_contract.py"
    output = subprocess.run(
        [sys.executable, str(validator), "--registry", str(fixture)],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert output.returncode == 2
    assert output.stdout.strip() == "OFF0_CONTRACT = FAIL (contract_json_invalid)"
    assert "Traceback" not in output.stderr


def test_valid_but_wrong_issue_has_contract_error_not_json_error(inventory):
    changed = copy.deepcopy(inventory)
    changed["issue"] = 123
    with pytest.raises(ContractError, match="contract_issue_invalid"):
        validate_contract(changed)


@pytest.mark.parametrize("payload", [
    "client_secret=hunter2",
    "access_token=hunter2",
    "/usr/local/private/config",
    "Hello\u2028credential",
    "Hello\u2029credential",
    "CREDENTIAL_KEY=topsecret",
])
def test_common_redaction_bypasses_are_rejected(inventory, payload):
    changed = copy.deepcopy(inventory)
    changed["checks"][0]["remediation"] = payload
    with pytest.raises(ContractError, match="contract_report_text_unsafe"):
        make_report_record(changed, "PKG-01", "FAIL", error_code="package_missing")


def test_innocuous_but_unapproved_registry_copy_is_rejected(inventory):
    changed = copy.deepcopy(inventory)
    changed["checks"][0]["title"] = "Unreviewed harmless looking text"
    with pytest.raises(ContractError, match="contract_report_text_unapproved"):
        make_report_record(changed, "PKG-01", "FAIL", error_code="package_missing")


def _run_cli_with_registry(path):
    validator = Path(__file__).resolve().parents[1] / "tools/validate_sraf_airgap_off0_contract.py"
    return subprocess.run(
        [sys.executable, str(validator), "--registry", str(path)],
        capture_output=True, text=True, check=False, timeout=10,
    )


def test_deeply_nested_json_is_bounded_error_not_traceback(tmp_path):
    input_path = tmp_path / "too-deep.json"
    input_path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    output = _run_cli_with_registry(input_path)
    assert output.returncode == 2
    assert output.stdout.strip() == "OFF0_CONTRACT = FAIL (contract_json_invalid)"
    assert "Traceback" not in output.stderr


def test_excessive_regular_registry_is_rejected_before_decode(tmp_path):
    input_path = tmp_path / "over-limit.json"
    input_path.write_bytes(b"x" * (256 * 1024 + 1))
    output = _run_cli_with_registry(input_path)
    assert output.returncode == 2
    assert output.stdout.strip() == "OFF0_CONTRACT = FAIL (contract_file_too_large)"
    assert "Traceback" not in output.stderr


@pytest.mark.skipif(not Path("/dev/zero").exists(), reason="Linux only")
def test_character_device_cannot_trigger_unbounded_registry_read():
    output = _run_cli_with_registry(Path("/dev/zero"))
    assert output.returncode == 2
    assert output.stdout.strip() == "OFF0_CONTRACT = FAIL (contract_file_not_regular)"
    assert "Traceback" not in output.stderr


def test_symlink_registry_is_rejected_without_following(tmp_path):
    input_path = tmp_path / "link.json"
    input_path.symlink_to(REGISTRY)
    output = _run_cli_with_registry(input_path)
    assert output.returncode == 2
    assert output.stdout.strip() == "OFF0_CONTRACT = FAIL (contract_file_unreadable)"
    assert "Traceback" not in output.stderr
