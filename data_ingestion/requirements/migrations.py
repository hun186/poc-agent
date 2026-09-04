from __future__ import annotations

from dataclasses import dataclass

import re

SCHEMA_VERSION = 1


def validate_schema_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise ValueError("invalid REQUIREMENT_DB_SCHEMA")
    return value


def migration_v1(schema: str) -> list[str]:
    """Canonical idempotent version-0 to version-1 DDL."""
    s = f"[{validate_schema_name(schema)}]"
    return [
        f"IF SCHEMA_ID(N'{schema}') IS NULL EXEC(N'CREATE SCHEMA {s}')",
        f"IF OBJECT_ID(N'{s}.[schema_version]', N'U') IS NULL CREATE TABLE {s}.[schema_version] (version INT NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[requirement_sources]', N'U') IS NULL CREATE TABLE {s}.[requirement_sources] (source_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_sources PRIMARY KEY, name NVARCHAR(240) NOT NULL, source_type NVARCHAR(32) NOT NULL, source_mode NVARCHAR(32) NOT NULL, source_config_json NVARCHAR(MAX) NOT NULL, import_profile_id NVARCHAR(64) NOT NULL, enabled BIT NOT NULL, created_by NVARCHAR(128) NOT NULL, created_at DATETIMEOFFSET NOT NULL, updated_by NVARCHAR(128) NOT NULL, updated_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[import_profiles]', N'U') IS NULL CREATE TABLE {s}.[import_profiles] (profile_id NVARCHAR(64) NOT NULL CONSTRAINT PK_import_profiles PRIMARY KEY, name NVARCHAR(240) NOT NULL, description NVARCHAR(1000) NOT NULL, enabled BIT NOT NULL, active_version_id NVARCHAR(64) NULL, created_by NVARCHAR(128) NOT NULL, created_at DATETIMEOFFSET NOT NULL, updated_by NVARCHAR(128) NOT NULL, updated_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[import_profile_versions]', N'U') IS NULL CREATE TABLE {s}.[import_profile_versions] (profile_version_id NVARCHAR(64) NOT NULL CONSTRAINT PK_import_profile_versions PRIMARY KEY, profile_id NVARCHAR(64) NOT NULL, version_number INT NOT NULL, format NVARCHAR(20) NOT NULL, source_mode NVARCHAR(32) NOT NULL, profile_json NVARCHAR(MAX) NOT NULL, profile_sha256 CHAR(64) NOT NULL, status NVARCHAR(20) NOT NULL, created_by NVARCHAR(128) NOT NULL, created_at DATETIMEOFFSET NOT NULL, approved_by NVARCHAR(128) NULL, approved_at DATETIMEOFFSET NULL, retired_at DATETIMEOFFSET NULL, CONSTRAINT UQ_import_profile_version UNIQUE(profile_id, version_number))",
        f"IF OBJECT_ID(N'{s}.[requirements]', N'U') IS NULL CREATE TABLE {s}.[requirements] (requirement_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirements PRIMARY KEY, source_id NVARCHAR(64) NOT NULL, external_item_id NVARCHAR(240) NOT NULL, created_at DATETIMEOFFSET NOT NULL, CONSTRAINT UQ_requirement_identity UNIQUE(source_id, external_item_id))",
        f"IF OBJECT_ID(N'{s}.[requirement_versions]', N'U') IS NULL CREATE TABLE {s}.[requirement_versions] (requirement_version_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_versions PRIMARY KEY, requirement_id NVARCHAR(64) NOT NULL, version_number INT NOT NULL, title NVARCHAR(1000) NOT NULL, prompt_content NVARCHAR(MAX) NOT NULL, source_updated_at DATETIMEOFFSET NOT NULL, expires_at DATETIMEOFFSET NULL, source_created_by BIGINT NULL, source_updated_by BIGINT NULL, source_created_at DATETIMEOFFSET NOT NULL, source_row_hash CHAR(64) NOT NULL, source_payload_hash CHAR(64) NOT NULL, execution_content_hash CHAR(64) NOT NULL, source_raw_json NVARCHAR(MAX) NOT NULL, created_at DATETIMEOFFSET NOT NULL, CONSTRAINT UQ_requirement_version UNIQUE(requirement_id, version_number))",
        f"IF OBJECT_ID(N'{s}.[requirement_sets]', N'U') IS NULL CREATE TABLE {s}.[requirement_sets] (requirement_set_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_sets PRIMARY KEY, source_id NVARCHAR(64) NOT NULL CONSTRAINT UQ_requirement_set_source UNIQUE, name NVARCHAR(240) NOT NULL, active_snapshot_id NVARCHAR(64) NULL, created_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[import_runs]', N'U') IS NULL CREATE TABLE {s}.[import_runs] (import_run_id NVARCHAR(64) NOT NULL CONSTRAINT PK_import_runs PRIMARY KEY, source_id NVARCHAR(64) NOT NULL, import_profile_version_id NVARCHAR(64) NOT NULL, source_uri_display NVARCHAR(500) NOT NULL, source_sha256 CHAR(64) NOT NULL, status NVARCHAR(20) NOT NULL, row_count INT NOT NULL, accepted_count INT NOT NULL, rejected_count INT NOT NULL, started_at DATETIMEOFFSET NOT NULL, completed_at DATETIMEOFFSET NULL, actor_kind NVARCHAR(20) NOT NULL, actor_id NVARCHAR(128) NOT NULL, error_summary NVARCHAR(1000) NULL)",
        f"IF OBJECT_ID(N'{s}.[import_run_rows]', N'U') IS NULL CREATE TABLE {s}.[import_run_rows] (import_run_id NVARCHAR(64) NOT NULL, source_row_number INT NULL, external_item_id NVARCHAR(240) NULL, row_status NVARCHAR(32) NOT NULL, source_row_hash CHAR(64) NULL, diagnostic_code NVARCHAR(80) NULL, diagnostic_message NVARCHAR(500) NULL)",
        f"IF OBJECT_ID(N'{s}.[requirement_set_snapshots]', N'U') IS NULL CREATE TABLE {s}.[requirement_set_snapshots] (snapshot_id NVARCHAR(64) NOT NULL CONSTRAINT PK_requirement_set_snapshots PRIMARY KEY, requirement_set_id NVARCHAR(64) NOT NULL, import_run_id NVARCHAR(64) NOT NULL, source_snapshot_sha256 CHAR(64) NOT NULL, import_profile_version_id NVARCHAR(64) NOT NULL, created_at DATETIMEOFFSET NOT NULL, activated_at DATETIMEOFFSET NOT NULL)",
        f"IF OBJECT_ID(N'{s}.[requirement_snapshot_items]', N'U') IS NULL CREATE TABLE {s}.[requirement_snapshot_items] (snapshot_id NVARCHAR(64) NOT NULL, requirement_id NVARCHAR(64) NOT NULL, requirement_version_id NVARCHAR(64) NOT NULL, source_order INT NOT NULL, CONSTRAINT PK_requirement_snapshot_items PRIMARY KEY(snapshot_id, requirement_id))",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_profile_version_profile') ALTER TABLE {s}.[import_profile_versions] ADD CONSTRAINT FK_requirement_profile_version_profile FOREIGN KEY(profile_id) REFERENCES {s}.[import_profiles](profile_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_source_profile') ALTER TABLE {s}.[requirement_sources] ADD CONSTRAINT FK_requirement_source_profile FOREIGN KEY(import_profile_id) REFERENCES {s}.[import_profiles](profile_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_source') ALTER TABLE {s}.[requirements] ADD CONSTRAINT FK_requirement_source FOREIGN KEY(source_id) REFERENCES {s}.[requirement_sources](source_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_version_requirement') ALTER TABLE {s}.[requirement_versions] ADD CONSTRAINT FK_requirement_version_requirement FOREIGN KEY(requirement_id) REFERENCES {s}.[requirements](requirement_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_set') ALTER TABLE {s}.[requirement_set_snapshots] ADD CONSTRAINT FK_requirement_snapshot_set FOREIGN KEY(requirement_set_id) REFERENCES {s}.[requirement_sets](requirement_set_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_item_snapshot') ALTER TABLE {s}.[requirement_snapshot_items] ADD CONSTRAINT FK_requirement_snapshot_item_snapshot FOREIGN KEY(snapshot_id) REFERENCES {s}.[requirement_set_snapshots](snapshot_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_item_version') ALTER TABLE {s}.[requirement_snapshot_items] ADD CONSTRAINT FK_requirement_snapshot_item_version FOREIGN KEY(requirement_version_id) REFERENCES {s}.[requirement_versions](requirement_version_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_set_source') ALTER TABLE {s}.[requirement_sets] ADD CONSTRAINT FK_requirement_set_source FOREIGN KEY(source_id) REFERENCES {s}.[requirement_sources](source_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_import_run_source') ALTER TABLE {s}.[import_runs] ADD CONSTRAINT FK_import_run_source FOREIGN KEY(source_id) REFERENCES {s}.[requirement_sources](source_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_import_run_profile_version') ALTER TABLE {s}.[import_runs] ADD CONSTRAINT FK_import_run_profile_version FOREIGN KEY(import_profile_version_id) REFERENCES {s}.[import_profile_versions](profile_version_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_import_run_row_run') ALTER TABLE {s}.[import_run_rows] ADD CONSTRAINT FK_import_run_row_run FOREIGN KEY(import_run_id) REFERENCES {s}.[import_runs](import_run_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_run') ALTER TABLE {s}.[requirement_set_snapshots] ADD CONSTRAINT FK_requirement_snapshot_run FOREIGN KEY(import_run_id) REFERENCES {s}.[import_runs](import_run_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_profile_version') ALTER TABLE {s}.[requirement_set_snapshots] ADD CONSTRAINT FK_requirement_snapshot_profile_version FOREIGN KEY(import_profile_version_id) REFERENCES {s}.[import_profile_versions](profile_version_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_snapshot_item_requirement') ALTER TABLE {s}.[requirement_snapshot_items] ADD CONSTRAINT FK_requirement_snapshot_item_requirement FOREIGN KEY(requirement_id) REFERENCES {s}.[requirements](requirement_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_import_profile_active_version') ALTER TABLE {s}.[import_profiles] ADD CONSTRAINT FK_import_profile_active_version FOREIGN KEY(active_version_id) REFERENCES {s}.[import_profile_versions](profile_version_id)",
        f"IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_requirement_set_active_snapshot') ALTER TABLE {s}.[requirement_sets] ADD CONSTRAINT FK_requirement_set_active_snapshot FOREIGN KEY(active_snapshot_id) REFERENCES {s}.[requirement_set_snapshots](snapshot_id)",
    ]


def bootstrap_schema_statements(schema: str) -> list[str]:
    """Create only the namespace and version container used to inspect state."""
    return migration_v1(schema)[:2]


def migration_0_to_1_statements(schema: str) -> list[str]:
    """Create/repair canonical v1 domain objects without changing the version row."""
    return migration_v1(schema)[2:]


# Runtime-required columns. Validation intentionally names every column rather than
# trusting an integer schema marker.
REQUIRED_COLUMNS = {
    "schema_version": ("version",),
    "requirement_sources": ("source_id", "name", "source_type", "source_mode", "source_config_json", "import_profile_id", "enabled", "created_by", "created_at", "updated_by", "updated_at"),
    "import_profiles": ("profile_id", "name", "description", "enabled", "active_version_id", "created_by", "created_at", "updated_by", "updated_at"),
    "import_profile_versions": ("profile_version_id", "profile_id", "version_number", "format", "source_mode", "profile_json", "profile_sha256", "status", "created_by", "created_at", "approved_by", "approved_at", "retired_at"),
    "requirements": ("requirement_id", "source_id", "external_item_id", "created_at"),
    "requirement_versions": ("requirement_version_id", "requirement_id", "version_number", "title", "prompt_content", "source_updated_at", "expires_at", "source_created_by", "source_updated_by", "source_created_at", "source_row_hash", "source_payload_hash", "execution_content_hash", "source_raw_json", "created_at"),
    "requirement_sets": ("requirement_set_id", "source_id", "name", "active_snapshot_id", "created_at"),
    "import_runs": ("import_run_id", "source_id", "import_profile_version_id", "source_uri_display", "source_sha256", "status", "row_count", "accepted_count", "rejected_count", "started_at", "completed_at", "actor_kind", "actor_id", "error_summary"),
    "import_run_rows": ("import_run_id", "source_row_number", "external_item_id", "row_status", "source_row_hash", "diagnostic_code", "diagnostic_message"),
    "requirement_set_snapshots": ("snapshot_id", "requirement_set_id", "import_run_id", "source_snapshot_sha256", "import_profile_version_id", "created_at", "activated_at"),
    "requirement_snapshot_items": ("snapshot_id", "requirement_id", "requirement_version_id", "source_order"),
}
@dataclass(frozen=True)
class KeyConstraint:
    name: str
    table: str
    columns: tuple[str, ...]
    kind: str


@dataclass(frozen=True)
class ForeignKey:
    name: str
    parent_table: str
    parent_columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]


REQUIRED_KEYS = (
    KeyConstraint("PK_requirement_sources", "requirement_sources", ("source_id",), "PK"),
    KeyConstraint("PK_import_profiles", "import_profiles", ("profile_id",), "PK"),
    KeyConstraint("PK_import_profile_versions", "import_profile_versions", ("profile_version_id",), "PK"),
    KeyConstraint("UQ_import_profile_version", "import_profile_versions", ("profile_id", "version_number"), "UQ"),
    KeyConstraint("PK_requirements", "requirements", ("requirement_id",), "PK"),
    KeyConstraint("UQ_requirement_identity", "requirements", ("source_id", "external_item_id"), "UQ"),
    KeyConstraint("PK_requirement_versions", "requirement_versions", ("requirement_version_id",), "PK"),
    KeyConstraint("UQ_requirement_version", "requirement_versions", ("requirement_id", "version_number"), "UQ"),
    KeyConstraint("PK_requirement_sets", "requirement_sets", ("requirement_set_id",), "PK"),
    KeyConstraint("UQ_requirement_set_source", "requirement_sets", ("source_id",), "UQ"),
    KeyConstraint("PK_import_runs", "import_runs", ("import_run_id",), "PK"),
    KeyConstraint("PK_requirement_set_snapshots", "requirement_set_snapshots", ("snapshot_id",), "PK"),
    KeyConstraint("PK_requirement_snapshot_items", "requirement_snapshot_items", ("snapshot_id", "requirement_id"), "PK"),
)

REQUIRED_FOREIGN_KEYS = (
    ForeignKey("FK_requirement_profile_version_profile", "import_profile_versions", ("profile_id",), "import_profiles", ("profile_id",)),
    ForeignKey("FK_requirement_source_profile", "requirement_sources", ("import_profile_id",), "import_profiles", ("profile_id",)),
    ForeignKey("FK_requirement_source", "requirements", ("source_id",), "requirement_sources", ("source_id",)),
    ForeignKey("FK_requirement_version_requirement", "requirement_versions", ("requirement_id",), "requirements", ("requirement_id",)),
    ForeignKey("FK_requirement_snapshot_set", "requirement_set_snapshots", ("requirement_set_id",), "requirement_sets", ("requirement_set_id",)),
    ForeignKey("FK_requirement_snapshot_item_snapshot", "requirement_snapshot_items", ("snapshot_id",), "requirement_set_snapshots", ("snapshot_id",)),
    ForeignKey("FK_requirement_snapshot_item_version", "requirement_snapshot_items", ("requirement_version_id",), "requirement_versions", ("requirement_version_id",)),
    ForeignKey("FK_requirement_set_source", "requirement_sets", ("source_id",), "requirement_sources", ("source_id",)),
    ForeignKey("FK_import_run_source", "import_runs", ("source_id",), "requirement_sources", ("source_id",)),
    ForeignKey("FK_import_run_profile_version", "import_runs", ("import_profile_version_id",), "import_profile_versions", ("profile_version_id",)),
    ForeignKey("FK_import_run_row_run", "import_run_rows", ("import_run_id",), "import_runs", ("import_run_id",)),
    ForeignKey("FK_requirement_snapshot_run", "requirement_set_snapshots", ("import_run_id",), "import_runs", ("import_run_id",)),
    ForeignKey("FK_requirement_snapshot_profile_version", "requirement_set_snapshots", ("import_profile_version_id",), "import_profile_versions", ("profile_version_id",)),
    ForeignKey("FK_requirement_snapshot_item_requirement", "requirement_snapshot_items", ("requirement_id",), "requirements", ("requirement_id",)),
    ForeignKey("FK_import_profile_active_version", "import_profiles", ("active_version_id",), "import_profile_versions", ("profile_version_id",)),
    ForeignKey("FK_requirement_set_active_snapshot", "requirement_sets", ("active_snapshot_id",), "requirement_set_snapshots", ("snapshot_id",)),
)


def nullable_diagnostic_check(schema: str) -> tuple[str, tuple[object, ...]]:
    return (
        "SELECT c.is_nullable FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "JOIN sys.columns c ON c.object_id=t.object_id "
        "WHERE s.name=? AND t.name='import_run_rows' AND c.name='source_row_number'",
        (validate_schema_name(schema),),
    )


def repair_diagnostic_nullability_statement(schema: str) -> str:
    s = f"[{validate_schema_name(schema)}]"
    return f"ALTER TABLE {s}.[import_run_rows] ALTER COLUMN source_row_number INT NULL"


def validation_queries(schema: str) -> list[tuple[str, str, tuple[object, ...], object]]:
    """Return named scalar checks; each query must return exactly the expected count."""
    validate_schema_name(schema)
    checks: list[tuple[str, str, tuple[object, ...], object]] = []
    for table, columns in REQUIRED_COLUMNS.items():
        placeholders = ",".join("?" for _ in columns)
        checks.append((
            f"columns:{table}",
            "SELECT COUNT(DISTINCT c.name) FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
            "JOIN sys.columns c ON c.object_id=t.object_id WHERE s.name=? AND t.name=? "
            f"AND c.name IN ({placeholders})",
            (schema, table, *columns), len(columns),
        ))
    for key in REQUIRED_KEYS:
        checks.append((
            f"key:{key.name}",
            "SELECT s.name,t.name,kc.name,kc.type,c.name,ic.key_ordinal FROM sys.key_constraints kc "
            "JOIN sys.tables t ON t.object_id=kc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id "
            "JOIN sys.index_columns ic ON ic.object_id=kc.parent_object_id AND ic.index_id=kc.unique_index_id "
            "JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id "
            "WHERE s.name=? AND kc.name=? ORDER BY ic.key_ordinal",
            (schema, key.name),
            tuple((schema, key.table, key.name, key.kind, column, ordinal) for ordinal, column in enumerate(key.columns, 1)),
        ))
    for fk in REQUIRED_FOREIGN_KEYS:
        checks.append((
            f"fk:{fk.name}",
            "SELECT ps.name,pt.name,fk.name,pc.name,rs.name,rt.name,rc.name,fkc.constraint_column_id "
            "FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id "
            "JOIN sys.tables pt ON pt.object_id=fk.parent_object_id JOIN sys.schemas ps ON ps.schema_id=pt.schema_id "
            "JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id "
            "JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id JOIN sys.schemas rs ON rs.schema_id=rt.schema_id "
            "JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id "
            "WHERE ps.name=? AND fk.name=? ORDER BY fkc.constraint_column_id",
            (schema, fk.name),
            tuple((schema, fk.parent_table, fk.name, parent, schema, fk.referenced_table, referenced, ordinal)
                  for ordinal, (parent, referenced) in enumerate(zip(fk.parent_columns, fk.referenced_columns, strict=True), 1)),
        ))
    return checks
