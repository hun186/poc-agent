from requirement_scheduler.migrations import (
    SCHEMA_VERSION, REQUIRED_COLUMNS, REQUIRED_FILTERED_INDEXES, REQUIRED_FOREIGN_KEYS, REQUIRED_KEYS,
    bootstrap_schema_statements, canonical_v2_statements, classify_v1_catalog,
    migration_0_to_1_statements, validate_schema_name,
    required_foreign_keys, validate_catalog_evidence,
)
import pytest


def test_schema_v2_contains_exact_history_evidence_and_identities():
    ddl = "\n".join(canonical_v2_statements("sra_schedule", "sra_requirement"))
    assert SCHEMA_VERSION == 2
    assert "requirement_version_number" in ddl
    assert "last_seen_requirement_version_number" in ddl
    assert "last_successful_requirement_version_number" in ddl
    assert "phase1a_output_root_fingerprint" in ddl
    assert "UX_schedule_run_manual" in ddl and "schedule_id,trigger_request_id" in ddl
    assert "UNIQUE(schedule_id,config_sha256)" not in ddl.replace(" ", "")
    assert set(REQUIRED_COLUMNS) == {"schema_version", "requirement_schedules", "requirement_schedule_versions", "requirement_batch_runs", "requirement_batch_run_items", "requirement_schedule_item_state", "requirement_schedule_audit_outbox"}
    assert next(c for c in REQUIRED_COLUMNS["requirement_batch_run_items"] if c.name == "phase1a_task_id").max_length == 480
    assert "UQ_requirement_schedule_version_owner" in ddl
    assert "FK_schedule_active_version_owner" in ddl and "FK_run_schedule_version_owner" in ddl
    assert "requirement_schedule_audit_outbox" in ddl
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


def test_v1_classifier_accepts_only_exact_whole_catalogs():
    import requirement_scheduler.migrations as migrations
    class Cursor:
        def __init__(self, evidence): self.evidence = evidence
        def requirement_schedule_catalog(self, *_): return self.evidence
    common_keys = tuple(k for k in REQUIRED_KEYS if k.name not in {
        "UQ_requirement_schedule_version_owner", "PK_requirement_schedule_audit_outbox"})
    for shape, names in (("pr200_v1", migrations._PR200_FK_NAMES),
                         ("pr201_v1", migrations._PR201_FK_NAMES)):
        evidence = {"columns": migrations._v1_columns(shape), "keys": common_keys,
                    "indexes": REQUIRED_FILTERED_INDEXES[:2], "foreign_key_names": names}
        assert classify_v1_catalog(Cursor(evidence), "sra_schedule", "sra_requirement") == shape
        hybrid = dict(evidence, foreign_key_names=names | {"unexpected"})
        with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
            classify_v1_catalog(Cursor(hybrid), "sra_schedule", "sra_requirement")
