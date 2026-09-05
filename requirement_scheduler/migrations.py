from __future__ import annotations

from dataclasses import dataclass, replace
import re

SCHEMA_VERSION = 2


def validate_schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise ValueError("invalid_schedule_schema")
    return value


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    sql_type: str
    max_length: int
    nullable: bool
    ordinal: int


@dataclass(frozen=True)
class KeyConstraint:
    name: str; table: str; columns: tuple[str, ...]; kind: str


@dataclass(frozen=True)
class ForeignKey:
    name: str; table: str; columns: tuple[str, ...]; referenced_schema: str; referenced_table: str; referenced_columns: tuple[str, ...]; delete_action: int = 0; update_action: int = 0


@dataclass(frozen=True)
class FilteredIndex:
    name: str; table: str; columns: tuple[str, ...]; filter_definition: str; is_unique: bool


@dataclass(frozen=True)
class DefaultConstraint:
    name: str; table: str; column: str; definition: str


@dataclass(frozen=True)
class CheckConstraint:
    name: str; table: str; definition: str


def normalize_sql_predicate(value: object) -> str:
    """Canonicalize the narrow catalog expressions owned by this schema."""
    return re.sub(r"[\s\[\]\(\)]", "", str(value or "")).lower()


def _cols(table: str, specs: tuple[tuple[str, str, int, bool], ...]) -> tuple[Column, ...]:
    return tuple(Column(table, name, sql_type, length, nullable, ordinal) for ordinal, (name, sql_type, length, nullable) in enumerate(specs, 1))


# SQL Server sys.columns.max_length is bytes (NVARCHAR(n) therefore reports 2*n).
_N64=("nvarchar",128); _N128=("nvarchar",256); _N240=("nvarchar",480); _N500=("nvarchar",1000)
REQUIRED_COLUMNS = {
    "schema_version": _cols("schema_version", (("version","int",4,False),)),
    "requirement_schedules": _cols("requirement_schedules", (("schedule_id",*_N64,False),("name",*_N240,False),("requirement_set_id",*_N64,False),("enabled","bit",1,False),("active_version_id",*_N64,True),("next_run_at","datetimeoffset",10,True),("created_by",*_N128,False),("created_at","datetimeoffset",10,False),("updated_by",*_N128,False),("updated_at","datetimeoffset",10,False))),
    "requirement_schedule_versions": _cols("requirement_schedule_versions", (("schedule_version_id",*_N64,False),("schedule_id",*_N64,False),("version_number","int",4,False),("timezone",*_N128,False),("recurrence_json","nvarchar",-1,False),("run_policy","nvarchar",64,False),("model",*_N240,False),("config_sha256","char",64,False),("status","nvarchar",40,False),("created_by",*_N128,False),("created_at","datetimeoffset",10,False),("approved_by",*_N128,True),("approved_at","datetimeoffset",10,True),("retired_at","datetimeoffset",10,True))),
    "requirement_batch_runs": _cols("requirement_batch_runs", (("batch_run_id",*_N64,False),("schedule_id",*_N64,False),("schedule_version_id",*_N64,False),("trigger_type","nvarchar",32,False),("trigger_request_id",*_N128,True),("scheduled_for","datetimeoffset",10,True),("snapshot_id",*_N64,True),("run_policy","nvarchar",64,False),("phase1a_batch_id",*_N128,False),("phase1a_source_sha256","char",64,True),("phase1a_output_root_fingerprint","char",64,True),("state","nvarchar",64,False),("selected_count","int",4,False),("skipped_count","int",4,False),("success_count","int",4,False),("failure_count","int",4,False),("error_code",*_N64,True),("error_message",*_N500,True),("deadline_elapsed_during_execution","bit",1,False),("created_by",*_N128,False),("created_at","datetimeoffset",10,False),("materialized_at","datetimeoffset",10,True),("handoff_started_at","datetimeoffset",10,True),("handed_off_at","datetimeoffset",10,True),("reconciled_at","datetimeoffset",10,True),("completed_at","datetimeoffset",10,True),("updated_at","datetimeoffset",10,False))),
    "requirement_batch_run_items": _cols("requirement_batch_run_items", (("run_item_id",*_N64,False),("batch_run_id",*_N64,False),("requirement_id",*_N64,False),("requirement_version_id",*_N64,False),("requirement_version_number","int",4,False),("source_order","int",4,False),("selection_status","nvarchar",32,False),("selection_reason",*_N64,False),("phase1a_task_id",*_N240,True),("execution_state","nvarchar",64,False),("remote_job_id",*_N64,True),("remote_job_state","nvarchar",64,True),("artifact_relative_path",*_N500,True),("error_code",*_N64,True),("error_message",*_N500,True),("expired_at_selection","bit",1,False),("expired_before_handoff","bit",1,False),("deadline_elapsed_during_execution","bit",1,False),("created_at","datetimeoffset",10,False),("evaluated_at","datetimeoffset",10,False),("handoff_started_at","datetimeoffset",10,True),("dispatched_at","datetimeoffset",10,True),("remote_completed_at","datetimeoffset",10,True),("artifact_reconciled_at","datetimeoffset",10,True),("completed_at","datetimeoffset",10,True),("updated_at","datetimeoffset",10,False))),
    "requirement_schedule_item_state": _cols("requirement_schedule_item_state", (("schedule_id",*_N64,False),("requirement_id",*_N64,False),("last_seen_requirement_version_id",*_N64,True),("last_seen_requirement_version_number","int",4,True),("last_successful_requirement_version_id",*_N64,True),("last_successful_requirement_version_number","int",4,True),("last_successful_run_item_id",*_N64,True),("last_successful_at","datetimeoffset",10,True),("updated_at","datetimeoffset",10,False))),
    "requirement_schedule_audit_outbox": _cols("requirement_schedule_audit_outbox", (("audit_event_id",*_N64,False),("action","nvarchar",192,False),("actor",*_N128,False),("schedule_id",*_N64,False),("schedule_version_id",*_N64,True),("batch_run_id",*_N64,True),("safe_payload_json","nvarchar",4000,False),("created_at","datetimeoffset",10,False),("delivery_attempt_count","int",4,False),("last_delivery_attempt_at","datetimeoffset",10,True),("last_delivery_error_code",*_N64,True),("delivered_at","datetimeoffset",10,True))),
}

REQUIRED_KEYS = (
    KeyConstraint("PK_requirement_schedules","requirement_schedules",("schedule_id",),"PK"), KeyConstraint("PK_requirement_schedule_versions","requirement_schedule_versions",("schedule_version_id",),"PK"), KeyConstraint("UQ_requirement_schedule_version","requirement_schedule_versions",("schedule_id","version_number"),"UQ"), KeyConstraint("PK_requirement_batch_runs","requirement_batch_runs",("batch_run_id",),"PK"), KeyConstraint("PK_requirement_batch_run_items","requirement_batch_run_items",("run_item_id",),"PK"), KeyConstraint("UQ_requirement_batch_run_item","requirement_batch_run_items",("batch_run_id","requirement_id"),"UQ"), KeyConstraint("UQ_requirement_batch_run_order","requirement_batch_run_items",("batch_run_id","source_order"),"UQ"), KeyConstraint("PK_requirement_schedule_item_state","requirement_schedule_item_state",("schedule_id","requirement_id"),"PK"),
    KeyConstraint("UQ_requirement_schedule_version_owner","requirement_schedule_versions",("schedule_id","schedule_version_id"),"UQ"),
    KeyConstraint("PK_requirement_schedule_audit_outbox","requirement_schedule_audit_outbox",("audit_event_id",),"PK"),
)

REQUIRED_FILTERED_INDEXES = (
    FilteredIndex("UX_schedule_run_scheduled","requirement_batch_runs",("schedule_id","scheduled_for"),"trigger_type='scheduled'",True),
    FilteredIndex("UX_schedule_run_manual","requirement_batch_runs",("schedule_id","trigger_request_id"),"trigger_type='manual'",True),
    FilteredIndex("IX_requirement_schedule_audit_pending","requirement_schedule_audit_outbox",("delivered_at","created_at","audit_event_id"),"delivered_at IS NULL",False),
)

REQUIRED_DEFAULTS = (
    DefaultConstraint("DF_requirement_schedule_audit_attempts", "requirement_schedule_audit_outbox", "delivery_attempt_count", "0"),
)
REQUIRED_CHECKS = (
    CheckConstraint("CK_requirement_schedule_audit_attempts", "requirement_schedule_audit_outbox", "delivery_attempt_count>=0"),
)


def required_foreign_keys(schedule_schema: str = "sra_schedule", requirement_schema: str = "sra_requirement") -> tuple[ForeignKey, ...]:
    s, r = validate_schema_name(schedule_schema), validate_schema_name(requirement_schema)
    return (
        ForeignKey("FK_schedule_requirement_set","requirement_schedules",("requirement_set_id",),r,"requirement_sets",("requirement_set_id",)),
        ForeignKey("FK_schedule_active_version_owner","requirement_schedules",("schedule_id","active_version_id"),s,"requirement_schedule_versions",("schedule_id","schedule_version_id")),
        ForeignKey("FK_schedule_version_schedule","requirement_schedule_versions",("schedule_id",),s,"requirement_schedules",("schedule_id",)),
        ForeignKey("FK_run_schedule","requirement_batch_runs",("schedule_id",),s,"requirement_schedules",("schedule_id",)),
        ForeignKey("FK_run_schedule_version_owner","requirement_batch_runs",("schedule_id","schedule_version_id"),s,"requirement_schedule_versions",("schedule_id","schedule_version_id")),
        ForeignKey("FK_run_snapshot","requirement_batch_runs",("snapshot_id",),r,"requirement_set_snapshots",("snapshot_id",)),
        ForeignKey("FK_run_item_run","requirement_batch_run_items",("batch_run_id",),s,"requirement_batch_runs",("batch_run_id",)),
        ForeignKey("FK_run_item_version","requirement_batch_run_items",("requirement_version_id",),r,"requirement_versions",("requirement_version_id",)),
        ForeignKey("FK_state_schedule","requirement_schedule_item_state",("schedule_id",),s,"requirement_schedules",("schedule_id",)),
        ForeignKey("FK_state_seen_version","requirement_schedule_item_state",("last_seen_requirement_version_id",),r,"requirement_versions",("requirement_version_id",)),
        ForeignKey("FK_state_success_version","requirement_schedule_item_state",("last_successful_requirement_version_id",),r,"requirement_versions",("requirement_version_id",)),
        ForeignKey("FK_state_success_item","requirement_schedule_item_state",("last_successful_run_item_id",),s,"requirement_batch_run_items",("run_item_id",)),
        ForeignKey("FK_audit_outbox_schedule","requirement_schedule_audit_outbox",("schedule_id",),s,"requirement_schedules",("schedule_id",)),
    )

REQUIRED_FOREIGN_KEYS = required_foreign_keys()

_PR200_FK_NAMES = {
    "FK_schedule_requirement_set", "FK_schedule_version_schedule", "FK_run_snapshot",
    "FK_run_item_version", "FK_state_seen_version", "FK_state_success_version",
}
_PR201_FK_NAMES = {
    "FK_schedule_requirement_set", "FK_schedule_version_schedule", "FK_schedule_active_version",
    "FK_run_schedule", "FK_run_schedule_version", "FK_run_snapshot", "FK_run_item_run",
    "FK_run_item_version", "FK_state_schedule", "FK_state_seen_version",
    "FK_state_success_version", "FK_state_success_item",
}


def _v1_columns(shape: str) -> dict[str, tuple[Column, ...]]:
    columns = {name: tuple(values) for name, values in REQUIRED_COLUMNS.items()
               if name != "requirement_schedule_audit_outbox"}
    columns["requirement_batch_run_items"] = tuple(
        replace(column, max_length=256) if column.name == "phase1a_task_id" else column
        for column in columns["requirement_batch_run_items"]
    )
    return columns


def classify_v1_catalog(cursor, schedule_schema: str, requirement_schema: str) -> str:
    """Classify only either complete reviewed v1 catalog; arbitrary hybrids fail closed."""
    schedule_schema = validate_schema_name(schedule_schema)
    requirement_schema = validate_schema_name(requirement_schema)
    evidence = read_catalog(cursor, schedule_schema)
    matches = []
    for shape, fk_names in (("pr200_v1", _PR200_FK_NAMES), ("pr201_v1", _PR201_FK_NAMES)):
        if evidence.get("columns") != _v1_columns(shape):
            continue
        if set(evidence.get("keys", ())) != set(key for key in REQUIRED_KEYS if key.name not in {
            "UQ_requirement_schedule_version_owner", "PK_requirement_schedule_audit_outbox"}):
            continue
        if set(evidence.get("indexes", ())) != set(REQUIRED_FILTERED_INDEXES[:2]):
            continue
        expected_fks = tuple(fk for fk in v1_foreign_keys(schedule_schema, requirement_schema)
                             if fk.name in fk_names)
        if set(evidence.get("foreign_keys", ())) != set(expected_fks):
            continue
        matches.append(shape)
    if len(matches) != 1:
        raise RuntimeError("unsupported_requirement_schedule_schema")
    return matches[0]


def v1_foreign_keys(schedule_schema: str, requirement_schema: str) -> tuple[ForeignKey, ...]:
    """The exact PR #201 v1 relationships (PR #200 is the named subset)."""
    s, r = validate_schema_name(schedule_schema), validate_schema_name(requirement_schema)
    return (
        ForeignKey("FK_schedule_requirement_set", "requirement_schedules", ("requirement_set_id",), r, "requirement_sets", ("requirement_set_id",)),
        ForeignKey("FK_schedule_active_version", "requirement_schedules", ("active_version_id",), s, "requirement_schedule_versions", ("schedule_version_id",)),
        ForeignKey("FK_schedule_version_schedule", "requirement_schedule_versions", ("schedule_id",), s, "requirement_schedules", ("schedule_id",)),
        ForeignKey("FK_run_schedule", "requirement_batch_runs", ("schedule_id",), s, "requirement_schedules", ("schedule_id",)),
        ForeignKey("FK_run_schedule_version", "requirement_batch_runs", ("schedule_version_id",), s, "requirement_schedule_versions", ("schedule_version_id",)),
        ForeignKey("FK_run_snapshot", "requirement_batch_runs", ("snapshot_id",), r, "requirement_set_snapshots", ("snapshot_id",)),
        ForeignKey("FK_run_item_run", "requirement_batch_run_items", ("batch_run_id",), s, "requirement_batch_runs", ("batch_run_id",)),
        ForeignKey("FK_run_item_version", "requirement_batch_run_items", ("requirement_version_id",), r, "requirement_versions", ("requirement_version_id",)),
        ForeignKey("FK_state_schedule", "requirement_schedule_item_state", ("schedule_id",), s, "requirement_schedules", ("schedule_id",)),
        ForeignKey("FK_state_seen_version", "requirement_schedule_item_state", ("last_seen_requirement_version_id",), r, "requirement_versions", ("requirement_version_id",)),
        ForeignKey("FK_state_success_version", "requirement_schedule_item_state", ("last_successful_requirement_version_id",), r, "requirement_versions", ("requirement_version_id",)),
        ForeignKey("FK_state_success_item", "requirement_schedule_item_state", ("last_successful_run_item_id",), s, "requirement_batch_run_items", ("run_item_id",)),
    )


def read_catalog(cursor, schema: str) -> dict:
    """Read a complete SQL Server schema through ordinary parameterized DB-API calls."""
    queries = (
        "SELECT t.name FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=? ORDER BY t.name",
        "SELECT t.name,c.name,ty.name,c.max_length,c.is_nullable,c.column_id FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id WHERE s.name=? ORDER BY t.name,c.column_id",
        "SELECT t.name,kc.name,kc.type,c.name,ic.key_ordinal FROM sys.key_constraints kc JOIN sys.tables t ON t.object_id=kc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.index_columns ic ON ic.object_id=t.object_id AND ic.index_id=kc.unique_index_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=ic.column_id WHERE s.name=? ORDER BY t.name,kc.name,ic.key_ordinal",
        "SELECT t.name,i.name,i.is_unique,i.has_filter,i.filter_definition,c.name,ic.key_ordinal FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=ic.column_id WHERE s.name=? AND i.has_filter=1 AND ic.is_included_column=0 ORDER BY t.name,i.name,ic.key_ordinal",
        "SELECT pt.name,fk.name,pc.name,rs.name,rt.name,rc.name,fkc.constraint_column_id,fk.delete_referential_action,fk.update_referential_action FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id JOIN sys.tables pt ON pt.object_id=fk.parent_object_id JOIN sys.schemas ps ON ps.schema_id=pt.schema_id JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id JOIN sys.schemas rs ON rs.schema_id=rt.schema_id JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id WHERE ps.name=? ORDER BY pt.name,fk.name,fkc.constraint_column_id",
        "SELECT t.name,dc.name,c.name,dc.definition FROM sys.default_constraints dc JOIN sys.tables t ON t.object_id=dc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=dc.parent_column_id WHERE s.name=? ORDER BY t.name,dc.name",
        "SELECT t.name,cc.name,cc.definition FROM sys.check_constraints cc JOIN sys.tables t ON t.object_id=cc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=? ORDER BY t.name,cc.name",
    )
    result = []
    for sql in queries:
        cursor.execute(sql, schema)
        result.append(tuple(cursor.fetchall()))
    tables, column_rows, key_rows, index_rows, fk_rows, default_rows, check_rows = result
    columns = {}
    for table in (row[0] for row in tables):
        rows = [r for r in column_rows if r[0] == table]
        columns[table] = tuple(Column(table, r[1], str(r[2]).lower(), int(r[3]), bool(r[4]), int(r[5])) for r in rows)
    keys = []
    for table, name in dict.fromkeys((r[0], r[1]) for r in key_rows):
        rows = [r for r in key_rows if r[0] == table and r[1] == name]
        keys.append(KeyConstraint(name, table, tuple(r[3] for r in rows), rows[0][2]))
    indexes = []
    for table, name in dict.fromkeys((r[0], r[1]) for r in index_rows):
        rows = [r for r in index_rows if r[0] == table and r[1] == name]
        if not all(bool(r[3]) for r in rows):
            raise RuntimeError("unsupported_requirement_schedule_schema")
        indexes.append(FilteredIndex(name, table, tuple(r[5] for r in rows), normalize_sql_predicate(rows[0][4]), bool(rows[0][2])))
    fks = []
    for table, name in dict.fromkeys((r[0], r[1]) for r in fk_rows):
        rows = [r for r in fk_rows if r[0] == table and r[1] == name]
        if any(int(r[7]) != 0 or int(r[8]) != 0 for r in rows):
            raise RuntimeError("unsupported_requirement_schedule_schema")
        fks.append(ForeignKey(name, table, tuple(r[2] for r in rows), rows[0][3], rows[0][4], tuple(r[5] for r in rows)))
    defaults = tuple(DefaultConstraint(r[1], r[0], r[2], normalize_sql_predicate(r[3])) for r in default_rows)
    checks = tuple(CheckConstraint(r[1], r[0], normalize_sql_predicate(r[2])) for r in check_rows)
    return {"tables": tuple(r[0] for r in tables), "columns": columns,
            "keys": tuple(keys), "indexes": tuple(indexes), "foreign_keys": tuple(fks),
            "defaults": defaults, "checks": checks}


def canonical_catalog_matches(evidence: dict, schedule_schema: str,
                              requirement_schema: str) -> bool:
    return (
        evidence.get("columns") == REQUIRED_COLUMNS
        and set(evidence.get("keys", ())) == set(REQUIRED_KEYS)
        and set(evidence.get("indexes", ())) == set(
            replace(index, filter_definition=normalize_sql_predicate(index.filter_definition))
            for index in REQUIRED_FILTERED_INDEXES)
        and set(evidence.get("foreign_keys", ()))
        == set(required_foreign_keys(schedule_schema, requirement_schema))
        and set(evidence.get("defaults", ())) == set(REQUIRED_DEFAULTS)
        and set(evidence.get("checks", ())) == set(REQUIRED_CHECKS)
        and set(evidence.get("tables", ())) == set(REQUIRED_COLUMNS)
    )


def bootstrap_schema_statements(schema: str) -> list[str]:
    s=validate_schema_name(schema); return [f"IF SCHEMA_ID(N'{s}') IS NULL EXEC(N'CREATE SCHEMA [{s}]')",f"IF OBJECT_ID(N'[{s}].[schema_version]',N'U') IS NULL CREATE TABLE [{s}].[schema_version](version INT NOT NULL)"]


def migration_0_to_1_statements(schema: str, requirement_schema: str = "sra_requirement") -> list[str]:
    name, req=validate_schema_name(schema),validate_schema_name(requirement_schema); s,r=f"[{name}]",f"[{req}]"
    return [
        f"CREATE TABLE {s}.[requirement_schedules](schedule_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_schedules PRIMARY KEY,name NVARCHAR(240) NOT NULL,requirement_set_id NVARCHAR(64) NOT NULL,enabled BIT NOT NULL,active_version_id NVARCHAR(64) NULL,next_run_at DATETIMEOFFSET NULL,created_by NVARCHAR(128) NOT NULL,created_at DATETIMEOFFSET NOT NULL,updated_by NVARCHAR(128) NOT NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT FK_schedule_requirement_set FOREIGN KEY(requirement_set_id) REFERENCES {r}.[requirement_sets](requirement_set_id))",
        f"CREATE TABLE {s}.[requirement_schedule_versions](schedule_version_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_schedule_versions PRIMARY KEY,schedule_id NVARCHAR(64) NOT NULL,version_number INT NOT NULL,timezone NVARCHAR(128) NOT NULL,recurrence_json NVARCHAR(MAX) NOT NULL,run_policy NVARCHAR(32) NOT NULL,model NVARCHAR(240) NOT NULL,config_sha256 CHAR(64) NOT NULL,status NVARCHAR(20) NOT NULL,created_by NVARCHAR(128) NOT NULL,created_at DATETIMEOFFSET NOT NULL,approved_by NVARCHAR(128) NULL,approved_at DATETIMEOFFSET NULL,retired_at DATETIMEOFFSET NULL,CONSTRAINT UQ_requirement_schedule_version UNIQUE(schedule_id,version_number),CONSTRAINT FK_schedule_version_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id)); ALTER TABLE {s}.[requirement_schedules] ADD CONSTRAINT FK_schedule_active_version FOREIGN KEY(active_version_id) REFERENCES {s}.[requirement_schedule_versions](schedule_version_id)",
        f"CREATE TABLE {s}.[requirement_batch_runs](batch_run_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_batch_runs PRIMARY KEY,schedule_id NVARCHAR(64) NOT NULL,schedule_version_id NVARCHAR(64) NOT NULL,trigger_type NVARCHAR(16) NOT NULL,trigger_request_id NVARCHAR(128) NULL,scheduled_for DATETIMEOFFSET NULL,snapshot_id NVARCHAR(64) NULL,run_policy NVARCHAR(32) NOT NULL,phase1a_batch_id NVARCHAR(128) NOT NULL,phase1a_source_sha256 CHAR(64) NULL,phase1a_output_root_fingerprint CHAR(64) NULL,state NVARCHAR(32) NOT NULL,selected_count INT NOT NULL,skipped_count INT NOT NULL,success_count INT NOT NULL,failure_count INT NOT NULL,error_code NVARCHAR(64) NULL,error_message NVARCHAR(500) NULL,deadline_elapsed_during_execution BIT NOT NULL,created_by NVARCHAR(128) NOT NULL,created_at DATETIMEOFFSET NOT NULL,materialized_at DATETIMEOFFSET NULL,handoff_started_at DATETIMEOFFSET NULL,handed_off_at DATETIMEOFFSET NULL,reconciled_at DATETIMEOFFSET NULL,completed_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT FK_run_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id),CONSTRAINT FK_run_schedule_version FOREIGN KEY(schedule_version_id) REFERENCES {s}.[requirement_schedule_versions](schedule_version_id),CONSTRAINT FK_run_snapshot FOREIGN KEY(snapshot_id) REFERENCES {r}.[requirement_set_snapshots](snapshot_id)); CREATE UNIQUE INDEX UX_schedule_run_scheduled ON {s}.[requirement_batch_runs](schedule_id,scheduled_for) WHERE trigger_type='scheduled'; CREATE UNIQUE INDEX UX_schedule_run_manual ON {s}.[requirement_batch_runs](schedule_id,trigger_request_id) WHERE trigger_type='manual'",
        f"CREATE TABLE {s}.[requirement_batch_run_items](run_item_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_batch_run_items PRIMARY KEY,batch_run_id NVARCHAR(64) NOT NULL,requirement_id NVARCHAR(64) NOT NULL,requirement_version_id NVARCHAR(64) NOT NULL,requirement_version_number INT NOT NULL,source_order INT NOT NULL,selection_status NVARCHAR(16) NOT NULL,selection_reason NVARCHAR(64) NOT NULL,phase1a_task_id NVARCHAR(128) NULL,execution_state NVARCHAR(32) NOT NULL,remote_job_id NVARCHAR(64) NULL,remote_job_state NVARCHAR(32) NULL,artifact_relative_path NVARCHAR(500) NULL,error_code NVARCHAR(64) NULL,error_message NVARCHAR(500) NULL,expired_at_selection BIT NOT NULL,expired_before_handoff BIT NOT NULL,deadline_elapsed_during_execution BIT NOT NULL,created_at DATETIMEOFFSET NOT NULL,evaluated_at DATETIMEOFFSET NOT NULL,handoff_started_at DATETIMEOFFSET NULL,dispatched_at DATETIMEOFFSET NULL,remote_completed_at DATETIMEOFFSET NULL,artifact_reconciled_at DATETIMEOFFSET NULL,completed_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT UQ_requirement_batch_run_item UNIQUE(batch_run_id,requirement_id),CONSTRAINT UQ_requirement_batch_run_order UNIQUE(batch_run_id,source_order),CONSTRAINT FK_run_item_run FOREIGN KEY(batch_run_id) REFERENCES {s}.[requirement_batch_runs](batch_run_id),CONSTRAINT FK_run_item_version FOREIGN KEY(requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id))",
        f"CREATE TABLE {s}.[requirement_schedule_item_state](schedule_id NVARCHAR(64) NOT NULL,requirement_id NVARCHAR(64) NOT NULL,last_seen_requirement_version_id NVARCHAR(64) NULL,last_seen_requirement_version_number INT NULL,last_successful_requirement_version_id NVARCHAR(64) NULL,last_successful_requirement_version_number INT NULL,last_successful_run_item_id NVARCHAR(64) NULL,last_successful_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT PK_requirement_schedule_item_state PRIMARY KEY(schedule_id,requirement_id),CONSTRAINT FK_state_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id),CONSTRAINT FK_state_seen_version FOREIGN KEY(last_seen_requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id),CONSTRAINT FK_state_success_version FOREIGN KEY(last_successful_requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id),CONSTRAINT FK_state_success_item FOREIGN KEY(last_successful_run_item_id) REFERENCES {s}.[requirement_batch_run_items](run_item_id))",
    ]


def canonical_v2_statements(schema: str, requirement_schema: str = "sra_requirement") -> list[str]:
    """Explicit canonical-v2 DDL; intentionally independent of legacy migration assembly."""
    name = validate_schema_name(schema)
    req = validate_schema_name(requirement_schema)
    values = ['CREATE TABLE {s}.[requirement_schedules](schedule_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_schedules '
 'PRIMARY KEY,name NVARCHAR(240) NOT NULL,requirement_set_id NVARCHAR(64) NOT NULL,enabled BIT NOT '
 'NULL,active_version_id NVARCHAR(64) NULL,next_run_at DATETIMEOFFSET NULL,created_by NVARCHAR(128) NOT '
 'NULL,created_at DATETIMEOFFSET NOT NULL,updated_by NVARCHAR(128) NOT NULL,updated_at DATETIMEOFFSET NOT '
 'NULL,CONSTRAINT FK_schedule_requirement_set FOREIGN KEY(requirement_set_id) REFERENCES '
 '{r}.[requirement_sets](requirement_set_id))',
 'CREATE TABLE {s}.[requirement_schedule_versions](schedule_version_id NVARCHAR(64) NOT NULL CONSTRAINT '
 'PK_requirement_schedule_versions PRIMARY KEY,schedule_id NVARCHAR(64) NOT NULL,version_number INT NOT NULL,timezone '
 'NVARCHAR(128) NOT NULL,recurrence_json NVARCHAR(MAX) NOT NULL,run_policy NVARCHAR(32) NOT NULL,model NVARCHAR(240) '
 'NOT NULL,config_sha256 CHAR(64) NOT NULL,status NVARCHAR(20) NOT NULL,created_by NVARCHAR(128) NOT NULL,created_at '
 'DATETIMEOFFSET NOT NULL,approved_by NVARCHAR(128) NULL,approved_at DATETIMEOFFSET NULL,retired_at DATETIMEOFFSET '
 'NULL,CONSTRAINT UQ_requirement_schedule_version UNIQUE(schedule_id,version_number),CONSTRAINT '
 'FK_schedule_version_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id))',
 'CREATE TABLE {s}.[requirement_batch_runs](batch_run_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_batch_runs '
 'PRIMARY KEY,schedule_id NVARCHAR(64) NOT NULL,schedule_version_id NVARCHAR(64) NOT NULL,trigger_type NVARCHAR(16) '
 'NOT NULL,trigger_request_id NVARCHAR(128) NULL,scheduled_for DATETIMEOFFSET NULL,snapshot_id NVARCHAR(64) '
 'NULL,run_policy NVARCHAR(32) NOT NULL,phase1a_batch_id NVARCHAR(128) NOT NULL,phase1a_source_sha256 CHAR(64) '
 'NULL,phase1a_output_root_fingerprint CHAR(64) NULL,state NVARCHAR(32) NOT NULL,selected_count INT NOT '
 'NULL,skipped_count INT NOT NULL,success_count INT NOT NULL,failure_count INT NOT NULL,error_code NVARCHAR(64) '
 'NULL,error_message NVARCHAR(500) NULL,deadline_elapsed_during_execution BIT NOT NULL,created_by NVARCHAR(128) NOT '
 'NULL,created_at DATETIMEOFFSET NOT NULL,materialized_at DATETIMEOFFSET NULL,handoff_started_at DATETIMEOFFSET '
 'NULL,handed_off_at DATETIMEOFFSET NULL,reconciled_at DATETIMEOFFSET NULL,completed_at DATETIMEOFFSET NULL,updated_at '
 'DATETIMEOFFSET NOT NULL,CONSTRAINT FK_run_schedule FOREIGN KEY(schedule_id) REFERENCES '
 '{s}.[requirement_schedules](schedule_id),CONSTRAINT FK_run_snapshot FOREIGN KEY(snapshot_id) REFERENCES '
 '{r}.[requirement_set_snapshots](snapshot_id)); CREATE UNIQUE INDEX UX_schedule_run_scheduled ON '
 "{s}.[requirement_batch_runs](schedule_id,scheduled_for) WHERE trigger_type='scheduled'; CREATE UNIQUE INDEX "
 "UX_schedule_run_manual ON {s}.[requirement_batch_runs](schedule_id,trigger_request_id) WHERE trigger_type='manual'",
 'CREATE TABLE {s}.[requirement_batch_run_items](run_item_id NVARCHAR(64) NOT NULL CONSTRAINT '
 'PK_requirement_batch_run_items PRIMARY KEY,batch_run_id NVARCHAR(64) NOT NULL,requirement_id NVARCHAR(64) NOT '
 'NULL,requirement_version_id NVARCHAR(64) NOT NULL,requirement_version_number INT NOT NULL,source_order INT NOT '
 'NULL,selection_status NVARCHAR(16) NOT NULL,selection_reason NVARCHAR(64) NOT NULL,phase1a_task_id NVARCHAR(240) '
 'NULL,execution_state NVARCHAR(32) NOT NULL,remote_job_id NVARCHAR(64) NULL,remote_job_state NVARCHAR(32) '
 'NULL,artifact_relative_path NVARCHAR(500) NULL,error_code NVARCHAR(64) NULL,error_message NVARCHAR(500) '
 'NULL,expired_at_selection BIT NOT NULL,expired_before_handoff BIT NOT NULL,deadline_elapsed_during_execution BIT NOT '
 'NULL,created_at DATETIMEOFFSET NOT NULL,evaluated_at DATETIMEOFFSET NOT NULL,handoff_started_at DATETIMEOFFSET '
 'NULL,dispatched_at DATETIMEOFFSET NULL,remote_completed_at DATETIMEOFFSET NULL,artifact_reconciled_at DATETIMEOFFSET '
 'NULL,completed_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT UQ_requirement_batch_run_item '
 'UNIQUE(batch_run_id,requirement_id),CONSTRAINT UQ_requirement_batch_run_order '
 'UNIQUE(batch_run_id,source_order),CONSTRAINT FK_run_item_run FOREIGN KEY(batch_run_id) REFERENCES '
 '{s}.[requirement_batch_runs](batch_run_id),CONSTRAINT FK_run_item_version FOREIGN KEY(requirement_version_id) '
 'REFERENCES {r}.[requirement_versions](requirement_version_id))',
 'CREATE TABLE {s}.[requirement_schedule_item_state](schedule_id NVARCHAR(64) NOT NULL,requirement_id NVARCHAR(64) NOT '
 'NULL,last_seen_requirement_version_id NVARCHAR(64) NULL,last_seen_requirement_version_number INT '
 'NULL,last_successful_requirement_version_id NVARCHAR(64) NULL,last_successful_requirement_version_number INT '
 'NULL,last_successful_run_item_id NVARCHAR(64) NULL,last_successful_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET '
 'NOT NULL,CONSTRAINT PK_requirement_schedule_item_state PRIMARY KEY(schedule_id,requirement_id),CONSTRAINT '
 'FK_state_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id),CONSTRAINT '
 'FK_state_seen_version FOREIGN KEY(last_seen_requirement_version_id) REFERENCES '
 '{r}.[requirement_versions](requirement_version_id),CONSTRAINT FK_state_success_version FOREIGN '
 'KEY(last_successful_requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id),CONSTRAINT '
 'FK_state_success_item FOREIGN KEY(last_successful_run_item_id) REFERENCES '
 '{s}.[requirement_batch_run_items](run_item_id))',
 'ALTER TABLE {s}.[requirement_schedule_versions] ADD CONSTRAINT UQ_requirement_schedule_version_owner '
 'UNIQUE(schedule_id,schedule_version_id)',
 'ALTER TABLE {s}.[requirement_schedules] ADD CONSTRAINT FK_schedule_active_version_owner FOREIGN '
 'KEY(schedule_id,active_version_id) REFERENCES {s}.[requirement_schedule_versions](schedule_id,schedule_version_id)',
 'ALTER TABLE {s}.[requirement_batch_runs] ADD CONSTRAINT FK_run_schedule_version_owner FOREIGN '
 'KEY(schedule_id,schedule_version_id) REFERENCES {s}.[requirement_schedule_versions](schedule_id,schedule_version_id)',
 'CREATE TABLE {s}.[requirement_schedule_audit_outbox](audit_event_id NVARCHAR(64) NOT NULL CONSTRAINT '
 'PK_requirement_schedule_audit_outbox PRIMARY KEY,action NVARCHAR(96) NOT NULL,actor NVARCHAR(128) NOT '
 'NULL,schedule_id NVARCHAR(64) NOT NULL,schedule_version_id NVARCHAR(64) NULL,batch_run_id NVARCHAR(64) '
 'NULL,safe_payload_json NVARCHAR(2000) NOT NULL,created_at DATETIMEOFFSET NOT NULL,delivery_attempt_count INT NOT '
 'NULL CONSTRAINT DF_requirement_schedule_audit_attempts DEFAULT 0 CONSTRAINT CK_requirement_schedule_audit_attempts '
 'CHECK(delivery_attempt_count>=0),last_delivery_attempt_at DATETIMEOFFSET NULL,last_delivery_error_code NVARCHAR(64) '
 'NULL,delivered_at DATETIMEOFFSET NULL,CONSTRAINT FK_audit_outbox_schedule FOREIGN KEY(schedule_id) REFERENCES '
 '{s}.[requirement_schedules](schedule_id))',
 'CREATE INDEX IX_requirement_schedule_audit_pending ON '
 '{s}.[requirement_schedule_audit_outbox](delivered_at,created_at,audit_event_id) WHERE delivered_at IS NULL']
    return [statement.format(s=f"[{name}]", r=f"[{req}]") for statement in values]

def migration_1_to_2_statements(schema: str, v1_shape: str) -> list[str]:
    """Ordered v2 DDL. Identity repair/validation is performed before these statements."""
    if v1_shape not in {"pr200_v1", "pr201_v1"}:
        raise ValueError("unsupported_requirement_schedule_schema")
    s = f"[{validate_schema_name(schema)}]"
    statements = [
        f"ALTER TABLE {s}.[requirement_batch_run_items] ALTER COLUMN phase1a_task_id NVARCHAR(240) NULL",
        f"ALTER TABLE {s}.[requirement_schedule_versions] ADD CONSTRAINT UQ_requirement_schedule_version_owner UNIQUE(schedule_id,schedule_version_id)",
    ]
    if v1_shape == "pr200_v1":
        statements.extend((
            f"ALTER TABLE {s}.[requirement_batch_runs] ADD CONSTRAINT FK_run_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id)",
            f"ALTER TABLE {s}.[requirement_batch_run_items] ADD CONSTRAINT FK_run_item_run FOREIGN KEY(batch_run_id) REFERENCES {s}.[requirement_batch_runs](batch_run_id)",
            f"ALTER TABLE {s}.[requirement_schedule_item_state] ADD CONSTRAINT FK_state_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id)",
            f"ALTER TABLE {s}.[requirement_schedule_item_state] ADD CONSTRAINT FK_state_success_item FOREIGN KEY(last_successful_run_item_id) REFERENCES {s}.[requirement_batch_run_items](run_item_id)",
        ))
    else:
        statements.extend((
            f"ALTER TABLE {s}.[requirement_schedules] DROP CONSTRAINT FK_schedule_active_version",
            f"ALTER TABLE {s}.[requirement_batch_runs] DROP CONSTRAINT FK_run_schedule_version",
        ))
    statements.extend((
        f"ALTER TABLE {s}.[requirement_schedules] ADD CONSTRAINT FK_schedule_active_version_owner FOREIGN KEY(schedule_id,active_version_id) REFERENCES {s}.[requirement_schedule_versions](schedule_id,schedule_version_id)",
        f"ALTER TABLE {s}.[requirement_batch_runs] ADD CONSTRAINT FK_run_schedule_version_owner FOREIGN KEY(schedule_id,schedule_version_id) REFERENCES {s}.[requirement_schedule_versions](schedule_id,schedule_version_id)",
    ))
    statements.extend(canonical_v2_statements(schema)[-2:])
    return statements


def validation_queries(schema: str, requirement_schema: str = "sra_requirement"):
    validate_schema_name(schema); validate_schema_name(requirement_schema); checks=[]
    for table, columns in REQUIRED_COLUMNS.items():
        checks.append((f"columns:{table}","SELECT c.name,ty.name,c.max_length,c.is_nullable,c.column_id FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id WHERE s.name=? AND t.name=? ORDER BY c.column_id",(schema,table),columns))
    for key in REQUIRED_KEYS:
        checks.append((f"key:{key.name}","SELECT s.name,t.name,kc.name,kc.type,c.name,ic.key_ordinal FROM sys.key_constraints kc JOIN sys.tables t ON t.object_id=kc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.index_columns ic ON ic.object_id=t.object_id AND ic.index_id=kc.unique_index_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=ic.column_id WHERE s.name=? AND kc.name=? ORDER BY ic.key_ordinal",(schema,key.name),key))
    for index in REQUIRED_FILTERED_INDEXES:
        checks.append((f"index:{index.name}","SELECT s.name,t.name,i.name,i.is_unique,i.has_filter,i.filter_definition,c.name,ic.key_ordinal FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=i.object_id AND c.column_id=ic.column_id WHERE s.name=? AND i.name=? AND ic.is_included_column=0 ORDER BY ic.key_ordinal",(schema,index.name),index))
    for fk in required_foreign_keys(schema,requirement_schema):
        checks.append((f"fk:{fk.name}","SELECT ps.name,pt.name,fk.name,pc.name,rs.name,rt.name,rc.name,fkc.constraint_column_id,fk.delete_referential_action,fk.update_referential_action FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id JOIN sys.tables pt ON pt.object_id=fk.parent_object_id JOIN sys.schemas ps ON ps.schema_id=pt.schema_id JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id JOIN sys.schemas rs ON rs.schema_id=rt.schema_id JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id WHERE ps.name=? AND fk.name=? ORDER BY fkc.constraint_column_id",(schema,fk.name),fk))
    for default in REQUIRED_DEFAULTS:
        checks.append((f"default:{default.name}", "SELECT s.name,t.name,dc.name,c.name,dc.definition FROM sys.default_constraints dc JOIN sys.tables t ON t.object_id=dc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=dc.parent_column_id WHERE s.name=? AND dc.name=?", (schema, default.name), default))
    for check in REQUIRED_CHECKS:
        checks.append((f"check:{check.name}", "SELECT s.name,t.name,cc.name,cc.definition FROM sys.check_constraints cc JOIN sys.tables t ON t.object_id=cc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=? AND cc.name=?", (schema, check.name), check))
    return checks


def validate_catalog_evidence(schema: str, expected, rows: tuple) -> bool:
    """Compare one catalog query result with the complete canonical descriptor."""
    if isinstance(expected, KeyConstraint):
        actual=tuple((r[4],int(r[5])) for r in rows)
        return bool(rows) and all(r[0]==schema and r[1]==expected.table and r[2]==expected.name and r[3]==expected.kind for r in rows) and actual==tuple((c,i) for i,c in enumerate(expected.columns,1))
    if isinstance(expected, ForeignKey):
        actual=tuple((r[3],r[4],r[5],r[6],int(r[7])) for r in rows)
        wanted=tuple((c,expected.referenced_schema,expected.referenced_table,rc,i) for i,(c,rc) in enumerate(zip(expected.columns,expected.referenced_columns),1))
        return actual==wanted and bool(rows) and all(r[0]==schema and r[1]==expected.table and r[2]==expected.name and int(r[8]) == expected.delete_action and int(r[9]) == expected.update_action for r in rows)
    if isinstance(expected, FilteredIndex):
        actual=tuple((r[6],int(r[7])) for r in rows)
        return bool(rows) and all(r[0]==schema and r[1]==expected.table and r[2]==expected.name and bool(r[3]) == expected.is_unique and bool(r[4]) and normalize_sql_predicate(r[5])==normalize_sql_predicate(expected.filter_definition) for r in rows) and actual==tuple((c,i) for i,c in enumerate(expected.columns,1))
    if isinstance(expected, DefaultConstraint):
        return len(rows) == 1 and rows[0][:4] == (schema, expected.table, expected.name, expected.column) and normalize_sql_predicate(rows[0][4]) == normalize_sql_predicate(expected.definition)
    if isinstance(expected, CheckConstraint):
        return len(rows) == 1 and rows[0][:3] == (schema, expected.table, expected.name) and normalize_sql_predicate(rows[0][3]) == normalize_sql_predicate(expected.definition)
    actual=tuple(Column(expected[0].table,str(r[0]).lower(),str(r[1]).lower(),int(r[2]),bool(r[3]),int(r[4])) for r in rows)
    return actual==tuple(expected)
