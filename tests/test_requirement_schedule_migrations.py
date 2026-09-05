from requirement_scheduler.migrations import (
    SCHEMA_VERSION, REQUIRED_CHECKS, REQUIRED_COLUMNS, REQUIRED_DEFAULTS, REQUIRED_FILTERED_INDEXES, REQUIRED_FOREIGN_KEYS, REQUIRED_KEYS,
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
        def __init__(self, evidence): self.evidence = evidence; self.rows = ()
        def execute(self, sql, *params):
            assert params == ("sra_schedule",)
            if "SELECT t.name FROM" in sql:
                self.rows = tuple((name,) for name in sorted(self.evidence["columns"]))
            elif "SELECT t.name,c.name" in sql:
                self.rows = tuple((table,c.name,c.sql_type,c.max_length,c.nullable,c.ordinal)
                                  for table in sorted(self.evidence["columns"])
                                  for c in self.evidence["columns"][table])
            elif "sys.key_constraints" in sql:
                self.rows = tuple((k.table,k.name,k.kind,column,ordinal)
                                  for k in self.evidence["keys"]
                                  for ordinal,column in enumerate(k.columns,1))
            elif "sys.indexes" in sql:
                self.rows = tuple((i.table,i.name,i.is_unique,True,
                                   f" ( [ {i.filter_definition.replace('=', '] = [')} ] ) ",column,ordinal)
                                  for i in self.evidence["indexes"]
                                  for ordinal,column in enumerate(i.columns,1))
            else:
                self.rows = tuple((fk.table,fk.name,column,fk.referenced_schema,fk.referenced_table,referenced,ordinal,0,0)
                                  for fk in self.evidence["foreign_keys"]
                                  for ordinal,(column,referenced) in enumerate(zip(fk.columns,fk.referenced_columns),1))
            return self
        def fetchall(self): return self.rows
    common_keys = tuple(k for k in REQUIRED_KEYS if k.name not in {
        "UQ_requirement_schedule_version_owner", "PK_requirement_schedule_audit_outbox"})
    for shape, names in (("pr200_v1", migrations._PR200_FK_NAMES),
                         ("pr201_v1", migrations._PR201_FK_NAMES)):
        evidence = {"columns": migrations._v1_columns(shape), "keys": common_keys,
                    "indexes": REQUIRED_FILTERED_INDEXES[:2],
                    "foreign_keys": tuple(fk for fk in migrations.v1_foreign_keys("sra_schedule", "sra_requirement") if fk.name in names)}
        assert classify_v1_catalog(Cursor(evidence), "sra_schedule", "sra_requirement") == shape
        hybrid = dict(evidence, foreign_keys=evidence["foreign_keys"] + (migrations.ForeignKey("unexpected", "requirement_schedules", ("active_version_id",), "sra_schedule", "requirement_schedule_versions", ("schedule_version_id",)),))
        with pytest.raises(RuntimeError, match="unsupported_requirement_schedule_schema"):
            classify_v1_catalog(Cursor(hybrid), "sra_schedule", "sra_requirement")


def test_fk_actions_and_outbox_constraints_fail_closed():
    fk = REQUIRED_FOREIGN_KEYS[0]
    base = (("sra_schedule", fk.table, fk.name, fk.columns[0], fk.referenced_schema,
             fk.referenced_table, fk.referenced_columns[0], 1, 0, 0),)
    assert validate_catalog_evidence("sra_schedule", fk, base)
    for action_position in (8, 9):
        changed = [list(base[0])]
        changed[0][action_position] = 1
        assert not validate_catalog_evidence("sra_schedule", fk, tuple(map(tuple, changed)))

    default = REQUIRED_DEFAULTS[0]
    assert validate_catalog_evidence("sra_schedule", default, (("sra_schedule", default.table, default.name, default.column, "((0))"),))
    assert not validate_catalog_evidence("sra_schedule", default, (("sra_schedule", default.table, default.name, default.column, "(1)"),))
    check = REQUIRED_CHECKS[0]
    assert validate_catalog_evidence("sra_schedule", check, (("sra_schedule", check.table, check.name, "(([delivery_attempt_count] >= (0)))"),))
    assert not validate_catalog_evidence("sra_schedule", check, (("sra_schedule", check.table, check.name, "delivery_attempt_count>0"),))
