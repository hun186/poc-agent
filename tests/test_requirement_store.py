import pytest
from data_ingestion.requirements.migrations import migration_v1, validate_schema_name

def test_migration_v1_has_explicit_control_plane_tables_and_support_fields():
    sql="\n".join(migration_v1("sra_requirement"))
    for table in ("schema_version","requirement_sources","import_profiles","import_profile_versions","requirements","requirement_versions","requirement_sets","import_runs","import_run_rows","requirement_set_snapshots","requirement_snapshot_items"): assert f"[{table}]" in sql
    for field in ("active_version_id","source_payload_hash","source_mode","approved_by"): assert field in sql
    assert "auto_create" not in sql
def test_schema_identifier_rejected():
    with pytest.raises(ValueError): validate_schema_name("dbo]; DROP TABLE x--")
