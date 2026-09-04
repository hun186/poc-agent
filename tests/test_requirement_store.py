import pytest
from data_ingestion.requirements.migrations import REQUIRED_COLUMNS, REQUIRED_CONSTRAINTS, migration_v1, validate_schema_name
from data_ingestion.requirements.models import AcquiredSource, NormalizedCandidate, RowDiagnostic
from data_ingestion.requirements.store import RequirementStore

def test_migration_v1_has_explicit_control_plane_tables_and_support_fields():
    sql="\n".join(migration_v1("sra_requirement"))
    for table in ("schema_version","requirement_sources","import_profiles","import_profile_versions","requirements","requirement_versions","requirement_sets","import_runs","import_run_rows","requirement_set_snapshots","requirement_snapshot_items"): assert f"[{table}]" in sql
    for field in ("active_version_id","source_payload_hash","source_mode","approved_by"): assert field in sql
    assert "auto_create" not in sql
def test_schema_identifier_rejected():
    with pytest.raises(ValueError): validate_schema_name("dbo]; DROP TABLE x--")

class RecordingCursor:
    description=[]
    def __init__(self, version=None, malformed=False): self.version=version; self.malformed=malformed; self.calls=[]; self.last=""
    def execute(self, sql, *params): self.last=sql; self.calls.append((sql,params)); return self
    def fetchone(self):
        if "SELECT version" in self.last: return None if self.version is None else (self.version,)
        if "COUNT(DISTINCT c.name)" in self.last:
            table=self.calls[-1][1][1]; count=len(REQUIRED_COLUMNS[table]); return (count-1 if self.malformed else count,)
        if "COUNT(DISTINCT o.name)" in self.last: return (len(REQUIRED_CONSTRAINTS),)
        return None
    def fetchall(self): return []
class RecordingConnection:
    def __init__(self, **kwargs): self.cursor_value=RecordingCursor(**kwargs); self.commits=0; self.rollbacks=0; self.closed=False
    def cursor(self): return self.cursor_value
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
    def close(self): self.closed=True
class Registry:
    def __init__(self,*connections): self.connections=list(connections)
    def open_named_connection(self,ref): return self.connections.pop(0)

@pytest.mark.parametrize("version", [None,0,1])
def test_schema_migration_and_validation_state_machine(version):
    connection=RecordingConnection(version=version); RequirementStore(Registry(connection),"control").initialize()
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed
    statements=[sql for sql,_ in connection.cursor_value.calls]
    assert any("sys.columns" in sql for sql in statements)
    assert any("INSERT INTO [sra_requirement].[schema_version]" in sql for sql in statements) == (version is None)
    assert any("UPDATE [sra_requirement].[schema_version]" in sql for sql in statements) == (version == 0)

@pytest.mark.parametrize("kwargs,error", [({"version":99},"unsupported requirement schema version"),({"version":1,"malformed":True},"malformed requirement schema version 1")])
def test_unknown_or_malformed_schema_rolls_back(kwargs,error):
    connection=RecordingConnection(**kwargs)
    with pytest.raises(RuntimeError,match=error): RequirementStore(Registry(connection),"control").initialize()
    assert connection.rollbacks == 1 and connection.commits == 0 and connection.closed

def test_failed_import_persists_each_row_diagnostic_in_one_transaction():
    connection=RecordingConnection(); store=RequirementStore(Registry(connection),"control")
    candidate=NormalizedCandidate(diagnostics=[RowDiagnostic(source_row_number=2,external_item_id="A1",code="bad_a",message="bad_a"),RowDiagnostic(source_row_number=2,external_item_id="A1",code="bad_b",message="bad_b")])
    result=store.record_failed_import({"source_id":"s"},{"profile_version_id":"pv"},AcquiredSource(rows=[{}],source_sha256="a"*64,source_uri_display="safe.csv",source_row_numbers=[2]),candidate,"operator")
    calls=connection.cursor_value.calls
    assert result["status"] == "failed" and sum("[import_run_rows]" in sql for sql,_ in calls) == 2
    run_params=next(params for sql,params in calls if "[import_runs]" in sql)
    assert run_params[5] == 1  # unique observed source rows, not diagnostic count
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed

def test_execute_driver_failure_is_stable_and_rolls_back():
    class BrokenCursor(RecordingCursor):
        def execute(self,sql,*params): raise RuntimeError("DRIVER secret connection string")
    connection=RecordingConnection(); connection.cursor_value=BrokenCursor()
    store=RequirementStore(Registry(connection),"control")
    with pytest.raises(RuntimeError,match="^persistence_error$") as caught: store._execute("UPDATE x")
    assert "secret" not in str(caught.value) and connection.rollbacks == 1 and connection.closed
