from __future__ import annotations

from dataclasses import dataclass
import re

SCHEMA_VERSION = 1


def validate_schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise ValueError("invalid_schedule_schema")
    return value


@dataclass(frozen=True)
class KeyConstraint:
    name: str; table: str; columns: tuple[str, ...]; kind: str


@dataclass(frozen=True)
class ForeignKey:
    name: str; table: str; columns: tuple[str, ...]; referenced_schema: str; referenced_table: str; referenced_columns: tuple[str, ...]


REQUIRED_COLUMNS = {
    "schema_version": ("version",),
    "requirement_schedules": ("schedule_id", "name", "requirement_set_id", "enabled", "active_version_id", "next_run_at", "created_by", "created_at", "updated_by", "updated_at"),
    "requirement_schedule_versions": ("schedule_version_id", "schedule_id", "version_number", "timezone", "recurrence_json", "run_policy", "model", "config_sha256", "status", "created_by", "created_at", "approved_by", "approved_at", "retired_at"),
    "requirement_batch_runs": ("batch_run_id", "schedule_id", "schedule_version_id", "trigger_type", "trigger_request_id", "scheduled_for", "snapshot_id", "run_policy", "phase1a_batch_id", "phase1a_source_sha256", "phase1a_output_root_fingerprint", "state", "selected_count", "skipped_count", "success_count", "failure_count", "error_code", "error_message", "deadline_elapsed_during_execution", "created_by", "created_at", "materialized_at", "handoff_started_at", "handed_off_at", "reconciled_at", "completed_at", "updated_at"),
    "requirement_batch_run_items": ("run_item_id", "batch_run_id", "requirement_id", "requirement_version_id", "requirement_version_number", "source_order", "selection_status", "selection_reason", "phase1a_task_id", "execution_state", "remote_job_id", "remote_job_state", "artifact_relative_path", "error_code", "error_message", "expired_at_selection", "expired_before_handoff", "deadline_elapsed_during_execution", "created_at", "evaluated_at", "handoff_started_at", "dispatched_at", "remote_completed_at", "artifact_reconciled_at", "completed_at", "updated_at"),
    "requirement_schedule_item_state": ("schedule_id", "requirement_id", "last_seen_requirement_version_id", "last_seen_requirement_version_number", "last_successful_requirement_version_id", "last_successful_requirement_version_number", "last_successful_run_item_id", "last_successful_at", "updated_at"),
}

REQUIRED_KEYS = (
    KeyConstraint("PK_requirement_schedules", "requirement_schedules", ("schedule_id",), "PK"),
    KeyConstraint("PK_requirement_schedule_versions", "requirement_schedule_versions", ("schedule_version_id",), "PK"),
    KeyConstraint("UQ_requirement_schedule_version", "requirement_schedule_versions", ("schedule_id", "version_number"), "UQ"),
    KeyConstraint("PK_requirement_batch_runs", "requirement_batch_runs", ("batch_run_id",), "PK"),
    KeyConstraint("PK_requirement_batch_run_items", "requirement_batch_run_items", ("run_item_id",), "PK"),
    KeyConstraint("UQ_requirement_batch_run_item", "requirement_batch_run_items", ("batch_run_id", "requirement_id"), "UQ"),
    KeyConstraint("UQ_requirement_batch_run_order", "requirement_batch_run_items", ("batch_run_id", "source_order"), "UQ"),
    KeyConstraint("PK_requirement_schedule_item_state", "requirement_schedule_item_state", ("schedule_id", "requirement_id"), "PK"),
)


def required_foreign_keys(requirement_schema: str) -> tuple[ForeignKey, ...]:
    r = validate_schema_name(requirement_schema)
    return (
        ForeignKey("FK_schedule_requirement_set", "requirement_schedules", ("requirement_set_id",), r, "requirement_sets", ("requirement_set_id",)),
        ForeignKey("FK_schedule_version_schedule", "requirement_schedule_versions", ("schedule_id",), "sra_schedule", "requirement_schedules", ("schedule_id",)),
        ForeignKey("FK_run_snapshot", "requirement_batch_runs", ("snapshot_id",), r, "requirement_set_snapshots", ("snapshot_id",)),
        ForeignKey("FK_run_item_version", "requirement_batch_run_items", ("requirement_version_id",), r, "requirement_versions", ("requirement_version_id",)),
        ForeignKey("FK_state_seen_version", "requirement_schedule_item_state", ("last_seen_requirement_version_id",), r, "requirement_versions", ("requirement_version_id",)),
        ForeignKey("FK_state_success_version", "requirement_schedule_item_state", ("last_successful_requirement_version_id",), r, "requirement_versions", ("requirement_version_id",)),
    )

REQUIRED_FOREIGN_KEYS = required_foreign_keys("sra_requirement")


def bootstrap_schema_statements(schema: str) -> list[str]:
    s = validate_schema_name(schema)
    return [f"IF SCHEMA_ID(N'{s}') IS NULL EXEC(N'CREATE SCHEMA [{s}]')", f"IF OBJECT_ID(N'[{s}].[schema_version]',N'U') IS NULL CREATE TABLE [{s}].[schema_version](version INT NOT NULL)"]


def migration_0_to_1_statements(schema: str, requirement_schema: str = "sra_requirement") -> list[str]:
    name, req = validate_schema_name(schema), validate_schema_name(requirement_schema); s, r = f"[{name}]", f"[{req}]"
    return [
        f"CREATE TABLE {s}.[requirement_schedules](schedule_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_schedules PRIMARY KEY,name NVARCHAR(240) NOT NULL,requirement_set_id NVARCHAR(64) NOT NULL,enabled BIT NOT NULL,active_version_id NVARCHAR(64) NULL,next_run_at DATETIMEOFFSET NULL,created_by NVARCHAR(128) NOT NULL,created_at DATETIMEOFFSET NOT NULL,updated_by NVARCHAR(128) NOT NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT FK_schedule_requirement_set FOREIGN KEY(requirement_set_id) REFERENCES {r}.[requirement_sets](requirement_set_id))",
        f"CREATE TABLE {s}.[requirement_schedule_versions](schedule_version_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_schedule_versions PRIMARY KEY,schedule_id NVARCHAR(64) NOT NULL,version_number INT NOT NULL,timezone NVARCHAR(128) NOT NULL,recurrence_json NVARCHAR(MAX) NOT NULL,run_policy NVARCHAR(32) NOT NULL,model NVARCHAR(240) NOT NULL,config_sha256 CHAR(64) NOT NULL,status NVARCHAR(20) NOT NULL,created_by NVARCHAR(128) NOT NULL,created_at DATETIMEOFFSET NOT NULL,approved_by NVARCHAR(128) NULL,approved_at DATETIMEOFFSET NULL,retired_at DATETIMEOFFSET NULL,CONSTRAINT UQ_requirement_schedule_version UNIQUE(schedule_id,version_number),CONSTRAINT FK_schedule_version_schedule FOREIGN KEY(schedule_id) REFERENCES {s}.[requirement_schedules](schedule_id))",
        f"CREATE TABLE {s}.[requirement_batch_runs](batch_run_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_batch_runs PRIMARY KEY,schedule_id NVARCHAR(64) NOT NULL,schedule_version_id NVARCHAR(64) NOT NULL,trigger_type NVARCHAR(16) NOT NULL,trigger_request_id NVARCHAR(128) NULL,scheduled_for DATETIMEOFFSET NULL,snapshot_id NVARCHAR(64) NULL,run_policy NVARCHAR(32) NOT NULL,phase1a_batch_id NVARCHAR(128) NOT NULL,phase1a_source_sha256 CHAR(64) NULL,phase1a_output_root_fingerprint CHAR(64) NULL,state NVARCHAR(32) NOT NULL,selected_count INT NOT NULL,skipped_count INT NOT NULL,success_count INT NOT NULL,failure_count INT NOT NULL,error_code NVARCHAR(64) NULL,error_message NVARCHAR(500) NULL,deadline_elapsed_during_execution BIT NOT NULL,created_by NVARCHAR(128) NOT NULL,created_at DATETIMEOFFSET NOT NULL,materialized_at DATETIMEOFFSET NULL,handoff_started_at DATETIMEOFFSET NULL,handed_off_at DATETIMEOFFSET NULL,reconciled_at DATETIMEOFFSET NULL,completed_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT FK_run_snapshot FOREIGN KEY(snapshot_id) REFERENCES {r}.[requirement_set_snapshots](snapshot_id)); CREATE UNIQUE INDEX UX_schedule_run_scheduled ON {s}.[requirement_batch_runs](schedule_id,scheduled_for) WHERE trigger_type='scheduled'; CREATE UNIQUE INDEX UX_schedule_run_manual ON {s}.[requirement_batch_runs](schedule_id,trigger_request_id) WHERE trigger_type='manual'",
        f"CREATE TABLE {s}.[requirement_batch_run_items](run_item_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_batch_run_items PRIMARY KEY,batch_run_id NVARCHAR(64) NOT NULL,requirement_id NVARCHAR(64) NOT NULL,requirement_version_id NVARCHAR(64) NOT NULL,requirement_version_number INT NOT NULL,source_order INT NOT NULL,selection_status NVARCHAR(16) NOT NULL,selection_reason NVARCHAR(64) NOT NULL,phase1a_task_id NVARCHAR(128) NULL,execution_state NVARCHAR(32) NOT NULL,remote_job_id NVARCHAR(64) NULL,remote_job_state NVARCHAR(32) NULL,artifact_relative_path NVARCHAR(500) NULL,error_code NVARCHAR(64) NULL,error_message NVARCHAR(500) NULL,expired_at_selection BIT NOT NULL,expired_before_handoff BIT NOT NULL,deadline_elapsed_during_execution BIT NOT NULL,created_at DATETIMEOFFSET NOT NULL,evaluated_at DATETIMEOFFSET NOT NULL,handoff_started_at DATETIMEOFFSET NULL,dispatched_at DATETIMEOFFSET NULL,remote_completed_at DATETIMEOFFSET NULL,artifact_reconciled_at DATETIMEOFFSET NULL,completed_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT UQ_requirement_batch_run_item UNIQUE(batch_run_id,requirement_id),CONSTRAINT UQ_requirement_batch_run_order UNIQUE(batch_run_id,source_order),CONSTRAINT FK_run_item_version FOREIGN KEY(requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id))",
        f"CREATE TABLE {s}.[requirement_schedule_item_state](schedule_id NVARCHAR(64) NOT NULL,requirement_id NVARCHAR(64) NOT NULL,last_seen_requirement_version_id NVARCHAR(64) NULL,last_seen_requirement_version_number INT NULL,last_successful_requirement_version_id NVARCHAR(64) NULL,last_successful_requirement_version_number INT NULL,last_successful_run_item_id NVARCHAR(64) NULL,last_successful_at DATETIMEOFFSET NULL,updated_at DATETIMEOFFSET NOT NULL,CONSTRAINT PK_requirement_schedule_item_state PRIMARY KEY(schedule_id,requirement_id),CONSTRAINT FK_state_seen_version FOREIGN KEY(last_seen_requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id),CONSTRAINT FK_state_success_version FOREIGN KEY(last_successful_requirement_version_id) REFERENCES {r}.[requirement_versions](requirement_version_id))",
    ]


def validation_queries(schema: str, requirement_schema: str = "sra_requirement"):
    validate_schema_name(schema); validate_schema_name(requirement_schema)
    checks = []
    for table, columns in REQUIRED_COLUMNS.items():
        checks.append((f"columns:{table}", "SELECT c.name,c.is_nullable FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns c ON c.object_id=t.object_id WHERE s.name=? AND t.name=? ORDER BY c.column_id", (schema, table), columns))
    for key in REQUIRED_KEYS:
        checks.append((f"key:{key.name}", "SELECT s.name,t.name,kc.name,kc.type,c.name,ic.key_ordinal FROM sys.key_constraints kc JOIN sys.tables t ON t.object_id=kc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.index_columns ic ON ic.object_id=t.object_id AND ic.index_id=kc.unique_index_id JOIN sys.columns c ON c.object_id=t.object_id AND c.column_id=ic.column_id WHERE s.name=? AND kc.name=? ORDER BY ic.key_ordinal", (schema, key.name), key))
    for fk in required_foreign_keys(requirement_schema):
        checks.append((f"fk:{fk.name}", "SELECT ps.name,pt.name,fk.name,pc.name,rs.name,rt.name,rc.name,fkc.constraint_column_id FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id JOIN sys.tables pt ON pt.object_id=fk.parent_object_id JOIN sys.schemas ps ON ps.schema_id=pt.schema_id JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id JOIN sys.schemas rs ON rs.schema_id=rt.schema_id JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id WHERE ps.name=? AND fk.name=? ORDER BY fkc.constraint_column_id", (schema, fk.name), fk))
    return checks
