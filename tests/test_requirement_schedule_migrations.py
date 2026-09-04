from requirement_scheduler.migrations import (
    REQUIRED_COLUMNS, REQUIRED_FILTERED_INDEXES, REQUIRED_FOREIGN_KEYS, REQUIRED_KEYS,
    bootstrap_schema_statements, migration_0_to_1_statements, validate_schema_name,
    required_foreign_keys, validate_catalog_evidence,
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


def test_custom_schemas_bind_all_internal_and_requirement_foreign_keys():
    fks = required_foreign_keys("custom_schedule", "custom_requirement")
    assert {fk.referenced_schema for fk in fks if fk.referenced_table.startswith("requirement_") and fk.referenced_table not in {"requirement_schedules", "requirement_schedule_versions", "requirement_batch_runs", "requirement_batch_run_items"}} == {"custom_requirement"}
    assert any(fk.referenced_schema == "custom_schedule" for fk in fks)
    ddl = "\n".join(migration_0_to_1_statements("custom_schedule", "custom_requirement"))
    assert "[custom_schedule].[requirement_batch_runs]" in ddl and "[custom_requirement].[requirement_versions]" in ddl


def test_exact_column_descriptors_reject_structural_drift():
    expected = REQUIRED_COLUMNS["requirement_schedule_versions"]
    rows = tuple((c.name, c.sql_type, c.max_length, c.nullable, c.ordinal) for c in expected)
    assert validate_catalog_evidence("sra_schedule", expected, rows)
    for index, field, replacement in ((0,1,"int"),(1,2,999),(2,3,not rows[2][3]),(3,4,99)):
        malformed=list(rows); changed=list(malformed[index]); changed[field]=replacement; malformed[index]=tuple(changed)
        assert not validate_catalog_evidence("sra_schedule", expected, tuple(malformed))
    assert not validate_catalog_evidence("sra_schedule", expected, rows[:-1])
    assert not validate_catalog_evidence("sra_schedule", expected, rows + (("extra","int",4,True,99),))


def test_filtered_indexes_require_exact_structure():
    expected=REQUIRED_FILTERED_INDEXES[0]
    rows=(("custom_schedule",expected.table,expected.name,True,True,"([trigger_type]='scheduled')","schedule_id",1),("custom_schedule",expected.table,expected.name,True,True,"([trigger_type]='scheduled')","scheduled_for",2))
    assert validate_catalog_evidence("custom_schedule",expected,rows)
    for position,value in ((0,"other"),(3,False),(5,"trigger_type='manual'"),(6,"trigger_request_id")):
        bad=[list(row) for row in rows]; bad[0][position]=value
        assert not validate_catalog_evidence("custom_schedule",expected,tuple(tuple(row) for row in bad))


def test_bootstrap_and_identifiers_are_fail_closed():
    assert "schema_version" in " ".join(bootstrap_schema_statements("sra_schedule"))
    with pytest.raises(ValueError): validate_schema_name("dbo]; DROP TABLE x--")
