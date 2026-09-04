from requirement_scheduler.migrations import (
    REQUIRED_COLUMNS, REQUIRED_FOREIGN_KEYS, REQUIRED_KEYS,
    bootstrap_schema_statements, migration_0_to_1_statements, validate_schema_name,
)
import pytest


def test_schema_v1_contains_exact_history_evidence_and_identities():
    ddl = "\n".join(migration_0_to_1_statements("sra_schedule", "sra_requirement"))
    assert "requirement_version_number" in ddl
    assert "last_seen_requirement_version_number" in ddl
    assert "last_successful_requirement_version_number" in ddl
    assert "phase1a_output_root_fingerprint" in ddl
    assert "UX_schedule_run_manual" in ddl and "schedule_id,trigger_request_id" in ddl
    assert "UNIQUE(schedule_id,config_sha256)" not in ddl.replace(" ", "")
    assert set(REQUIRED_COLUMNS) == {"schema_version", "requirement_schedules", "requirement_schedule_versions", "requirement_batch_runs", "requirement_batch_run_items", "requirement_schedule_item_state"}
    assert REQUIRED_KEYS and REQUIRED_FOREIGN_KEYS


def test_bootstrap_and_identifiers_are_fail_closed():
    assert "schema_version" in " ".join(bootstrap_schema_statements("sra_schedule"))
    with pytest.raises(ValueError): validate_schema_name("dbo]; DROP TABLE x--")
