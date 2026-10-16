"""OFF-0 contract checks: no network, SQL, workers, or external services."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.validate_sraf_airgap_off0_contract import (
    ContractError, _json_exceeds_nesting_limit, make_report_record,
    validate_contract,
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


def test_report_records_use_allowlisted_static_strings_without_fake_evidence(inventory):
    record = make_report_record(
        inventory, "API-01", "SKIP",
        evidence={}, error_code="blocked_by_dependency", duration_ms=0,
    )
    assert record["status"] == "SKIP"
    assert record["error_code"] == "blocked_by_dependency"
    assert record["summary"] == "SRA API Health"
    assert record["evidence"] == {}
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



@pytest.mark.parametrize("removed_id", ["AIR-01", "DOC-01", "SQL-01"])
def test_incomplete_reviewed_inventory_must_fail(removed_id, inventory):
    changed = copy.deepcopy(inventory)
    changed["checks"] = [
        check for check in changed["checks"] if check["id"] != removed_id
    ]
    # Removing independent leaves and dependency targets both fail closed:
    # the incomplete inventory is invalid even if the graph is still connected.
    with pytest.raises(ContractError, match="contract_incomplete_check_inventory"):
        validate_contract(changed)


def test_incomplete_registry_cli_never_reports_pass(tmp_path, inventory):
    changed = copy.deepcopy(inventory)
    changed["checks"] = [
        check for check in changed["checks"] if check["id"] != "AIR-01"
    ]
    fixture = tmp_path / "missing-check.json"
    fixture.write_text(json.dumps(changed), encoding="utf-8")
    output = _run_cli_with_registry(fixture)
    assert output.returncode == 1
    assert output.stdout.strip() == (
        "OFF0_CONTRACT = FAIL (contract_incomplete_check_inventory)"
    )


@pytest.mark.parametrize(("status", "error_code"), [
    ("FAIL", "blocked_by_dependency"),
    ("FAIL", "check_not_implemented"),
    ("FAIL", "auth_session_unavailable"),
    ("SKIP", "api_unreachable"),
    ("SKIP", "product_api_invalid"),
    ("WARN", "blocked_by_dependency"),
])
def test_report_rejects_status_error_code_confusion(
    inventory, status, error_code,
):
    with pytest.raises(ContractError, match="report_error_code_unsafe"):
        make_report_record(
            inventory, "API-01", status, error_code=error_code,
        )


def test_report_valid_status_error_code_pairs(inventory):
    for status, code in [
        ("SKIP", "blocked_by_dependency"),
        ("SKIP", "auth_session_unavailable"),
        ("SKIP", "check_not_implemented"),
    ]:
        record = make_report_record(inventory, "API-01", status,
                                    error_code=code)
        assert record["status"] == status
        assert record["error_code"] == code


@pytest.mark.parametrize("depth", [129, 150, 2000])
def test_json_depth_rejection_independent_of_python_version(tmp_path, depth):
    raw = "[" * depth + "0" + "]" * depth
    assert _json_exceeds_nesting_limit(raw)
    fixture = tmp_path / "deep.json"
    fixture.write_text(raw, encoding="utf-8")
    output = _run_cli_with_registry(fixture)
    assert output.returncode == 2
    assert output.stdout.strip() == "OFF0_CONTRACT = FAIL (contract_json_invalid)"
    assert "Traceback" not in output.stderr


def test_depth_guard_ignores_brackets_and_escaped_quotes_inside_json_strings(
    tmp_path, inventory,
):
    changed = copy.deepcopy(inventory)
    changed["checks"][0]["existing_evidence"] = (
        'look at "[[[[' + "\\\"" + '[' * 130 + ']' * 130
    )
    raw = json.dumps(changed)
    assert not _json_exceeds_nesting_limit(raw)
    fixture = tmp_path / "brackets-in-string.json"
    fixture.write_text(raw, encoding="utf-8")
    output = _run_cli_with_registry(fixture)
    assert output.returncode == 0, output.stdout + output.stderr
    assert "checks=19" in output.stdout


@pytest.mark.parametrize(("status", "error_code"), [
    ("FAIL", "host_resource_insufficient"),
    ("WARN", "host_resource_insufficient"),
    ("WARN", None),
    ("PASS", None),
    ("SKIP", "blocked_by_dependency"),
    ("SKIP", "auth_session_unavailable"),
    ("SKIP", "mode_not_enabled"),
])
def test_unimplemented_checks_cannot_claim_execution(inventory, status, error_code):
    check = next(item for item in inventory["checks"] if item["id"] == "SYS-01")
    assert check["readiness"] == "planned"
    expected = ("report_unimplemented_pass" if status == "PASS"
                else "report_unimplemented_check")
    with pytest.raises(ContractError, match=expected):
        make_report_record(
            inventory, check["id"], status, error_code=error_code,
        )


def test_every_planned_check_has_only_explicit_unimplemented_skip(inventory):
    checks = [item for item in inventory["checks"] if item["readiness"] == "planned"]
    assert checks
    for check in checks:
        record = make_report_record(
            inventory, check["id"], "SKIP",
            error_code="check_not_implemented",
        )
        assert record["status"] == "SKIP"
        assert record["error_code"] == "check_not_implemented"
        assert record["remediation"] == check["remediation"]


def test_reusable_component_does_not_claim_unexecuted_fail(inventory):
    with pytest.raises(ContractError, match="report_outcome_probe_not_implemented"):
        make_report_record(
            inventory, "API-01", "FAIL", error_code="api_unreachable",
        )
    skipped = make_report_record(
        inventory, "API-01", "SKIP", error_code="blocked_by_dependency",
    )
    assert skipped["status"] == "SKIP"


@pytest.mark.parametrize("check_id,new_readiness", [
    ("SYS-01", "existing_component"),
    ("SYS-01", "existing_external_smoke"),
    ("ENV-01", "existing_component"),
    ("SQL-01", "existing_external_smoke"),
    ("API-01", "planned"),
    ("PREV-01", "existing_component"),
])
def test_readiness_cannot_be_promoted_or_relabelled_by_registry(
    inventory, check_id, new_readiness,
):
    changed = copy.deepcopy(inventory)
    entry = next(x for x in changed["checks"] if x["id"] == check_id)
    assert entry["readiness"] != new_readiness
    entry["readiness"] = new_readiness
    with pytest.raises(ContractError, match="contract_check_readiness_unapproved"):
        validate_contract(changed)


def test_fake_ready_planned_probe_cannot_report_pass(inventory):
    changed = copy.deepcopy(inventory)
    entry = next(x for x in changed["checks"] if x["id"] == "SYS-01")
    entry["readiness"] = "existing_component"
    with pytest.raises(ContractError, match="contract_check_readiness_unapproved"):
        make_report_record(changed, "SYS-01", "PASS")


def test_readiness_mutation_is_rejected_by_standalone_cli(tmp_path, inventory):
    changed = copy.deepcopy(inventory)
    entry = next(x for x in changed["checks"] if x["id"] == "SYS-01")
    entry["readiness"] = "existing_component"
    path = tmp_path / "fake-promoted.json"
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    out = _run_cli_with_registry(path)
    assert out.returncode == 1
    assert out.stdout.strip() == (
        "OFF0_CONTRACT = FAIL (contract_check_readiness_unapproved)"
    )
    assert "Traceback" not in out.stderr



@pytest.mark.parametrize(("check_id", "field", "value"), [
    ("RUN-01", "minimum_mode", "quick"),
    ("RUN-01", "effect", "read_only"),
    ("RUN-01", "depends_on", []),
    ("WORK-01", "depends_on", ["API-01"]),
    ("DOC-01", "depends_on", []),
    ("LLM-02", "minimum_mode", "diagnose"),
])
def test_reviewed_execution_gates_cannot_be_changed_from_json(
    inventory, check_id, field, value,
):
    changed = copy.deepcopy(inventory)
    check = next(x for x in changed["checks"] if x["id"] == check_id)
    assert check[field] != value
    check[field] = value
    # Moving a compute/write check into a read-only mode hits the intrinsic
    # side-effect fence before the reviewed semantic authority is consulted.
    # Both failures must remain fail-closed with a stable error category.
    expected = ("contract_readonly_mode_violation"
                if field == "minimum_mode"
                else "contract_check_execution_unapproved")
    with pytest.raises(ContractError, match=expected):
        validate_contract(changed)


def test_e2e_cannot_be_disguised_as_read_only_quick_check(inventory):
    changed = copy.deepcopy(inventory)
    check = next(x for x in changed["checks"] if x["id"] == "RUN-01")
    check["minimum_mode"] = "quick"
    check["effect"] = "read_only"
    check["depends_on"] = []
    with pytest.raises(ContractError, match="contract_check_execution_unapproved"):
        validate_contract(changed)
    with pytest.raises(ContractError, match="contract_check_execution_unapproved"):
        make_report_record(
            changed, "RUN-01", "SKIP", error_code="mode_not_enabled",
        )


def test_mutable_error_code_cannot_redirect_failure_attribution(inventory):
    changed = copy.deepcopy(inventory)
    api = next(x for x in changed["checks"] if x["id"] == "API-01")
    api["error_code"] = "mapping_incompatible"
    with pytest.raises(ContractError, match="contract_check_error_code_unapproved"):
        validate_contract(changed)
    with pytest.raises(ContractError, match="contract_check_error_code_unapproved"):
        make_report_record(
            changed, "API-01", "FAIL", error_code="mapping_incompatible",
        )


def test_mutable_component_cannot_redirect_failure_attribution(inventory):
    changed = copy.deepcopy(inventory)
    api = next(x for x in changed["checks"] if x["id"] == "API-01")
    api["component"] = "elasticsearch"
    with pytest.raises(ContractError, match="contract_check_component_unapproved"):
        validate_contract(changed)


def test_cli_rejects_quick_mode_e2e_promotion(tmp_path, inventory):
    changed = copy.deepcopy(inventory)
    check = next(x for x in changed["checks"] if x["id"] == "RUN-01")
    check["minimum_mode"] = "quick"
    check["effect"] = "read_only"
    check["depends_on"] = []
    fixture = tmp_path / "unsafe-promotion.json"
    fixture.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    result = _run_cli_with_registry(fixture)
    assert result.returncode == 1
    assert result.stdout.strip() == (
        "OFF0_CONTRACT = FAIL (contract_check_execution_unapproved)"
    )
    assert "Traceback" not in result.stderr


def test_cli_rejects_error_code_rebinding(tmp_path, inventory):
    changed = copy.deepcopy(inventory)
    check = next(x for x in changed["checks"] if x["id"] == "API-01")
    check["error_code"] = "mapping_incompatible"
    fixture = tmp_path / "wrong-code.json"
    fixture.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    result = _run_cli_with_registry(fixture)
    assert result.returncode == 1
    assert result.stdout.strip() == (
        "OFF0_CONTRACT = FAIL (contract_check_error_code_unapproved)"
    )



@pytest.mark.parametrize("check_id", ["API-01", "PKG-01", "ES-01", "WORK-01", "RUN-01", "DOC-01"])
@pytest.mark.parametrize("evidence", [
    None,
    {},
    {"http_status": 200},
    {"identity_verified": True},
    {"artifact_sha256": "a" * 64},
    {"classification": "FULL_LIVE"},
])
def test_contract_only_components_cannot_claim_pass_without_bound_probes(
    inventory, check_id, evidence,
):
    check = next(item for item in inventory["checks"] if item["id"] == check_id)
    assert check["readiness"] != "planned"
    with pytest.raises(ContractError, match="report_pass_probe_not_implemented"):
        make_report_record(inventory, check_id, "PASS", evidence=evidence)


def test_schema_pass_and_runtime_pass_are_independent(inventory):
    # A sound OFF-0 schema is not evidence that a live check was run.
    assert validate_contract(inventory) == 19
    with pytest.raises(ContractError, match="report_pass_probe_not_implemented"):
        make_report_record(inventory, "API-01", "PASS")


def test_off0_skip_is_not_an_execution_pass(inventory):
    record = make_report_record(
        inventory, "API-01", "SKIP", error_code="check_not_implemented",
    )
    assert record["status"] == "SKIP"
    assert record["evidence"] == {}



@pytest.mark.parametrize("check_id", [
    "PKG-01", "API-01", "ES-01", "ES-02", "LLM-02",
    "WORK-01", "PREV-01", "RUN-01", "DOC-01",
])
@pytest.mark.parametrize("status", ["FAIL", "WARN"])
@pytest.mark.parametrize("evidence", [
    None, {}, {"http_status": 503}, {"mapping_compatible": False},
    {"classification": "FULL_LIVE"},
])
def test_contract_only_components_cannot_claim_fail_or_warn(
    inventory, check_id, status, evidence,
):
    check = next(item for item in inventory["checks"] if item["id"] == check_id)
    assert check["readiness"] != "planned"
    with pytest.raises(ContractError, match="report_outcome_probe_not_implemented"):
        make_report_record(
            inventory, check_id, status, evidence=evidence,
            error_code=check["error_code"],
        )


def test_off0_schema_pass_cannot_produce_live_pass_fail_or_warn(inventory):
    assert validate_contract(inventory) == 19
    for status, code, expected in [
        ("PASS", None, "report_pass_probe_not_implemented"),
        ("FAIL", "api_unreachable", "report_outcome_probe_not_implemented"),
        ("WARN", None, "report_outcome_probe_not_implemented"),
    ]:
        with pytest.raises(ContractError, match=expected):
            make_report_record(inventory, "API-01", status, error_code=code)



@pytest.mark.parametrize(("check_id", "error_code"), [
    ("SYS-01", "check_not_implemented"),
    ("ENV-01", "check_not_implemented"),
    ("API-01", "blocked_by_dependency"),
    ("RUN-01", "mode_not_enabled"),
    ("WORK-01", "auth_session_unavailable"),
])
@pytest.mark.parametrize("evidence", [
    {"classification": "FULL_LIVE"},
    {"http_status": 200},
    {"identity_verified": True},
    {"mapping_compatible": False},
    {"package_sha256": "a" * 64},
    {"item_count": 0},
    {"artifact_sha256": "b" * 64, "classification": "OFFLINE"},
])
def test_off0_skip_rejects_even_allowlisted_fabricated_evidence(
    inventory, check_id, error_code, evidence,
):
    with pytest.raises(ContractError, match="report_skip_evidence_untrusted"):
        make_report_record(
            inventory, check_id, "SKIP", error_code=error_code,
            evidence=evidence,
        )


@pytest.mark.parametrize("evidence", [None, {}])
def test_off0_skip_accepts_only_empty_evidence(inventory, evidence):
    record = make_report_record(
        inventory, "API-01", "SKIP",
        error_code="blocked_by_dependency", evidence=evidence,
    )
    assert record["evidence"] == {}
    assert record["status"] == "SKIP"
