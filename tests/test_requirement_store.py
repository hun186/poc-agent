import json

import pytest
from data_ingestion.requirements.hashing import canonical_sha256
from data_ingestion.requirements.migrations import (
    REQUIRED_COLUMNS,
    REQUIRED_FOREIGN_KEYS,
    REQUIRED_KEYS,
    migration_v1,
    validate_schema_name,
)
from data_ingestion.requirements.models import AcquiredSource, ImportProfileDocument, NormalizedCandidate, RowDiagnostic
from data_ingestion.requirements.profile import normalize_rows
from data_ingestion.requirements.store import RequirementStore
from tests.requirement_test_support import ScriptedConnection, ScriptedRegistry, sample_profile, sample_row

def test_migration_v1_has_explicit_control_plane_tables_and_support_fields():
    sql="\n".join(migration_v1("sra_requirement"))
    for table in ("schema_version","requirement_sources","import_profiles","import_profile_versions","requirements","requirement_versions","requirement_sets","import_runs","import_run_rows","requirement_set_snapshots","requirement_snapshot_items"): assert f"[{table}]" in sql
    for field in ("active_version_id","source_payload_hash","source_mode","approved_by"): assert field in sql
    for key in REQUIRED_KEYS: assert f"CONSTRAINT {key.name}" in sql
    assert "auto_create" not in sql
def test_schema_identifier_rejected():
    with pytest.raises(ValueError): validate_schema_name("dbo]; DROP TABLE x--")

class DbApiRow:
    """Minimal sequence row that deliberately has no tuple equality semantics."""

    def __init__(self, *values):
        self._values = values

    def __getitem__(self, index):
        return self._values[index]

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)


class RecordingCursor:
    description=[]
    def __init__(self, version=None, malformed=False, malformed_binding=None, diagnostic_nullable=True, diagnostic_row_factory=None, catalog_row_factory=None, repair_effective=True, legacy_generated_names=False, legacy_defect=None): self.version=version; self.malformed=malformed; self.malformed_binding=malformed_binding; self.diagnostic_nullable=diagnostic_nullable; self.diagnostic_row_factory=diagnostic_row_factory or (lambda value: (value,)); self.catalog_row_factory=catalog_row_factory or (lambda *values: tuple(values)); self.repair_effective=repair_effective; self.legacy_generated_names=legacy_generated_names; self.legacy_defect=legacy_defect; self.calls=[]; self.nullable_rows=[]; self.last=""
    def execute(self, sql, *params):
        self.last=sql; self.calls.append((sql,params))
        if "ALTER COLUMN source_row_number INT NULL" in sql and self.repair_effective: self.diagnostic_nullable=True
        return self
    def fetchone(self):
        if "SELECT version" in self.last: return None if self.version is None else (self.version,)
        if "COUNT(DISTINCT c.name)" in self.last:
            table=self.calls[-1][1][1]; count=len(REQUIRED_COLUMNS[table]); return (count-1 if self.malformed else count,)
        if "SELECT c.is_nullable" in self.last:
            row = self.diagnostic_row_factory(self.diagnostic_nullable)
            self.nullable_rows.append(row)
            return row
        return None
    def fetchall(self):
        params=self.calls[-1][1]
        if "sys.key_constraints" in self.last:
            if "t.name=? AND kc.type=?" in self.last:
                item=next(value for value in REQUIRED_KEYS if value.table == params[1] and value.kind == params[2] and value.legacy_generated_name)
                name = f"{item.kind}__{item.table}__6F4A3C2B" if self.legacy_generated_names else item.name
            else:
                item=next(value for value in REQUIRED_KEYS if value.name == params[1])
                name=item.name
            if self.legacy_defect and self.legacy_defect[1] == item.name and self.legacy_defect[0] in {"wrong_table", "wrong_kind", "missing"}:
                return []
            columns = item.columns
            if self.legacy_defect and self.legacy_defect == ("wrong_columns", item.name): columns=("wrong_column",)
            rows=[(params[0],item.table,name,item.kind,column,index) for index,column in enumerate(columns,1)]
            if self.legacy_defect and self.legacy_defect == ("duplicate", item.name):
                rows += [(params[0],item.table,f"{item.kind}__duplicate",item.kind,column,index) for index,column in enumerate(item.columns,1)]
        elif "sys.foreign_keys" in self.last:
            item=next(value for value in REQUIRED_FOREIGN_KEYS if value.name == params[1])
            rows=[(params[0],item.parent_table,item.name,parent,params[0],item.referenced_table,referenced,index) for index,(parent,referenced) in enumerate(zip(item.parent_columns,item.referenced_columns,strict=True),1)]
        else: return []
        malformed = self.malformed_binding
        lookup_name = item.name
        if malformed and (malformed == lookup_name or malformed[1] == lookup_name):
            mode = "column" if isinstance(malformed, str) else malformed[0]
            row = list(rows[0])
            positions = {
                "owner_table": 1, "parent_table": 1, "column": 4 if "sys.key_constraints" in self.last else 3,
                "referenced_table": 5, "referenced_column": 6,
            }
            row[positions[mode]] = "wrong_value"
            rows[0] = tuple(row)
        return [self.catalog_row_factory(*row) for row in rows]
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

def test_fresh_schema_accepts_canonical_catalog_evidence_as_dbapi_rows():
    connection=RecordingConnection(version=None,catalog_row_factory=DbApiRow)
    RequirementStore(Registry(connection),"control").initialize()
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed

@pytest.mark.parametrize("mode,constraint", [
    ("owner_table","UQ_requirement_identity"),
    ("referenced_table","FK_requirement_source"),
])
def test_dbapi_catalog_rows_with_wrong_named_constraint_structure_fail_closed(mode,constraint):
    connection=RecordingConnection(version=None,catalog_row_factory=DbApiRow,malformed_binding=(mode,constraint))
    with pytest.raises(RuntimeError,match="malformed requirement schema version 1"):
        RequirementStore(Registry(connection),"control").initialize()
    assert connection.commits == 0 and connection.rollbacks == 1 and connection.closed

@pytest.mark.parametrize("kwargs,error", [({"version":99},"unsupported requirement schema version"),({"version":1,"malformed":True},"malformed requirement schema version 1")])
def test_unknown_or_malformed_schema_rolls_back(kwargs,error):
    connection=RecordingConnection(**kwargs)
    with pytest.raises(RuntimeError,match=error): RequirementStore(Registry(connection),"control").initialize()
    assert connection.rollbacks == 1 and connection.commits == 0 and connection.closed

@pytest.mark.parametrize("constraint", [item.name for item in (*REQUIRED_KEYS, *REQUIRED_FOREIGN_KEYS)])
def test_schema_validation_rejects_wrong_constraint_binding(constraint):
    connection=RecordingConnection(version=1,malformed_binding=constraint)
    with pytest.raises(RuntimeError,match="malformed requirement schema version 1"):
        RequirementStore(Registry(connection),"control").initialize()
    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("schema_version] SET version" in sql for sql,_ in connection.cursor_value.calls)

@pytest.mark.parametrize("mode,constraint", [
    ("parent_table","FK_requirement_source"),
    ("column","FK_requirement_source"),
    ("referenced_table","FK_requirement_source"),
    ("referenced_column","FK_requirement_source"),
    ("owner_table","UQ_requirement_identity"),
    ("column","UQ_requirement_identity"),
])
def test_malformed_v1_named_constraint_on_wrong_structure_fails_closed(mode,constraint):
    connection=RecordingConnection(version=1,malformed_binding=(mode,constraint))
    with pytest.raises(RuntimeError,match="malformed requirement schema version 1"):
        RequirementStore(Registry(connection),"control").initialize()
    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("schema_version] SET version" in sql for sql,_ in connection.cursor_value.calls)

def test_v1_repairs_only_legacy_diagnostic_nullability_before_validation():
    connection=RecordingConnection(version=1,diagnostic_nullable=False)
    RequirementStore(Registry(connection),"control").initialize()
    statements=[sql for sql,_ in connection.cursor_value.calls]
    assert sum("ALTER COLUMN source_row_number INT NULL" in sql for sql in statements) == 1
    assert connection.commits == 1 and connection.rollbacks == 0

def test_actual_pr194_v1_schema_is_accepted_without_renaming_generated_keys():
    connection=RecordingConnection(version=1,diagnostic_nullable=False,diagnostic_row_factory=DbApiRow,legacy_generated_names=True)
    RequirementStore(Registry(connection),"control").initialize()
    statements=[sql for sql,_ in connection.cursor_value.calls]
    nullable_rows = connection.cursor_value.nullable_rows
    assert len(nullable_rows) == 2
    assert all(not isinstance(row, tuple) for row in nullable_rows)
    assert nullable_rows[0] != (False,) and nullable_rows[0][0] is False
    assert sum("ALTER COLUMN source_row_number INT NULL" in sql for sql in statements) == 1
    assert not any("schema_version] SET version" in sql or "schema_version](version) VALUES" in sql for sql in statements)
    assert not any("DROP CONSTRAINT" in sql or "ADD CONSTRAINT" in sql for sql in statements)
    assert sum("sys.key_constraints" in sql for sql in statements) == len(REQUIRED_KEYS)
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed

def test_pr194_v1_schema_fails_closed_when_dbapi_row_remains_not_nullable_after_repair():
    connection=RecordingConnection(
        version=1,
        diagnostic_nullable=False,
        diagnostic_row_factory=DbApiRow,
        repair_effective=False,
        legacy_generated_names=True,
    )
    with pytest.raises(RuntimeError,match="malformed requirement schema version 1"):
        RequirementStore(Registry(connection),"control").initialize()
    statements=[sql for sql,_ in connection.cursor_value.calls]
    assert sum("ALTER COLUMN source_row_number INT NULL" in sql for sql in statements) == 1
    assert not any("schema_version] SET version" in sql or "schema_version](version) VALUES" in sql for sql in statements)
    assert connection.commits == 0 and connection.rollbacks == 1 and connection.closed

@pytest.mark.parametrize("defect,constraint", [
    ("wrong_table", "PK_requirement_sources"),
    ("wrong_columns", "PK_requirement_sources"),
    ("wrong_columns", "UQ_requirement_set_source"),
    ("wrong_kind", "UQ_requirement_set_source"),
    ("duplicate", "UQ_requirement_set_source"),
    ("missing", "PK_import_runs"),
])
def test_malformed_pr194_generated_key_structure_fails_closed(defect,constraint):
    connection=RecordingConnection(version=1,legacy_generated_names=True,legacy_defect=(defect,constraint))
    with pytest.raises(RuntimeError,match="malformed requirement schema version 1"):
        RequirementStore(Registry(connection),"control").initialize()
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

def test_failed_import_persists_non_row_scoped_diagnostic_as_sql_null():
    connection=RecordingConnection(); store=RequirementStore(Registry(connection),"control")
    candidate=NormalizedCandidate(diagnostics=[RowDiagnostic(source_row_number=None,external_item_id=None,code="profile_invalid",message="invalid source timezone")])
    result=store.record_failed_import({"source_id":"s"},{"profile_version_id":"pv"},AcquiredSource(rows=[],source_sha256="a"*64,source_uri_display="safe.csv",source_row_numbers=[]),candidate,"operator")
    row_params=next(params for sql,params in connection.cursor_value.calls if "[import_run_rows]" in sql)
    assert row_params[1] is None and row_params[5] == "profile_invalid"
    assert result["status"] == "failed" and connection.commits == 1

def test_execute_driver_failure_is_stable_and_rolls_back():
    class BrokenCursor(RecordingCursor):
        def execute(self,sql,*params): raise RuntimeError("DRIVER secret connection string")
    connection=RecordingConnection(); connection.cursor_value=BrokenCursor()
    store=RequirementStore(Registry(connection),"control")
    with pytest.raises(RuntimeError,match="^persistence_error$") as caught: store._execute("UPDATE x")
    assert "secret" not in str(caught.value) and connection.rollbacks == 1 and connection.closed


def _candidate(*rows):
    from data_ingestion.requirements.models import ImportProfileDocument
    return normalize_rows(list(rows), ImportProfileDocument.model_validate(sample_profile()), list(range(2, 2 + len(rows))))


def _source(mode="authoritative_snapshot"):
    return {"source_id":"source-1","name":"Source","source_mode":mode,"enabled":True}


def _version(): return {"profile_version_id":"profile-version-7"}
def _acquired(): return AcquiredSource(rows=[],source_sha256="f"*64,source_uri_display="safe.json",source_row_numbers=[])


def test_actual_store_profile_source_and_immutable_version_sql(monkeypatch):
    connections=[ScriptedConnection(),ScriptedConnection(one=[(4,)]),ScriptedConnection(one=[("pv-4",)]),ScriptedConnection()]
    store=RequirementStore(ScriptedRegistry(*connections),"control")
    monkeypatch.setattr(store,"get_profile",lambda pid:{"profile_id":pid})
    monkeypatch.setattr(store,"get_profile_version",lambda vid:{"profile_version_id":vid,"status":"draft"})
    created=store.create_profile("name","description","operator",profile_id="profile-1")
    assert created["profile_id"] == "profile-1" and connections[0].commits == 1
    first=store.create_profile_version("profile-1",sample_profile(),"operator")
    assert first["status"] == "draft"
    version_calls=connections[1].cursor_value.calls
    assert version_calls[0][1] == ("profile-1",)
    assert version_calls[1][1][2] == 4 and version_calls[1][1][7] == "draft"
    assert not any(sql.lstrip().upper().startswith("UPDATE") for sql,_ in version_calls)
    approved=store.approve_profile_version("profile-1",4,"admin")
    approval_sql=[sql for sql,_ in connections[2].cursor_value.calls]
    assert approved["profile_version_id"] == "pv-4"
    assert "status='approved',approved_by=?,approved_at=?" in approval_sql[1]
    assert "active_version_id=?" in approval_sql[2]
    monkeypatch.setattr(store,"get_source",lambda sid:{"source_id":sid})
    store.create_source("source","sql_query","authoritative_snapshot",{"connection_ref":"reviewed","query_ref":"named"},"profile-1","admin",source_id="source-1")
    persisted=connections[3].cursor_value.calls[0][1][4]
    assert "reviewed" in persisted and "named" in persisted and "password" not in persisted.casefold() and "query" not in persisted.casefold().replace("query_ref","")


def test_create_profile_version_binds_all_insert_columns_in_order(monkeypatch):
    connection=ScriptedConnection(one=[(4,)])
    store=RequirementStore(ScriptedRegistry(connection),"control")
    monkeypatch.setattr(store,"get_profile_version",lambda vid:{"profile_version_id":vid})
    profile=ImportProfileDocument.model_validate(sample_profile())

    store.create_profile_version("profile-1",sample_profile(),"operator")

    insert_sql,params=next(call for call in connection.cursor_value.calls if call[0].lstrip().upper().startswith("INSERT"))
    assert "VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)" in insert_sql
    assert insert_sql.count("?") == len(params) == 10
    assert params[0].startswith("pv_")
    assert params[1:5] == ("profile-1",4,"json","authoritative_snapshot")
    assert json.loads(params[5]) == profile.model_dump(mode="json")
    assert params[6] == canonical_sha256(profile.model_dump(mode="json"))
    assert params[7:9] == ("draft","operator")
    assert params[9].tzinfo is not None
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed


def test_actual_store_commit_resolution_requires_enabled_approved_active_version(monkeypatch):
    store=RequirementStore(ScriptedRegistry(),"control")
    monkeypatch.setattr(store,"get_profile",lambda pid:{"enabled":True,"active_version_id":"approved-active"})
    monkeypatch.setattr(store,"get_profile_version",lambda vid:{"profile_version_id":vid,"status":"approved" if vid == "approved-active" else "draft"})
    assert store.get_active_profile_version("profile-1")["profile_version_id"] == "approved-active"
    assert store.get_profile_version("draft-explicit")["status"] == "draft"
    monkeypatch.setattr(store,"get_profile",lambda pid:{"enabled":True,"active_version_id":"draft-active"})
    with pytest.raises(ValueError,match="profile_invalid"):
        store.get_active_profile_version("profile-1")


def test_actual_store_commit_orders_snapshot_binding_and_active_switch_last():
    connection=ScriptedConnection(one=[("source-1",),None,None,None])
    store=RequirementStore(ScriptedRegistry(connection),"control")
    result=store.commit_candidate(_source(),_version(),_acquired(),_candidate(sample_row()),"operator")
    calls=connection.cursor_value.calls; sql=[item[0] for item in calls]
    snapshot_index=next(i for i,item in enumerate(sql) if "INSERT INTO [sra_requirement].[requirement_set_snapshots]" in item)
    item_index=next(i for i,item in enumerate(sql) if "INSERT INTO [sra_requirement].[requirement_snapshot_items]" in item)
    switch_index=next(i for i,item in enumerate(sql) if "SET active_snapshot_id" in item)
    snapshot_params=calls[snapshot_index][1]
    assert snapshot_params[3] == "f"*64 and snapshot_params[4] == "profile-version-7"
    assert snapshot_index < item_index < switch_index and connection.commits == 1 and result["status"] == "committed"


def test_actual_store_authoritative_omission_preserves_history_and_delta_carries_forward():
    authoritative=ScriptedConnection(one=[("source-1",),("set-1","old-snapshot"),("req-new",),None])
    RequirementStore(ScriptedRegistry(authoritative),"control").commit_candidate(_source(),_version(),_acquired(),_candidate(sample_row()),"operator")
    auth_sql=[sql for sql,_ in authoritative.cursor_value.calls]
    assert sum("requirement_snapshot_items] VALUES" in sql for sql in auth_sql) == 1
    assert not any("DELETE" in sql.upper() for sql in auth_sql)
    delta=ScriptedConnection(one=[("source-1",),("set-1","old-snapshot"),("req-new",),None],many=[[("req-old","rv-old",8)]])
    RequirementStore(ScriptedRegistry(delta),"control").commit_candidate(_source("upsert_delta"),_version(),_acquired(),_candidate(sample_row()),"operator")
    item_params=[params for sql,params in delta.cursor_value.calls if "requirement_snapshot_items] VALUES" in sql]
    assert len(item_params) == 2 and item_params[1][1:] == ("req-old","rv-old",8)


@pytest.mark.parametrize("old,expect_insert", [
    (("rv-old",3,__import__('datetime').datetime(2026,9,4,1,tzinfo=__import__('datetime').timezone.utc),None,None),True),
])
def test_actual_store_newer_timestamp_changed_payload_inserts_next_immutable_version(old,expect_insert):
    # Candidate timestamp is 01:00 UTC (09:00 Asia/Taipei); old is made earlier.
    old=list(old); old[2]=old[2].replace(day=3); old=tuple(old)
    connection=ScriptedConnection(one=[("source-1",),None,("req-1",),old])
    RequirementStore(ScriptedRegistry(connection),"control").commit_candidate(_source(),_version(),_acquired(),_candidate(sample_row()),"operator")
    inserts=[params for sql,params in connection.cursor_value.calls if "requirement_versions] VALUES" in sql]
    assert expect_insert and inserts[0][2] == 4


def test_actual_store_same_timestamp_and_payload_reuses_version():
    candidate=_candidate(sample_row()); row=candidate.rows[0]
    connection=ScriptedConnection(one=[("source-1",),None,("req-1",),("rv-existing",2,row.source_updated_at,row.source_payload_hash,row.source_row_hash)])
    RequirementStore(ScriptedRegistry(connection),"control").commit_candidate(_source(),_version(),_acquired(),candidate,"operator")
    assert not any("requirement_versions] VALUES" in sql for sql,_ in connection.cursor_value.calls)
    membership=next(params for sql,params in connection.cursor_value.calls if "requirement_snapshot_items] VALUES" in sql)
    assert membership[2] == "rv-existing"


@pytest.mark.parametrize("kind", ["stale", "anomaly"])
def test_actual_store_stale_and_anomaly_roll_back_then_record_failed_diagnostic(kind):
    candidate=_candidate(sample_row()); row=candidate.rows[0]
    timestamp=row.source_updated_at.replace(day=5) if kind == "stale" else row.source_updated_at
    payload="different" if kind == "anomaly" else row.source_payload_hash
    mutation=ScriptedConnection(one=[("source-1",),None,("req-1",),("rv-old",2,timestamp,payload,"hash")])
    diagnostic=ScriptedConnection()
    store=RequirementStore(ScriptedRegistry(mutation,diagnostic),"control")
    expected="stale_source_version" if kind == "stale" else "source_version_anomaly"
    with pytest.raises(ValueError,match=expected): store.commit_candidate(_source(),_version(),_acquired(),candidate,"operator")
    assert mutation.events[:2] == ["rollback","close"] and diagnostic.commits == 1
    params=next(params for sql,params in diagnostic.cursor_value.calls if "import_run_rows]" in sql)
    assert params[1] == 2 and params[5] == expected


@pytest.mark.parametrize("fail_on", ["requirement_set_snapshots] VALUES", "SET active_snapshot_id"])
def test_actual_store_forced_failure_rolls_back_without_authoritative_switch(fail_on):
    connection=ScriptedConnection(one=[("source-1",),None,None,None],fail_on=fail_on)
    store=RequirementStore(ScriptedRegistry(connection),"control")
    with pytest.raises(RuntimeError,match="^persistence_error$"):
        store.commit_candidate(_source(),_version(),_acquired(),_candidate(sample_row()),"operator")
    assert connection.rollbacks == 1 and connection.commits == 0 and connection.closed
    if fail_on.startswith("requirement_set_snapshots"):
        assert not any("SET active_snapshot_id" in sql for sql,_ in connection.cursor_value.calls)


def test_recover_preallocated_import_result_returns_original_terminal_identity():
    connection = ScriptedConnection(
        one=[("source-1", "committed", 0, 0)],
        many=[[("snap-fixed",)]],
    )
    store = RequirementStore(ScriptedRegistry(connection), "control")
    result = store.recover_preallocated_import_result(
        "source-1", "run-fixed", "snap-fixed"
    )
    assert result == {
        "import_run_id": "run-fixed",
        "snapshot_id": "snap-fixed",
        "status": "committed",
        "accepted_count": 0,
        "rejected_count": 0,
    }
    assert connection.closed
    assert not any("INSERT" in sql.upper() for sql, _ in connection.cursor_value.calls)


def test_commit_candidate_uses_preallocated_ids_and_base_snapshot_cas():
    connection = ScriptedConnection(
        one=[None, ("source-1",), ("set-1", "base-snap")]
    )
    store = RequirementStore(ScriptedRegistry(connection), "control")
    result = store.commit_candidate(
        _source(),
        _version(),
        _acquired(),
        _candidate(),
        "operator",
        import_run_id="run-fixed",
        snapshot_id="snap-fixed",
        expected_base_snapshot_id="base-snap",
    )
    assert result["import_run_id"] == "run-fixed"
    assert result["snapshot_id"] == "snap-fixed"
    run_insert = next(
        params for sql, params in connection.cursor_value.calls
        if "INSERT INTO [sra_requirement].[import_runs]" in sql
    )
    snapshot_insert = next(
        params for sql, params in connection.cursor_value.calls
        if "INSERT INTO [sra_requirement].[requirement_set_snapshots]" in sql
    )
    assert run_insert[0] == "run-fixed"
    assert snapshot_insert[0] == "snap-fixed"
    assert connection.commits == 1 and connection.rollbacks == 0


def test_commit_candidate_rejects_stale_base_snapshot_before_requirement_writes():
    connection = ScriptedConnection(
        one=[None, ("source-1",), ("set-1", "newer-snap")]
    )
    store = RequirementStore(ScriptedRegistry(connection), "control")
    with pytest.raises(ValueError, match="^requirement_input_conflict$"):
        store.commit_candidate(
            _source(),
            _version(),
            _acquired(),
            _candidate(),
            "operator",
            import_run_id="run-old",
            snapshot_id="snap-old",
            expected_base_snapshot_id="base-snap",
        )
    sql = [statement for statement, _ in connection.cursor_value.calls]
    assert not any("INSERT INTO [sra_requirement].[requirements]" in item for item in sql)
    assert not any("INSERT INTO [sra_requirement].[import_runs]" in item for item in sql)
    assert not any("INSERT INTO [sra_requirement].[requirement_set_snapshots]" in item for item in sql)
    assert connection.rollbacks == 1 and connection.commits == 0


def test_failed_import_preallocated_id_replay_does_not_duplicate_rows():
    candidate = NormalizedCandidate(
        diagnostics=[
            RowDiagnostic(
                source_row_number=2,
                external_item_id="A1",
                code="bad",
                message="bad",
            )
        ]
    )
    connection = ScriptedConnection(
        one=[("source-1", "failed", 0, 1)],
        many=[[]],
    )
    store = RequirementStore(ScriptedRegistry(connection), "control")
    result = store.record_failed_import(
        _source(),
        _version(),
        _acquired(),
        candidate,
        "operator",
        import_run_id="run-failed",
    )
    assert result["import_run_id"] == "run-failed"
    assert result["status"] == "failed"
    assert not any("INSERT" in sql.upper() for sql, _ in connection.cursor_value.calls)
    assert connection.commits == 1


def test_candidate_errors_still_enforce_replacement_base_cas_before_failed_import():
    candidate = NormalizedCandidate(
        diagnostics=[
            RowDiagnostic(
                source_row_number=2,
                external_item_id="A1",
                code="stale_source_version",
                message="Source timestamp is older",
            )
        ]
    )
    connection = ScriptedConnection(
        one=[None, ("source-1",), ("set-1", "newer-snap")]
    )
    store = RequirementStore(ScriptedRegistry(connection), "control")
    with pytest.raises(ValueError, match="^requirement_input_conflict$"):
        store.commit_candidate(
            _source(),
            _version(),
            _acquired(),
            candidate,
            "operator",
            import_run_id="run-old",
            snapshot_id="snap-old",
            expected_base_snapshot_id="base-snap",
        )
    sql = [statement for statement, _ in connection.cursor_value.calls]
    assert not any("INSERT INTO [sra_requirement].[import_runs]" in item for item in sql)
    assert not any("INSERT INTO [sra_requirement].[requirement_set_snapshots]" in item for item in sql)
    assert connection.rollbacks == 1 and connection.commits == 0



class SourceReplayCursor:
    def __init__(self, existing):
        self.existing = existing
        self.calls = []
        self.last = ""

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.last = sql
        return self

    def fetchone(self):
        if "FROM [sra_requirement].[requirement_sources] WITH (UPDLOCK,HOLDLOCK)" in self.last:
            return self.existing
        return None


class SourceReplayConnection:
    def __init__(self, existing):
        self.cursor_value = SourceReplayCursor(existing)
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


class SourceReplayRegistry:
    def __init__(self, connection):
        self.connection = connection

    def open_named_connection(self, ref):
        return self.connection


def test_create_source_same_supplied_identity_and_semantics_replays_without_insert(monkeypatch):
    config = {"display_name": "One Time", "format": "json"}
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = (
        "One Time",
        "manual_upload",
        "authoritative_snapshot",
        encoded,
        "prof-1",
        False,
    )
    connection = SourceReplayConnection(existing)
    store = RequirementStore(SourceReplayRegistry(connection), "control")
    monkeypatch.setattr(
        store,
        "get_source",
        lambda source_id: {
            "source_id": source_id,
            "name": "One Time",
            "source_type": "manual_upload",
            "source_mode": "authoritative_snapshot",
            "source_config": config,
            "import_profile_id": "prof-1",
            "enabled": False,
        },
    )

    result = store.create_source(
        "One Time",
        "manual_upload",
        "authoritative_snapshot",
        config,
        "prof-1",
        "admin",
        enabled=False,
        source_id="src-fixed",
    )

    assert result["source_id"] == "src-fixed"
    assert connection.commits == 1
    assert not any(
        sql.startswith("INSERT INTO") and "requirement_sources" in sql
        for sql, _ in connection.cursor_value.calls
    )


def test_create_source_same_supplied_identity_with_different_semantics_fails_closed():
    config = {"display_name": "One Time", "format": "json"}
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = (
        "Different",
        "manual_upload",
        "authoritative_snapshot",
        encoded,
        "prof-1",
        False,
    )
    connection = SourceReplayConnection(existing)
    store = RequirementStore(SourceReplayRegistry(connection), "control")

    with pytest.raises(RuntimeError, match="^persistence_error$"):
        store.create_source(
            "One Time",
            "manual_upload",
            "authoritative_snapshot",
            config,
            "prof-1",
            "admin",
            enabled=False,
            source_id="src-fixed",
        )

    assert connection.rollbacks == 1
    assert not any(
        sql.startswith("INSERT INTO") and "requirement_sources" in sql
        for sql, _ in connection.cursor_value.calls
    )



class ExpectedProfileCursor:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.row


def test_expected_profile_lock_binds_active_version_and_digest():
    store = RequirementStore(SourceReplayRegistry(SourceReplayConnection(None)), "control")
    cursor = ExpectedProfileCursor(
        (
            "prof-1",
            True,
            True,
            "pv-1",
            "prof-1",
            "a" * 64,
            "approved",
        )
    )

    store._lock_expected_profile_for_import(
        cursor,
        source={"source_id": "src-1"},
        version={
            "profile_id": "prof-1",
            "profile_version_id": "pv-1",
            "profile_sha256": "a" * 64,
        },
        expected_profile_version_id="pv-1",
        expected_profile_sha256="a" * 64,
    )

    sql, params = cursor.calls[0]
    assert "UPDLOCK,HOLDLOCK" in sql
    assert params == ("pv-1", "src-1")


def test_expected_profile_lock_rejects_active_version_switch():
    store = RequirementStore(SourceReplayRegistry(SourceReplayConnection(None)), "control")
    cursor = ExpectedProfileCursor(
        (
            "prof-1",
            True,
            True,
            "pv-new",
            "prof-1",
            "a" * 64,
            "approved",
        )
    )

    with pytest.raises(ValueError, match="profile_invalid"):
        store._lock_expected_profile_for_import(
            cursor,
            source={"source_id": "src-1"},
            version={
                "profile_id": "prof-1",
                "profile_version_id": "pv-1",
                "profile_sha256": "a" * 64,
            },
            expected_profile_version_id="pv-1",
            expected_profile_sha256="a" * 64,
        )

class ProductSourceFenceCursor:
    def __init__(self, *, task=False, reservation=False):
        self.task = task
        self.reservation = reservation
        self.calls = []
        self.last = ""

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        self.last = sql
        return self

    def fetchone(self):
        if "requirement_product_tasks" in self.last:
            return ("task-1",) if self.task else None
        if "requirement_product_requests" in self.last:
            return ("preq-1",) if self.reservation else None
        return None


@pytest.mark.parametrize(
    "task,reservation",
    [(True, False), (False, True)],
)
def test_requirement_source_guard_covers_task_and_provisioning_reservation(
    task, reservation
):
    store = RequirementStore(
        ScriptedRegistry(), "control", schedule_schema="sra_schedule"
    )
    cursor = ProductSourceFenceCursor(task=task, reservation=reservation)

    with pytest.raises(ValueError, match="requirement_product_owned_source"):
        store._guard_low_level_source_mutation_locked(cursor, "src-1")

    sql = [statement for statement, _ in cursor.calls]
    assert "[sra_schedule].[requirement_product_tasks]" in sql[0]
    assert "UPDLOCK,HOLDLOCK" in sql[0]
    if reservation:
        assert len(sql) == 2
        assert "operation='task_create'" in sql[1]
        assert "state IN" not in sql[1]


def test_guarded_patch_source_fences_before_requirement_update(monkeypatch):
    connection = ScriptedConnection()
    store = RequirementStore(
        ScriptedRegistry(connection), "control", schedule_schema="sra_schedule"
    )

    def deny(cursor, source_id):
        assert cursor is connection.cursor_value
        assert source_id == "source-1"
        raise ValueError("requirement_product_owned_source")

    monkeypatch.setattr(store, "_guard_low_level_source_mutation_locked", deny)

    with pytest.raises(ValueError, match="requirement_product_owned_source"):
        store.guarded_patch_source("source-1", "operator", name="blocked")

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert not any(
        sql.lstrip().upper().startswith("UPDATE")
        for sql, _ in connection.cursor_value.calls
    )


def test_guarded_import_fences_before_requirement_persistence(monkeypatch):
    connection = ScriptedConnection()
    store = RequirementStore(
        ScriptedRegistry(connection), "control", schedule_schema="sra_schedule"
    )

    def deny(cursor, source_id):
        assert cursor is connection.cursor_value
        assert source_id == "source-1"
        raise ValueError("requirement_product_owned_source")

    monkeypatch.setattr(store, "_guard_low_level_source_mutation_locked", deny)

    with pytest.raises(ValueError, match="requirement_product_owned_source"):
        store.guarded_commit_candidate(
            _source(),
            _version(),
            _acquired(),
            _candidate(sample_row()),
            "operator",
        )

    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql, _ in connection.cursor_value.calls
    )


def test_candidate_diagnostic_cas_and_failed_import_share_transaction():
    candidate = NormalizedCandidate(diagnostics=[
        RowDiagnostic(source_row_number=2, external_item_id="A1", code="bad", message="bad")
    ])
    connection = ScriptedConnection(one=[None, ("source-1",), ("set-1", "base-snap"), None])
    registry = ScriptedRegistry(connection)
    store = RequirementStore(registry, "control")
    result = store.commit_candidate(
        _source(), _version(), _acquired(), candidate, "operator",
        import_run_id="run-fixed", snapshot_id="snap-fixed",
        expected_base_snapshot_id="base-snap",
    )
    assert result["status"] == "failed"
    sql = [s for s, _ in connection.cursor_value.calls]
    base_check = next(i for i, s in enumerate(sql) if "requirement_sets]" in s)
    failed_insert = next(i for i, s in enumerate(sql) if "import_runs] VALUES" in s)
    diagnostic_insert = next(i for i, s in enumerate(sql) if "import_run_rows] VALUES" in s)
    assert base_check < failed_insert < diagnostic_insert
    assert "UPDLOCK,HOLDLOCK" in sql[base_check]
    assert registry.opened == [connection]
    assert connection.commits == 1 and connection.rollbacks == 0
    assert connection.events == ["commit", "close"]


def test_candidate_diagnostic_cas_rolls_back_failed_audit_write_together():
    candidate = NormalizedCandidate(diagnostics=[
        RowDiagnostic(source_row_number=2, external_item_id="A1", code="bad", message="bad")
    ])
    connection = ScriptedConnection(
        one=[None, ("source-1",), ("set-1", "base-snap"), None],
        fail_on="import_run_rows] VALUES",
    )
    registry = ScriptedRegistry(connection)
    store = RequirementStore(registry, "control")
    with pytest.raises(RuntimeError, match="^persistence_error$"):
        store.commit_candidate(
            _source(), _version(), _acquired(), candidate, "operator",
            import_run_id="run-fixed", snapshot_id="snap-fixed",
            expected_base_snapshot_id="base-snap",
        )
    assert registry.opened == [connection]
    assert connection.commits == 0 and connection.rollbacks == 1
    assert connection.events == ["rollback", "close"]
    assert not any("SET active_snapshot_id" in s for s, _ in connection.cursor_value.calls)


def test_candidate_diagnostic_stale_base_leaves_no_failed_audit_write():
    candidate = NormalizedCandidate(diagnostics=[
        RowDiagnostic(source_row_number=2, external_item_id="A1", code="bad", message="bad")
    ])
    connection = ScriptedConnection(
        one=[None, ("source-1",), ("set-1", "new-snapshot")]
    )
    registry = ScriptedRegistry(connection)
    store = RequirementStore(registry, "control")
    with pytest.raises(ValueError, match="^requirement_input_conflict$"):
        store.commit_candidate(
            _source(), _version(), _acquired(), candidate, "operator",
            import_run_id="run-fixed", snapshot_id="snap-fixed",
            expected_base_snapshot_id="base-snap",
        )
    assert registry.opened == [connection]
    assert connection.commits == 0 and connection.rollbacks == 1
    assert not any(
        "import_runs] VALUES" in s or "import_run_rows] VALUES" in s
        for s, _ in connection.cursor_value.calls
    )
