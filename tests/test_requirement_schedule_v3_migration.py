from requirement_scheduler.migrations import SCHEMA_VERSION, canonical_v3_statements, migration_2_to_3_statements

def test_v3_is_explicit_additive_schema_evolution():
    assert SCHEMA_VERSION==4
    sql="\n".join(migration_2_to_3_statements("sra_schedule"))
    assert "requirement_handoff_submissions" in sql
    assert "requirement_handoff_coordinator_leases" in sql
    assert "artifact_sha256" in sql
    assert all("DROP TABLE" not in statement.upper() for statement in migration_2_to_3_statements("sra_schedule"))

def test_fresh_v3_contains_v2_and_gate_b_objects():
    sql="\n".join(canonical_v3_statements("sra_schedule","sra_requirement"))
    for table in ("requirement_schedules","requirement_batch_runs","requirement_handoff_submissions","requirement_handoff_coordinator_leases"):
        assert table in sql
